"""LOD 3 film-lane build: generate ONE district with rules/najma_v4.cga (real facade geometry) and export
it to Datasmith under a separate name, next to (never over) the flat export from ce_export_datasmith.py.

Per slug:
  open /najma/scenes/<slug>.cej (never saved) -> rank shapes by OID, map to buildings.geojson features
  (ce_batch_v2 helpers) -> name "b<i>_<class>_s<status>", push fclass / fvar / bHeight / levels as object
  attrs -> assign the rule, LOD 3 -> generateModels -> reports pass (scripts/ce_report_v2.py: GFA, Storeys,
  Faces, Faces.<slot>) -> Datasmith export (UnrealExportModelSettings, PERINITIALSHAPE, metadata ALL,
  Unreal base materials, SAME global offset as data/ce/_datasmith/<slug>_georef.json so it lands on the
  existing import in Unreal) -> parse the export log + .udatasmith for failures / material slots ->
  data/ce/_datasmith/<name>.udatasmith + <name>_Assets/ + <name>_georef.json + <name>_stats.json.

Because the shapes are renamed in the SAME session, the Datasmith actors carry the b<i> names (the flat
export kept CE's "unnamed_N" names because it re-opened the saved scene).

Lock protocol as the other CE drivers: data/ce/.ce_lock (wait 20 s polls, 20 min). CE 2025.1 must be
running with the Python bridge on 25333. z = -northing in the CE frame.

Usage:  python scripts/ce_lod3_datasmith.py sobhaheartland [--rule najma_v4.cga] [--lod 3]
            [--name sobhaheartland_lod3] [--subset 1457,434,505,0] [--obj] [--no-datasmith] [--stats-dir DIR]
  --subset  feature indices only (quick check; Datasmith skipped unless --name is given explicitly)
  --obj     also export an OBJ of the generated subset to --stats-dir (visual / geometry check)
"""
import atexit, datetime, json, os, re, socket, sys, time, threading
import xml.etree.ElementTree as ET

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, ".."))
CEDIR = os.path.join(ROOT, "data", "ce"); RULES = os.path.join(ROOT, "rules"); OUT = os.path.join(CEDIR, "_datasmith")
LOCK = os.path.join(CEDIR, ".ce_lock")

args = sys.argv[1:]
def opt(name, default=None, cast=str):
    if name in args:
        i = args.index(name); v = args[i + 1]; del args[i:i + 2]; return cast(v)
    return default
def flag(name):
    if name in args: args.remove(name); return True
    return False

RULE = opt("--rule", "najma_v4.cga"); LOD = opt("--lod", 3, int)
flag_no_snap = flag("--no-snap")
TOWER_LOD = opt("--tower-lod", 2, int); TOWER_H = opt("--tower-lod-h", 60.0, float)   # towers take a cheaper LOD (Business Bay: 2.4 h at LOD 3)
NAME_ARG = opt("--name", None); SUBSET = opt("--subset", None)
WANT_OBJ = flag("--obj"); NO_DS = flag("--no-datasmith"); STATS_DIR = opt("--stats-dir", None)
OFFSET_ARG = opt("--offset", None)            # "X,Y,Z" CE-frame global offset; REQUIRED when no <slug>_georef.json exists (never auto)
FOCUS = opt("--focus", None); FOCUS_NAME = opt("--focus-name", "focus")   # extra snapshot framing these feature indices
ATTR_FILE = opt("--attr-file", "")          # data/ce/<slug>/facade_match.json: per-building rule attrs (scripts/facade_match.py)
RULE_ATTRS = opt("--rule-attr", "")          # "balconyMinH=24,winW=2.2": USER overrides of najma_v4.cga knobs for this district only
SLUGS = [a for a in args if not a.startswith("--")] or ["sobhaheartland"]
if len(SLUGS) != 1:
    sys.exit("one district at a time")
SLUG = SLUGS[0]; NAME = NAME_ARG or f"{SLUG}_lod3"
SUBSET = [int(x) for x in SUBSET.split(",")] if SUBSET else None
DO_DS = not NO_DS and (SUBSET is None or NAME_ARG is not None)
STATS_DIR = STATS_DIR or OUT
RULE_WS = f"/najma/rules/{RULE}"; SCENE = f"/najma/scenes/{SLUG}.cej"
ME = f"ce_lod3_datasmith.py {SLUG} host={socket.gethostname()} pid={os.getpid()}"
log_lines = []
def log(*a):
    s = time.strftime("%H:%M:%S") + " " + " ".join(str(x) for x in a); print(s, flush=True); log_lines.append(s)

# ce_batch_v2 helpers (mapping / OID rank / export-log parse) — import with a clean argv, it parses sys.argv on import
_argv = sys.argv; sys.argv = [sys.argv[0]]
sys.path.insert(0, HERE); import ce_batch_v2 as B  # noqa: E402
sys.argv = _argv


# ---------------------------------------------------------------- lock
def acquire_lock(max_wait=20 * 60, poll=20):
    t0 = time.time()
    while os.path.exists(LOCK):
        holder = open(LOCK, encoding="utf-8", errors="replace").read().strip()
        if time.time() - t0 > max_wait: sys.exit(f"CE lock held by '{holder}' for > {max_wait // 60} min — giving up")
        log(f"CE lock held by '{holder}' — waiting {poll}s"); time.sleep(poll)
    open(LOCK, "w", encoding="utf-8").write(f"{ME} {datetime.datetime.now().isoformat(timespec='seconds')}\n")
    atexit.register(release_lock); log("CE lock acquired:", ME)

def release_lock():
    try:
        if os.path.exists(LOCK) and ME in open(LOCK, encoding="utf-8", errors="replace").read():
            os.remove(LOCK); print("CE lock released")
    except Exception as e:
        print("lock release:", e)

def watchdog(label, seconds=120):
    ev = threading.Event()
    def _w():
        if not ev.wait(seconds): log(f"WARNING: '{label}' has blocked for {seconds}s — check the CityEngine window for a dialog")
    threading.Thread(target=_w, daemon=True).start(); return ev


# ---------------------------------------------------------------- stats helpers
def tier(h):
    return "tower" if h >= 60 else ("mid" if h >= 20 else "low")

def summarise_reports(json_p, feats, mapping_by_name):
    """Per-building faces + per-slot faces from the callback json (lists <= 8 or {n,sum})."""
    if not os.path.exists(json_p): return None
    raw = open(json_p, "rb").read().decode("utf-8", errors="replace")
    try:
        rep = json.loads(raw)
    except Exception:
        # Jython wrote a non-UTF8 shape name: strip the offending "shape" values and retry
        rep = json.loads(re.sub(r'"shape": "[^"\n]*"', '"shape": ""', raw))
    rows = rep.get("rows", []); per_b = []; slots = {}; tiers = {}
    def val(v): return float(v["sum"]) if isinstance(v, dict) else float(sum(v))
    for r in rows:
        R = r.get("reports", {}); faces = val(R.get("Faces", [0])); nm = r.get("shape", "")
        fi = mapping_by_name.get(nm)
        h = float(r.get("height_m") or 0) or (float(feats[fi]["properties"].get("bHeight") or 0) if fi is not None else 0)
        cl = r.get("class", "")
        per_b.append({"shape": nm, "feature": fi, "class": cl, "height_m": h, "tier": tier(h), "faces": int(faces), "storeys": r.get("storeys"), "gfa_m2": r.get("gfa_m2")})
        for k, v in R.items():
            if k.startswith("Faces."): slots[k[6:]] = slots.get(k[6:], 0) + val(v)
        t = tiers.setdefault(tier(h), {"n": 0, "faces": 0, "max": 0, "max_shape": ""})
        t["n"] += 1; t["faces"] += faces
        if faces > t["max"]: t["max"] = faces; t["max_shape"] = nm
    for t in tiers.values(): t["mean"] = round(t["faces"] / max(t["n"], 1)); t["faces"] = int(t["faces"]); t["max"] = int(t["max"])
    per_b.sort(key=lambda r: -r["faces"])
    return {"buildings": len(rows), "faces_total": int(sum(r["faces"] for r in per_b)), "tiers": tiers,
            "slots": {k: int(v) for k, v in sorted(slots.items(), key=lambda kv: -kv[1])}, "top": per_b[:20], "errors": rep.get("errors", [])}

def parse_udatasmith(path):
    """Material / mesh / actor counts and slot names from the Datasmith XML (no geometry inside)."""
    out = {"materials": [], "meshes": 0, "actors": 0}
    try:
        it = ET.iterparse(path, events=("start",)); names = set()
        for _, el in it:
            tg = el.tag.split("}")[-1]
            if tg in ("Material", "MasterMaterial", "UEPbrMaterial", "MaterialInstance"):
                names.add(el.get("name") or el.get("label") or "?")
            elif tg == "StaticMesh": out["meshes"] += 1
            elif tg in ("Actor", "ActorMesh"): out["actors"] += 1
            el.clear()
        out["materials"] = sorted(names)
    except Exception as e:
        out["error"] = str(e)[:200]
    return out

def dir_size(p):
    tot = n = 0
    for root, _, fns in os.walk(p):
        for fn in fns: tot += os.path.getsize(os.path.join(root, fn)); n += 1
    return tot, n


# ---------------------------------------------------------------- street bearings (villa porch / garage face)
def street_bearings(slug, feats):
    """Per feature: bearing (deg, CE frame atan2(x, z)) of the outward normal of the footprint edge nearest a drivable OSM
    road (data/ce/<slug>/highways_osm.json, Overpass 'out geom'); longest edge if no road within 80 m. None if no file."""
    p = os.path.join(CEDIR, slug, "highways_osm.json")
    if not os.path.exists(p): return None
    import math, pyproj
    tr = pyproj.Transformer.from_crs("EPSG:4326", "EPSG:32640", always_xy=True).transform
    skip = {"footway", "path", "steps", "cycleway", "pedestrian", "track", "bridleway", "corridor", "construction", "proposed"}
    segs = []
    for e in json.load(open(p, encoding="utf-8")).get("elements", []):
        if e.get("type") != "way" or not e.get("geometry") or (e.get("tags") or {}).get("highway") in skip: continue
        pts = [tr(g["lon"], g["lat"]) for g in e["geometry"]]; segs += list(zip(pts, pts[1:]))
    cell = 60.0; grid = {}
    for a, b in segs:
        for cx in range(int(min(a[0], b[0]) // cell), int(max(a[0], b[0]) // cell) + 1):
            for cy in range(int(min(a[1], b[1]) // cell), int(max(a[1], b[1]) // cell) + 1):
                grid.setdefault((cx, cy), []).append((a, b))
    def dseg(px, py, a, b):
        dx, dy = b[0] - a[0], b[1] - a[1]; L2 = dx * dx + dy * dy
        t = max(0.0, min(1.0, ((px - a[0]) * dx + (py - a[1]) * dy) / L2)) if L2 else 0.0
        return math.hypot(px - (a[0] + t * dx), py - (a[1] + t * dy))
    def near(px, py, r=2):
        cx, cy = int(px // cell), int(py // cell); best = 1e9
        for i in range(cx - r, cx + r + 1):
            for j in range(cy - r, cy + r + 1):
                for a, b in grid.get((i, j), ()): best = min(best, dseg(px, py, a, b))
        return best
    out = []; stats = {"road": 0, "longest_edge": 0, "none": 0, "segments": len(segs)}
    for f in feats:
        g = f["geometry"]; ring = g["coordinates"][0] if g["type"] == "Polygon" else g["coordinates"][0][0]
        pts = [tr(x, y) for x, y in ring[:-1]]; n = len(pts)
        area = sum(pts[i][0] * pts[(i + 1) % n][1] - pts[(i + 1) % n][0] * pts[i][1] for i in range(n)) / 2  # > 0 = CCW
        edges = []
        for i in range(n):
            a, b = pts[i], pts[(i + 1) % n]; dx, dy = b[0] - a[0], b[1] - a[1]; L = math.hypot(dx, dy)
            if L < 2: continue
            ox, oy = (dy, -dx) if area > 0 else (-dy, dx)                 # outward normal (UTM east, north)
            az = math.degrees(math.atan2(ox, -oy))                         # CE frame: x = east, z = -north
            edges.append((near((a[0] + b[0]) / 2, (a[1] + b[1]) / 2), -L, az))
        if not edges: out.append(None); stats["none"] += 1; continue
        # terraced rows (long thin footprints) front the street along a LONG edge: drop the short ends from the candidates
        Lmax = max(-e[1] for e in edges); Lmin = min(-e[1] for e in edges)
        if Lmax >= 24 and Lmax / max(0.1, Lmin) >= 2.2:
            edges = [e for e in edges if -e[1] >= 0.6 * Lmax] or edges
        edges.sort()
        if edges[0][0] <= 80: out.append(edges[0][2]); stats["road"] += 1
        else: out.append(min(edges, key=lambda e: e[1])[2]); stats["longest_edge"] += 1
    return out, stats


# ---------------------------------------------------------------- main
def main():
    os.makedirs(OUT, exist_ok=True); os.makedirs(STATS_DIR, exist_ok=True)
    gj = os.path.join(CEDIR, SLUG, "buildings.geojson"); fac_p = os.path.join(CEDIR, SLUG, "facade_v2.json")
    if not os.path.exists(gj): sys.exit(f"no {gj}")
    feats = json.load(open(gj, encoding="utf-8"))["features"]; facade = json.load(open(fac_p, encoding="utf-8"))["buildings"]
    if not os.path.exists(os.path.join(RULES, RULE)): sys.exit(f"no rules/{RULE}")
    existing = [p for p in (os.path.join(OUT, f"{NAME}.udatasmith"),) if os.path.exists(p)]
    if existing and DO_DS: log("NOTE: overwriting an earlier LOD 3 export of the same name:", existing[0])
    if DO_DS and NAME == SLUG: sys.exit("refusing: --name must differ from the flat export name")
    prior = os.path.join(OUT, f"{SLUG}_georef.json"); offset = None; osrc = ""
    if OFFSET_ARG:
        offset = [float(x) for x in OFFSET_ARG.split(",")]; osrc = "--offset"
    elif os.path.exists(prior):
        offset = list(json.load(open(prior, encoding="utf-8")).get("offset_ce_xyz") or []) or None; osrc = os.path.basename(prior)
    if DO_DS and not offset:
        sys.exit(f"no {os.path.basename(prior)} and no --offset: pass the city offset explicitly (e.g. --offset -328289,0,2784598); auto is refused")
    log(f"district {SLUG}: {len(feats)} footprints, rule {RULE}, LOD {LOD}, name {NAME}, offset {offset} ({osrc or 'none, no export'})")
    street = street_bearings(SLUG, feats)
    if street: log(f"street bearings from highways_osm.json: {street[1]}")

    acquire_lock()
    import shutil
    from cityengine import CE, UnrealExportModelSettings, ScriptExportModelSettings, OBJExportModelSettings
    ce = CE(); ws = ce.toFSPath("/"); proj = os.path.join(ws, "najma"); log("connected; workspace", ws)
    os.makedirs(os.path.join(proj, "rules"), exist_ok=True); os.makedirs(os.path.join(proj, "scripts"), exist_ok=True)
    shutil.copy2(os.path.join(RULES, RULE), os.path.join(proj, "rules", RULE))
    shutil.copy2(os.path.join(HERE, "ce_report_v2.py"), os.path.join(proj, "scripts", "ce_report_v2.py"))
    try: ce.refreshWorkspace()
    except Exception: pass
    info = ce.getRuleFileInfo(RULE_WS)   # compiles: raises on CGA errors before the scene is touched
    rules = [r.get("name") if isinstance(r, dict) else str(r) for r in (info.get("rules", []) if isinstance(info, dict) else [])]
    log(f"{RULE} compiled: {len(rules)} rules; start rule present: {'Lot' in rules}")

    ev = watchdog(f"openFile {SCENE}"); ce.openFile(SCENE); ev.set()
    try: ce.waitForUIIdle()
    except Exception: time.sleep(2)
    layers = ce.getObjectsFrom(ce.scene, ce.isShapeLayer); cands = []
    for L in layers:
        shp = ce.getObjectsFrom(L, ce.isShape); cands.append((str(ce.getName(L)), shp))
    pick = [c for c in cands if len(c[1]) == len(feats)] or sorted(cands, key=lambda c: -len(c[1]))
    layer_name, shapes = pick[0]; n = len(shapes); log(f"layer '{layer_name}': {n} shapes vs {len(feats)} features")
    shapes = B.rank_by_oid(ce, shapes)
    B.log = log
    mapping, how = B.map_shapes_to_features(ce, shapes, feats)

    by_cls, by_var, by_h, by_lv, by_az, names, shape_by_fi = {}, {}, {}, {}, {}, {}, {}
    sel = []
    for s, fi in zip(shapes, mapping):
        if SUBSET is not None and fi not in SUBSET: continue
        rec = facade.get(str(fi), {"class": "auto", "variant": fi % 3}); c = rec["class"]; v = int(rec.get("variant", fi % 3))
        pr = feats[fi]["properties"]; st = str(pr.get("status") or "existing").lower()
        nm = f"b{fi}_{c}_s{st}"; ce.setName(s, nm); names[nm] = fi; sel.append(s); shape_by_fi[fi] = s
        by_cls.setdefault(c, []).append(s); by_var.setdefault(v, []).append(s)
        if street and street[0][fi] is not None: by_az.setdefault(int(round(street[0][fi])), []).append(s)
        try: h = float(pr.get("bHeight") or 0)
        except (TypeError, ValueError): h = 0.0
        if h > 0: by_h.setdefault(round(h, 1), []).append(s)
        lv = str(pr.get("levels") or "").strip()
        if lv: by_lv.setdefault(lv, []).append(s)
    for c, lst in by_cls.items(): ce.setAttribute(lst, "fclass", c)
    for v, lst in by_var.items(): ce.setAttribute(lst, "fvar", v)
    for h, lst in by_h.items(): ce.setAttribute(lst, "bHeight", h)
    for lv, lst in by_lv.items(): ce.setAttribute(lst, "levels", lv)
    for az, lst in by_az.items(): ce.setAttribute(lst, "streetAz", float(az))
    log(f"named {len(sel)} shapes (mapping {how}); classes " + ", ".join(f"{c}={len(l)}" for c, l in sorted(by_cls.items()))
        + f"; streetAz pushed to {sum(len(l) for l in by_az.values())} shapes ({len(by_az)} bearings)")
    ce.setRuleFile(sel, RULE_WS); ce.setStartRule(sel, "Lot")
    for a in ("bHeight", "status", "levels", "fclass", "fvar", "pctComplete", "streetAz"):
        try: ce.setAttributeSource(sel, "/ce/rule/" + a, "OBJECT")
        except Exception as e: log(f"attr source {a}: {str(e).splitlines()[0][:80]}")
    ce.setAttribute(sel, "/ce/rule/LOD", LOD)
    try: ce.setAttributeSource(sel, "/ce/rule/LOD", "USER")
    except Exception: pass
    # Damac Hills, 13 Sep: the apartment blocks are 29-42 m, under balconyMinH (60), so they came out as punched 1.5 m windows in a
    # blank wall and read as "no facade". Per-district knob overrides let one district get balconies without touching the rest.
    for kv in [x for x in RULE_ATTRS.split(",") if "=" in x]:
        k, v = kv.split("=", 1)
        try:
            ce.setAttribute(sel, "/ce/rule/" + k.strip(), float(v)); ce.setAttributeSource(sel, "/ce/rule/" + k.strip(), "USER")
            log(f"rule override {k.strip()} = {float(v):g}")
        except Exception as e:
            log(f"rule override {kv} failed: {str(e).splitlines()[0][:80]}")
    # 14 Sep: named buildings matched to photos get their own knobs (balcony style, class, true height), applied per shape as USER
    # values so they win over the district defaults and the OBJECT attrs pushed above.
    if ATTR_FILE:
        match = json.load(open(ATTR_FILE, encoding="utf-8")); n_set = 0; miss = []
        for fi_s, rec in match.items():
            shp = shape_by_fi.get(int(fi_s))
            if shp is None: miss.append(fi_s); continue
            for k, v in rec.get("cga", {}).items():
                try:
                    ce.setAttribute([shp], "/ce/rule/" + k, v if isinstance(v, str) else float(v))
                    ce.setAttributeSource([shp], "/ce/rule/" + k, "USER"); n_set += 1
                except Exception as e:
                    log(f"attr {k} on b{fi_s} failed: {str(e).splitlines()[0][:60]}")
        log(f"attr file {os.path.basename(ATTR_FILE)}: {len(match)} buildings, {n_set} values set, {len(miss)} not in scene {miss[:5]}")
    # Business Bay, 11 Sep: 654 buildings at LOD 3 took 2.4 h to generate because every glass tower gets per-bay mullion bars and
    # balconies. Towers read through the window material in Unreal anyway, so at/above --tower-lod-h (60 m) they take --tower-lod (2:
    # bands + recess, no bars or balustrades). Heroes are exported separately at full detail.
    if TOWER_LOD < LOD:
        tall = [s for h, lst in by_h.items() if h >= TOWER_H for s in lst]
        if tall:
            ce.setAttribute(tall, "/ce/rule/LOD", TOWER_LOD); log(f"towers >= {TOWER_H:g} m: {len(tall)} shapes at LOD {TOWER_LOD} (rest LOD {LOD})")

    t0 = time.time(); ev = watchdog("generateModels", 600); ce.generateModels(sel); ev.set(); tg = time.time() - t0
    log(f"generated {len(sel)} shapes in {tg:.1f}s")
    # snapshots for the report: whole selection + the tallest building
    try:
        if flag_no_snap: raise RuntimeError("--no-snap: viewport snapshots skipped (they stalled the Marina batch run for 30 min on 12 Sep)")
        hmap = {nm: float(feats[fi]["properties"].get("bHeight") or 0) for nm, fi in names.items()}
        tallest = max(sel, key=lambda s: hmap.get(str(ce.getName(s)), 0))
        v3 = ce.get3DViews()[0]; ce.setSelection([]); v3.frame(sel)
        try: ce.waitForUIIdle()
        except Exception: time.sleep(2)
        v3.snapshot(os.path.join(STATS_DIR, f"{NAME}_district.png"), 1920, 1080)
        v3.frame([tallest])
        try: ce.waitForUIIdle()
        except Exception: time.sleep(2)
        v3.snapshot(os.path.join(STATS_DIR, f"{NAME}_hero.png"), 1920, 1080)
        log("snapshots written:", f"{NAME}_district.png", f"{NAME}_hero.png", "(hero =", str(ce.getName(tallest)) + ")")
        if FOCUS:
            fsh = [shape_by_fi[i] for i in (int(x) for x in FOCUS.split(",")) if i in shape_by_fi]
            if fsh:
                v3.frame(fsh)
                try: ce.waitForUIIdle()
                except Exception: time.sleep(2)
                v3.snapshot(os.path.join(STATS_DIR, f"{NAME}_{FOCUS_NAME}.png"), 1920, 1080)
                log(f"focus snapshot written: {NAME}_{FOCUS_NAME}.png ({len(fsh)} shapes)")
    except Exception as e:
        log("snapshot skipped:", str(e).splitlines()[0][:120])

    # reports pass (GFA / Storeys / Faces / Faces.<slot>)
    target = os.path.join(proj, "scripts", "ce_report_v2_target.json")
    csv_p = os.path.join(STATS_DIR, f"{NAME}_report.csv"); json_p = os.path.join(STATS_DIR, f"{NAME}_report.json")
    for p in (csv_p, json_p, csv_p + ".err"):
        if os.path.exists(p): os.remove(p)
    json.dump({"csv": csv_p, "json": json_p, "slug": SLUG, "lod": LOD}, open(target, "w"))
    t0 = time.time(); s2 = ScriptExportModelSettings(); s2.setScript("/najma/scripts/ce_report_v2.py"); ce.export(sel, s2); time.sleep(1)
    stats = summarise_reports(json_p, feats, names); log(f"reports pass {time.time() - t0:.1f}s -> {json_p}")
    if stats:
        log(f"faces total {stats['faces_total']:,} over {stats['buildings']} buildings; tiers " + json.dumps(stats["tiers"]))
        log("slots: " + ", ".join(f"{k}={v:,}" for k, v in stats["slots"].items()))
        log("heaviest: " + "; ".join(f"{r['shape']} {r['height_m']:.0f}m {r['faces']:,}f" for r in stats["top"][:6]))
        if stats["errors"]: log("callback errors:", stats["errors"][:3])

    if WANT_OBJ:
        so = OBJExportModelSettings(); so.setOutputPath(STATS_DIR); so.setBaseName(f"{NAME}_subset")
        if offset:
            try: so.setGlobalOffset(offset)
            except Exception: pass
        try: so.setExistingFiles(OBJExportModelSettings.OVERWRITE)
        except Exception: pass
        ce.export(sel, so); time.sleep(1); log("OBJ written to", STATS_DIR)

    result = {"area": SLUG, "name": NAME, "scene": SCENE, "rule": RULE, "lod": LOD, "ok": False, "shape_count": len(sel), "subset": SUBSET,
              "generate_s": round(tg, 1), "generated": datetime.datetime.now().isoformat(timespec="seconds"), "stats": stats}
    if DO_DS:
        if not offset:
            b = B.shape_bounds(ce, sel) if hasattr(B, "shape_bounds") else None
            offset = [0.0, 0.0, 0.0]
        s = UnrealExportModelSettings(); s.setOutputPath(OUT); s.setBaseName(NAME)
        wanted = {"setExportGeometry": s.MODEL_GEOMETRY_FALLBACK, "setMeshMerging": s.PERINITIALSHAPE, "setInstancing": s.DISABLED,
                  "setMetadata": s.ALL, "setUseUnrealBaseMaterials": True, "setTerrainLayers": s.TERRAIN_NONE, "setWriteLog": True,
                  "setGlobalOffset": offset}
        applied = {}
        for m, v in wanted.items():
            try: getattr(s, m)(v); applied[m] = v if isinstance(v, (bool, str, int, float)) else list(v)
            except Exception as e: log(f"setting {m} not applied: {str(e).splitlines()[0][:100]}")
        log("datasmith settings:", applied)
        t0 = time.time(); ev = watchdog("datasmith export", 900); ce.export(sel, s); ev.set(); te = time.time() - t0
        time.sleep(1)
        main_p = os.path.join(OUT, f"{NAME}.udatasmith"); log_p = os.path.join(OUT, f"{NAME}.log"); assets = os.path.join(OUT, f"{NAME}_Assets")
        ok, failed, total = B.export_log_status(log_p)
        fails = []
        if os.path.exists(log_p):
            for line in open(log_p, encoding="utf-8", errors="replace"):
                st = line.strip()
                if st and st[0].isdigit() and " : " in st and " OK " not in st: fails.append(st[:200])
        ds = parse_udatasmith(main_p) if os.path.exists(main_p) else {}
        asz, an = dir_size(assets) if os.path.isdir(assets) else (0, 0)
        result.update(ok=os.path.exists(main_p), exporter="UnrealExportModelSettings", kind="datasmith", main=[f"{NAME}.udatasmith"],
                      udatasmith_bytes=os.path.getsize(main_p) if os.path.exists(main_p) else 0, assets_files=an, assets_bytes=asz,
                      export_s=round(te, 1), export_log={"ok": ok, "failed": failed, "total": total, "failures": fails[:40]},
                      datasmith_xml=ds, offset_ce_xyz=offset,
                      note="CE frame: x=easting, y=up, z=-northing (metres); offset was ADDED to vertices, so UTM = exported - offset; "
                           "same offset as the flat export so both land on the same spot in Unreal",
                      utm_zone="EPSG:32640 (WGS84 / UTM 40N) - Dubai", settings=applied)
        log(f"datasmith: {NAME}.udatasmith {result['udatasmith_bytes'] / 1048576:.2f} MB, assets {an} files {asz / 1048576:.1f} MB, "
            f"export {te:.1f}s, log ok {ok} failed {failed}, xml meshes {ds.get('meshes')} actors {ds.get('actors')} materials {len(ds.get('materials', []))}")
        if fails: log("failures:", fails[:5])
        log("material slots:", ", ".join(ds.get("materials", [])[:60]))
        georef = {k: v for k, v in result.items() if k != "stats"}
        json.dump(georef, open(os.path.join(OUT, f"{NAME}_georef.json"), "w", encoding="utf-8"), indent=2)
    json.dump(result, open(os.path.join(STATS_DIR, f"{NAME}_stats.json"), "w", encoding="utf-8"), indent=1)
    release_lock()
    open(os.path.join(STATS_DIR, f"{NAME}_run.log"), "w", encoding="utf-8").write("\n".join(log_lines))
    log("done" if (result["ok"] or not DO_DS) else "finished with problems")


if __name__ == "__main__":
    main()
