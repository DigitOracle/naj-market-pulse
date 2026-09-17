"""ev_cityengine.py -- 3D track of Azimuth EV: one charge-station model per real Dubai coordinate.

Why this exists: the 2D map track (render_ev_map.py) answers "where are the chargers". It cannot
answer "what is actually standing there", which is the question a DEWA or RTA reviewer asks of a
digital twin. DEWA deploys a small standard set of Green Charger units, so ~4 archetypes instanced
308 times is the honest model: the massing is generic-by-class and says so, while the POSITION of
every instance is a real registered coordinate, not a sample.

Source of truth is v_ev_charge_points (scripts/build_ev_union.py): 186 DEWA register rows + 122
OpenChargeMap rows after a 150 m dedup, each carrying its own provenance. Nothing here invents a
point, and every instance in the output index names the row it came from.

PROJECTION. Points arrive WGS84. CityEngine, PRT and OBJ are all metric-Cartesian, so degrees are
projected to EPSG:32640 (UTM zone 40N), which is the correct zone for Dubai (55.27E sits inside
54E-60E). A local origin is subtracted so vertex coordinates stay small enough for float32 viewers;
that origin is written into the index JSON, so any instance can be put back on the globe exactly.

EXTENT, HONESTLY. The union layer is UAE-wide, not Dubai-only: OpenChargeMap was pulled for country
AE, so 47 of the 308 rows sit outside Dubai (Abu Dhabi, the Western Region, Al Ain) and 4 of those
sit west of 54E, which is UTM zone 39N territory. Zone 40N still projects them -- it just stretches,
by about 2 mm/m at the far end -- so nothing is dropped silently: the count and the worst-case scale
factor are printed on every run and written into the index. Pass --bbox dubai for a Dubai-only scene.

------------------------------------------------------------------------------------------------
PYPRT REALITY CHECK -- measured on this machine, 17 Sep 2026, not assumed:

    pyprt 1.12.0.12, PRT API version [3, 3, 11669]
    initialize_prt() / is_prt_initialized() / shutdown_prt() are all DEPRECATED -- PRT now
    initialises on import and its lifetime is tied to the module's.
    Public surface: InitialShape, ModelGenerator, GeneratedModel, get_rpk_attributes_info,
    get_api_version.

    WORKS headlessly: generation from a PRE-BUILT .rpk. Verified against
    C:\\Dev\\cga-library\\02_open_license\\pyprt-examples\\data\\extrusion_rule.rpk -- 1 model,
    8 vertices, 6 faces, no CGA errors; get_rpk_attributes_info() read its 5 attributes.

    DOES NOT WORK: feeding PRT a .cga. PRT answers
        "could not find a resolve map provider which can handle the scheme or uri: 'file:/...cga'"
    and then generate_model() returns an EMPTY LIST rather than raising -- a silent failure that
    will look like success if you only check for exceptions.

    WHY: an .rpk is a 7z archive of COMPILED .cgb bytecode. The compiler lives in CityEngine
    (plugins/com.esri.cgac_*.jar), not in PRT: pyprt/bin ships com.esri.prt.core.dll, glutess.dll
    and the .pyd, and pyprt/lib ships the format codecs -- no cgac, no compiler of any kind.
    So PyPRT is a RUNTIME, and a CGA rule cannot be turned into geometry without one pass through
    CityEngine. That is a licence/tooling boundary, not a bug and not something a script can route
    around.

WHAT THIS SCRIPT DOES ABOUT IT. Two paths, and it always says which one it took:

    1. --rpk PATH    PyPRT path. Builds one InitialShape per charge point, passes archetype /
                     totalnbofconnectors / max_power_kw as CGA attributes, generates, and writes
                     the returned meshes. UNTESTED -- there is no EVCharger.rpk to test it with
                     yet. (If per-leaf materials matter more than one colour per instance, swap
                     the 'com.esri.pyprt.PyEncoder' call for 'com.esri.prt.codecs.OBJEncoder',
                     which writes its own OBJ+MTL straight to disk.)

    2. default       Pure-Python path. Writes the SAME massing as data/ev/cityengine/EVCharger.cga
                     -- same parts, same dimensions, same colours, kept in the MASSING table below
                     -- with a stdlib box/cylinder mesh writer. Real, viewable, verifiable geometry
                     today. It is not procedural in the CGA sense and does not pretend to be.

WHAT A HUMAN MUST DO IN THE CITYENGINE GUI to finish the pipeline (CityEngine 2025.1 is installed
at C:\\Program Files\\ArcGIS\\CityEngine2025.1, so this is a local job, not a procurement one):

    1. New CityEngine project; copy data/ev/cityengine/EVCharger.cga into its rules/ folder.
    2. Open the .cga -- the editor compiles on save and lists errors inline. The file has NEVER
       been compiled, so expect some. Fix them there; mirror any dimension change back into the
       MASSING table below so the two paths do not drift.
    3. Right-click the .cga > Share As... > Rule Package (.rpk), start rule `Point`.
    4. Save it as data/ev/cityengine/EVCharger.rpk.
    5. python scripts/ev_cityengine.py build --rpk data/ev/cityengine/EVCharger.rpk
------------------------------------------------------------------------------------------------

Usage:
    python scripts/ev_cityengine.py probe                    # what can PyPRT actually do here?
    python scripts/ev_cityengine.py build                    # 308 stations -> data/ev/cityengine/out/
    python scripts/ev_cityengine.py build --source duckdb    # read the view instead of the GeoJSON
    python scripts/ev_cityengine.py build --limit 20 --vary-heading
    python scripts/ev_cityengine.py build --rpk data/ev/cityengine/EVCharger.rpk
"""
import argparse, hashlib, json, math, os, sys

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
DB = os.path.join(ROOT, "data", "graph", "najma.duckdb")
GEOJSON = os.path.join(ROOT, "data", "ev", "ev_charge_points.geojson")
CE_DIR = os.path.join(ROOT, "data", "ev", "cityengine")
OUT_DIR = os.path.join(CE_DIR, "out")
CGA = os.path.join(CE_DIR, "EVCharger.cga")
VIEW = "v_ev_charge_points"

SRC_CRS = "EPSG:4326"                   # WGS84 lon/lat as the GeoJSON carries it
DST_CRS = "EPSG:32640"                  # UTM zone 40N -- metres, correct zone for Dubai

# The union layer is UAE-wide, not Dubai-only: OCM was pulled for country AE, so 47 of the 308 rows
# sit outside Dubai (Abu Dhabi, the Western Region, Al Ain). Nothing is dropped silently -- use
# --bbox dubai when the scene must be Dubai alone, and read the count the script prints.
DUBAI_BBOX = (54.85, 24.75, 55.65, 25.45)       # lon_min, lat_min, lon_max, lat_max
ZONE40_LON = (54.0, 60.0)                       # UTM 40N's own 6-degree band; CM is 57E

# --- massing, mirrored from EVCharger.cga --------------------------------------------------------
# Any change here must be made there too, and vice versa. These are DEWA's four published Green
# Charger classes; dimensions are representative of the class, NOT surveyed per site.
MASSING = {
    "wallbox_ac":     {"w": 0.40, "d": 0.20, "h": 0.60, "mount": 1.00, "colour": "#8cc63f"},
    "public_ac_dual": {"w": 0.40, "d": 0.30, "h": 1.40, "mount": 0.00, "colour": "#00a651"},
    "fast_dc":        {"w": 0.70, "d": 0.40, "h": 1.60, "mount": 0.00, "colour": "#0072bc"},
    "ultra_fast_dc":  {"w": 1.20, "d": 0.60, "h": 2.00, "mount": 0.00, "colour": "#e8452c"},
}
UNKNOWN = {"w": 0.40, "d": 0.30, "h": 1.40, "mount": 0.00, "colour": "#999999"}

MAX_CONNECTORS = 6          # cosmetic cap; the true count stays in the index JSON
PAD_MARGIN = 0.60
PAD_H = 0.10
PLATE_T = 0.03
SUPPORT_W = 0.28
SUPPORT_T = 0.06
CABLE_R = 0.025
CABLE_SIDES = 8
HEAD_W = 0.09
HEAD_H = 0.13

COL_PAD = "#b4b4b4"
COL_SCREEN = "#1a1a1a"
COL_CABLE = "#2b2b2b"
COL_HEAD = "#f2f2f2"


def log(*a): print(*a, flush=True)


# --- geometry primitives -------------------------------------------------------------------------
# Everything is built y-up, x=east, z=south (a right-handed y-up frame, which is what CityEngine,
# PRT and OBJ all assume). --up z flips it into the x=east / y=north / z=up frame GIS tools expect.

def box(verts, faces, x, y, z, w, h, d):
    """Axis-aligned box with its MIN corner at (x, y, z). Six quads, outward normals."""
    b = len(verts)
    verts.extend([(x, y, z), (x + w, y, z), (x + w, y, z + d), (x, y, z + d),
                  (x, y + h, z), (x + w, y + h, z), (x + w, y + h, z + d), (x, y + h, z + d)])
    for f in ((0, 1, 2, 3), (4, 7, 6, 5), (0, 4, 5, 1), (3, 2, 6, 7), (0, 3, 7, 4), (1, 5, 6, 2)):
        faces.append(tuple(b + i for i in f))


def cylinder(verts, faces, cx, y, cz, r, h, sides=CABLE_SIDES):
    """Vertical cylinder, base centre (cx, y, cz). Quad wall + triangle-fan caps."""
    b = len(verts)
    ring = [(cx + r * math.cos(2 * math.pi * i / sides), 2 * math.pi * i / sides,
             cz + r * math.sin(2 * math.pi * i / sides)) for i in range(sides)]
    for px, _, pz in ring: verts.append((px, y, pz))                    # bottom ring  b + i
    for px, _, pz in ring: verts.append((px, y + h, pz))                # top ring     b + sides + i
    verts.append((cx, y, cz))                                           # bottom hub   b + 2*sides
    verts.append((cx, y + h, cz))                                       # top hub      b + 2*sides+1
    hub_b, hub_t = b + 2 * sides, b + 2 * sides + 1
    for i in range(sides):
        j = (i + 1) % sides
        faces.append((b + i, b + sides + i, b + sides + j, b + j))      # wall
        faces.append((hub_b, b + i, b + j))                             # bottom cap
        faces.append((hub_t, b + sides + j, b + sides + i))             # top cap


def station(archetype, connectors):
    """One charge station as [(material_name, [vertices], [faces])], origin at the pad centre,
    ground at y=0. Part for part the same model as EVCharger.cga."""
    m = MASSING.get(archetype, UNKNOWN)
    w, d, h, mount = m["w"], m["d"], m["h"], m["mount"]
    pad_w, pad_d = w + 2 * PAD_MARGIN, d + 2 * PAD_MARGIN
    x0, z0 = -pad_w / 2.0, -pad_d / 2.0                 # pad min corner; CGA does this with center(xz)
    n = max(1, min(int(connectors or 1), MAX_CONNECTORS))
    parts = []

    def part(name):
        v, f = [], []
        parts.append((name, v, f))
        return v, f

    v, f = part("pad")
    box(v, f, x0, 0.0, z0, pad_w, PAD_H, pad_d)

    if mount > 0.0:                                     # wall plate -- a wall box would float without it
        v, f = part("pad")
        box(v, f, x0 + PAD_MARGIN + (w - SUPPORT_W) / 2, PAD_H, z0 + PAD_MARGIN + d,
            SUPPORT_W, mount + h, SUPPORT_T)

    v, f = part("unit_" + (archetype if archetype in MASSING else "unknown"))
    box(v, f, x0 + PAD_MARGIN, PAD_H + mount, z0 + PAD_MARGIN, w, h, d)

    v, f = part("screen")                               # faceplate, proud of the cabinet front
    plate_w, plate_h = w * 0.60, h * 0.28
    box(v, f, x0 + PAD_MARGIN + (w - plate_w) / 2, PAD_H + mount + h * 0.55,
        z0 + PAD_MARGIN + d, plate_w, plate_h, PLATE_T)

    cable_len = h * 0.30
    conn_y = PAD_H + mount + h * 0.45
    cv, cf = part("cable")
    hv, hf = part("head")
    for i in range(1, n + 1):                           # evenly across the cabinet front
        cx = x0 + PAD_MARGIN + w * ((i - 0.5) / n)
        cz = z0 + PAD_MARGIN + d + PLATE_T + CABLE_R
        cylinder(cv, cf, cx, conn_y - cable_len, cz, CABLE_R, cable_len)
        box(hv, hf, cx - HEAD_W / 2, conn_y - cable_len - HEAD_H, cz - HEAD_W / 2,
            HEAD_W, HEAD_H, HEAD_W)
    return parts


def place(verts, east, north, heading_deg, up):
    """Local station coords -> scene coords. heading rotates about the vertical axis."""
    a = math.radians(heading_deg)
    ca, sa = math.cos(a), math.sin(a)
    out = []
    for x, y, z in verts:
        rx, rz = x * ca + z * sa, -x * sa + z * ca
        out.append((east + rx, y, north + rz) if up == "y" else (east + rx, north - rz, y))
    return out


# --- input ---------------------------------------------------------------------------------------

def read_points(source):
    """[{point_id, archetype, totalnbofconnectors, max_power_kw, lon, lat, ...}] from either input.
    The GeoJSON is the default because it is the artefact the 2D track also consumes, so the two
    tracks provably see the same 308 rows."""
    if source == "duckdb":
        import duckdb
        if not os.path.exists(DB): sys.exit(f"duckdb not found: {DB}")
        con = duckdb.connect(DB, read_only=True)        # read_only: this script never writes the db
        cols = ("point_id, source, authority, operator, location_name, archetype, "
                "totalnbofconnectors, max_power_kw, longitude, latitude")
        rows = con.execute(f"select {cols} from {VIEW} "
                           f"where latitude is not null and longitude is not null").fetchall()
        names = [c.strip() for c in cols.split(",")]
        out = [dict(zip(names, r)) for r in rows]
        for r in out:
            r["lon"], r["lat"] = float(r.pop("longitude")), float(r.pop("latitude"))
        return out, f"duckdb {VIEW}"

    if not os.path.exists(GEOJSON):
        sys.exit(f"geojson not found: {GEOJSON} -- run `python scripts/build_ev_union.py --export`")
    fc = json.load(open(GEOJSON, encoding="utf-8"))
    out = []
    for feat in fc.get("features", []):
        g = feat.get("geometry") or {}
        if g.get("type") != "Point": continue
        lon, lat = g["coordinates"][0], g["coordinates"][1]
        p = dict(feat.get("properties") or {})
        p["lon"], p["lat"] = float(lon), float(lat)
        out.append(p)
    return out, os.path.relpath(GEOJSON, ROOT)


# --- PyPRT path (requires a compiled .rpk) --------------------------------------------------------

def prt_probe():
    """Report what PyPRT can and cannot do here. Everything printed is measured, not assumed."""
    try:
        import pyprt
    except Exception as e:
        log(f"pyprt NOT importable: {type(e).__name__}: {e}"); return
    log(f"pyprt module      : {pyprt.__file__}")
    log(f"PRT API version   : {pyprt.get_api_version()}")
    log(f"public surface    : {', '.join(d for d in dir(pyprt) if not d.startswith('_'))}")
    log("note              : initialize_prt/is_prt_initialized/shutdown_prt are deprecated; PRT "
        "initialises on import")
    rpk = default_rpk()
    log(f"EVCharger.rpk     : {'present -> ' + rpk if rpk else 'ABSENT (expected at ' + os.path.join(CE_DIR, 'EVCharger.rpk') + ')'}")
    log(f"EVCharger.cga     : {'present' if os.path.exists(CGA) else 'ABSENT'} -- PRT cannot consume "
        "a .cga; it needs the compiled .rpk, and ships no compiler")
    if rpk:
        try:
            log(f"rpk attributes    : {pyprt.get_rpk_attributes_info(rpk)}")
        except Exception as e:
            log(f"rpk attributes    : FAILED {type(e).__name__}: {e}")


def default_rpk():
    p = os.path.join(CE_DIR, "EVCharger.rpk")
    return p if os.path.exists(p) else None


def prt_generate(points, rpk, origin, up):
    """UNTESTED -- no EVCharger.rpk exists yet. One InitialShape per charge point: a pad-sized
    square footprint already sitting at the projected coordinate, so the rule only has to build
    upwards. PRT returns an empty model list (no exception) when a rule fails, so that is checked."""
    import pyprt
    # PRT resolves the rule package itself and needs an ABSOLUTE path: handed a relative one it
    # reports "RPK/7zip file has invalid header" for the path with the drive letter stripped, which
    # reads like a corrupt archive rather than the missing file it actually is.
    rpk = os.path.abspath(rpk)
    shapes, meta = [], []
    for p in points:
        m = MASSING.get(p.get("archetype"), UNKNOWN)
        hw, hd = (m["w"] + 2 * PAD_MARGIN) / 2.0, (m["d"] + 2 * PAD_MARGIN) / 2.0
        e, n = p["_e"] - origin[0], p["_n"] - origin[1]
        if up == "y":
            quad = [e - hw, 0, n - hd,  e - hw, 0, n + hd,  e + hw, 0, n + hd,  e + hw, 0, n - hd]
        else:
            quad = [e - hw, n - hd, 0,  e - hw, n + hd, 0,  e + hw, n + hd, 0,  e + hw, n - hd, 0]
        shapes.append(pyprt.InitialShape(quad))
        meta.append(p)
    attrs = [{"archetype": str(p.get("archetype") or ""),
              "totalnbofconnectors": float(p.get("totalnbofconnectors") or 1),
              "max_power_kw": float(p.get("max_power_kw") or 0)} for p in meta]
    models = pyprt.ModelGenerator(shapes).generate_model(
        attrs, rpk, "com.esri.pyprt.PyEncoder", {"emitGeometry": True, "emitReport": True})
    if not models:
        sys.exit(f"PRT returned no models from {rpk}. PRT fails silently here -- check that the rpk "
                 f"is a real compiled rule package and that its start rule accepts a polygon shape.")
    out = []
    for md in models:
        if md is None: continue
        errs = md.get_cga_errors()
        if errs: log(f"  CGA errors on shape {md.get_initial_shape_index()}: {errs}")
        vs = md.get_vertices()
        verts = [(vs[i], vs[i + 1], vs[i + 2]) for i in range(0, len(vs), 3)]
        idx, faces, at = list(md.get_indices()), [], 0
        for c in md.get_faces():
            faces.append(tuple(idx[at:at + c])); at += c
        p = meta[md.get_initial_shape_index()]
        mat = "unit_" + (p.get("archetype") if p.get("archetype") in MASSING else "unknown")
        out.append((p, [(mat, verts, faces)]))
    return out


# --- output --------------------------------------------------------------------------------------

def hex_rgb(h):
    h = h.lstrip("#")
    return tuple(round(int(h[i:i + 2], 16) / 255.0, 4) for i in (0, 2, 4))


def write_mtl(path):
    mats = {"pad": COL_PAD, "screen": COL_SCREEN, "cable": COL_CABLE, "head": COL_HEAD,
            "unit_unknown": UNKNOWN["colour"]}
    mats.update({"unit_" + k: v["colour"] for k, v in MASSING.items()})
    with open(path, "w", encoding="utf-8") as f:
        f.write("# Azimuth EV -- charge station materials, colour-coded by DEWA Green Charger class\n")
        for name, col in sorted(mats.items()):
            r, g, b = hex_rgb(col)
            f.write(f"\nnewmtl {name}\nKd {r} {g} {b}\nKa 0 0 0\nKs 0.1 0.1 0.1\nNs 12\nd 1\nillum 2\n")
    return len(mats)


def write_obj(path, mtl_name, instances, header):
    """instances: [(point_dict, [(material, [(x,y,z)...], [(i,j,k[,l])...])])] -- indices local to
    each part. One OBJ object group per charge point so a viewer can isolate a single station."""
    nv = nf = 0
    with open(path, "w", encoding="utf-8") as f:
        for line in header: f.write(f"# {line}\n")
        f.write(f"mtllib {mtl_name}\n")
        for p, parts in instances:
            pid = str(p.get("point_id") or "unknown").replace(" ", "_")
            f.write(f"\no EV_{pid}\n")
            for mat, verts, faces in parts:
                if not faces: continue
                base = nv
                for x, y, z in verts:
                    f.write(f"v {x:.4f} {y:.4f} {z:.4f}\n")
                nv += len(verts)
                f.write(f"usemtl {mat}\n")
                for face in faces:
                    f.write("f " + " ".join(str(base + i + 1) for i in face) + "\n")
                nf += len(faces)
    return nv, nf


def build(a):
    points, src = read_points(a.source)
    if not points: sys.exit("no charge points read")
    log(f"read {len(points)} charge points from {src}")

    if a.bbox == "dubai":
        lo0, la0, lo1, la1 = DUBAI_BBOX
        keep = [p for p in points if lo0 <= p["lon"] <= lo1 and la0 <= p["lat"] <= la1]
        log(f"bbox dubai        : kept {len(keep)}, set aside {len(points) - len(keep)} UAE-wide rows "
            f"(OCM was pulled for country AE, not for Dubai)")
        points = keep
    if a.limit: points = points[:a.limit]

    from pyproj import Transformer
    tr = Transformer.from_crs(SRC_CRS, DST_CRS, always_xy=True)
    for p in points:
        p["_e"], p["_n"] = tr.transform(p["lon"], p["lat"])
    log(f"projected {SRC_CRS} -> {DST_CRS} (UTM 40N, metres)")

    # UTM is defined outside its own band but stretches as it goes. Dubai sits comfortably inside
    # zone 40N; the Western Region rows do not, so the stretch is measured and reported rather than
    # left for someone to discover in a scale bar. k ~ k0 * (1 + q^2/2), q = dlon_rad * cos(lat).
    outside = [p for p in points if not ZONE40_LON[0] <= p["lon"] <= ZONE40_LON[1]]
    worst = max((0.9996 * (1 + (math.radians(p["lon"] - 57.0) * math.cos(math.radians(p["lat"]))) ** 2 / 2)
                 for p in points), default=1.0)
    log(f"zone 40N check    : {len(outside)} point(s) west of 54E (zone 39N territory); worst-case "
        f"scale factor {worst:.5f} ({abs(worst - 1) * 1000:.1f} mm/m)")

    # Local origin: the rounded centroid. Keeps vertices in the hundreds of metres instead of the
    # millions, which float32 viewers mangle. The offset is written to the index so it is reversible.
    ox = round(sum(p["_e"] for p in points) / len(points), 1)
    oy = round(sum(p["_n"] for p in points) / len(points), 1)
    log(f"local origin      : E {ox} N {oy} ({DST_CRS})")

    os.makedirs(OUT_DIR, exist_ok=True)
    rpk = a.rpk or (default_rpk() if a.use_rpk_if_present else None)

    instances, drawn, mode = [], 0, ""
    if rpk:
        mode = f"PyPRT / {os.path.relpath(rpk, ROOT)}"
        log(f"generator         : {mode}")
        for p, parts in prt_generate(points, rpk, (ox, oy), a.up):
            instances.append((p, parts))
            drawn += max(1, min(int(p.get("totalnbofconnectors") or 1), MAX_CONNECTORS))
    else:
        mode = "pure-Python mesh writer (no .rpk -- PRT cannot compile EVCharger.cga itself)"
        log(f"generator         : {mode}")
        for p in points:
            head = 0.0
            if a.vary_heading:      # cosmetic only; no bearing exists in either source register
                head = int(hashlib.md5(str(p.get("point_id")).encode()).hexdigest()[:4], 16) % 360
            n = max(1, min(int(p.get("totalnbofconnectors") or 1), MAX_CONNECTORS))
            parts = [(mat, place(v, p["_e"] - ox, p["_n"] - oy, head, a.up), f)
                     for mat, v, f in station(p.get("archetype"), n)]
            instances.append((p, parts))
            drawn += n

    stem = "ev_chargers_utm40n"
    mtl_path = os.path.join(OUT_DIR, stem + ".mtl")
    obj_path = os.path.join(OUT_DIR, stem + ".obj")
    idx_path = os.path.join(OUT_DIR, stem + "_index.json")

    nmat = write_mtl(mtl_path)
    nv, nf = write_obj(obj_path, stem + ".mtl", instances, [
        "Azimuth EV -- 3D track -- DigitAlchemy(R) Tech Limited",
        f"source          : {src} (DEWA register + OpenChargeMap, deduplicated)",
        f"generator       : {mode}",
        f"massing         : generic per DEWA Green Charger class -- NOT surveyed per site",
        f"positions       : real registered coordinates, {SRC_CRS} -> {DST_CRS}",
        f"local origin    : E {ox} N {oy} ({DST_CRS}) -- add this back for true UTM",
        f"axes            : {'y-up (x=east, z=south) -- CityEngine/PRT convention' if a.up == 'y' else 'z-up (x=east, y=north) -- GIS convention'}",
        f"instances       : {len(instances)}",
    ])

    by_arch = {}
    for p, _ in instances:
        by_arch[p.get("archetype")] = by_arch.get(p.get("archetype"), 0) + 1
    json.dump({
        "project": "Azimuth EV -- 3D track",
        "source": src,
        "generator": mode,
        "crs": DST_CRS,
        "local_origin": {"easting": ox, "northing": oy,
                         "note": "add to every vertex x/z (or x/y when --up z) for true UTM 40N"},
        "axes": "y-up, x=east, z=south" if a.up == "y" else "z-up, x=east, y=north",
        "bbox_filter": a.bbox,
        "points_outside_utm40n_band": len(outside),
        "worst_case_scale_factor": round(worst, 6),
        "instances": len(instances),
        "connector_elements_drawn": drawn,
        "connector_cap": MAX_CONNECTORS,
        "by_archetype": by_arch,
        "massing_note": "dimensions are representative of the DEWA Green Charger class, not surveyed",
        "points": [{"point_id": p.get("point_id"), "archetype": p.get("archetype"),
                    "source": p.get("source"), "authority": p.get("authority"),
                    "operator": p.get("operator"), "location_name": p.get("location_name"),
                    "totalnbofconnectors": p.get("totalnbofconnectors"),
                    "max_power_kw": p.get("max_power_kw"),
                    "lon": p["lon"], "lat": p["lat"],
                    "utm_e": round(p["_e"], 3), "utm_n": round(p["_n"], 3),
                    "local_x": round(p["_e"] - ox, 3), "local_y": round(p["_n"] - oy, 3)}
                   for p, _ in instances],
    }, open(idx_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    log("")
    for pth in (obj_path, mtl_path, idx_path):
        log(f"wrote {pth}  ({os.path.getsize(pth):,} bytes)")
    log(f"\n{len(instances)} stations | {nv:,} vertices | {nf:,} faces | {drawn} connector elements "
        f"| {nmat} materials")
    for k in sorted(by_arch, key=lambda k: -by_arch[k]):
        log(f"  {k:<16} {by_arch[k]:>4}")
    if not rpk:
        log("\nThis is the pure-Python path. PRT has no CGA compiler, so data/ev/cityengine/EVCharger.cga")
        log("must be compiled to an .rpk once in the CityEngine GUI before --rpk can be used; see this")
        log("script's docstring for the four steps.")


def main():
    ap = argparse.ArgumentParser(description="Azimuth EV 3D track: instance charge-station models "
                                             "at real Dubai coordinates.")
    ap.add_argument("cmd", choices=["probe", "build"])
    ap.add_argument("--source", choices=["geojson", "duckdb"], default="geojson",
                    help="where the points come from (default geojson, the same artefact the 2D track uses)")
    ap.add_argument("--rpk", default=None, help="compiled rule package -- switches on the PyPRT path")
    ap.add_argument("--use-rpk-if-present", action="store_true",
                    help="use data/ev/cityengine/EVCharger.rpk automatically when it exists")
    ap.add_argument("--limit", type=int, default=0, help="first N points only (smoke tests)")
    ap.add_argument("--bbox", choices=["none", "dubai"], default="none",
                    help="'dubai' keeps only the Dubai rows; default keeps all 308, including the "
                         "47 UAE-wide OCM/DEWA rows, and says so")
    ap.add_argument("--up", choices=["y", "z"], default="y",
                    help="y = CityEngine/PRT convention (default); z = GIS convention")
    ap.add_argument("--vary-heading", action="store_true",
                    help="COSMETIC: stable pseudo-random rotation per point_id. No bearing exists in "
                         "either register, so the default is north-aligned and honest.")
    a = ap.parse_args()
    if a.cmd == "probe": return prt_probe()
    return build(a)


if __name__ == "__main__":
    main()
