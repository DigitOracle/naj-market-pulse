"""LAB (floor-use technique #2): floor-by-floor use bands + GFA per use + ESTIMATED units, headless with PyPRT.

Research use only. Unit figures are ESTIMATES (floor plate x net area factor / area per unit), labelled so everywhere.

Rule: najma/rules/lab/flooruse/flooruse.cga compiled to data/lab/flooruse/flooruse.rpk (scripts/lab_flooruse_rpk.py).
Nothing here writes outside data/lab/flooruse/ and no existing file is changed; the geometry helpers of
scripts/pyprt_district.py (footprints, heights, local origin) and scripts/glb_merge_per_building.py are imported, not edited.

What each building is given (the order is the provenance, carried into the CSV as `stack_source`):
  1. dm_floors        the Dubai Municipality floor register in data/board/stack_<slug>.json: one use per floor, bottom to top,
                      handed to the rule as runs "retail:1;services:2;homes:28;services:1"
  2. dm_permit        same file, a stack drawn from the DM permit line only (G retail, podium services, homes)
  3. register_levels  same file, but only the register's FLOOR COUNT is real (its uses are all "homes" by construction), so
                      the rule gets regFloors = that count and builds the documented default stack on it
  4. default          no register: the rule's default stack from the massing height, with the class taken from the
                      building's name where a keyword says hotel / office / residential (a priori list below), else auto
Upper-floor plate (attr typPlate, GROSS m2; homes / office / hotel floors are drawn as a centred scaled footprint of that area):
  dm_floor_area   dm_floors buildings: median DM floor area of the numbered homes / office / hotel floors / 0.85. The DM "a" is a
                  NET area - it is 0.91 x the sum of the DLD unit areas on the same floor (834 floors, Business Bay) - hence / 0.85.
  prior_oos       buildings the facts file flags plate_suspect (footprint is probably a podium or a plot) with no DM plate:
                  PLATE_PRIOR_NET / 0.85, the median DM typical floor of 266 towers (>= 20 numbered floors) in the 44 OTHER districts
  footprint       everything else (typPlate 0)
The DLD units register (unitmix type rows / asset classes, dld_buildings flats/offices/shops) is NEVER an input: it is the
truth the estimates are scored against by scripts/lab_flooruse_eval.py. (The DM floor register's per-floor unit count k is
not an input either - only its use and area.)

  python scripts/lab_flooruse_build.py businessbay                 reports CSV + GLB
  python scripts/lab_flooruse_build.py businessbay --no-register   ablation: default stacks everywhere, reports only
  python scripts/lab_flooruse_build.py businessbay --no-plate      ablation: every floor at the footprint, reports only
  python scripts/lab_flooruse_build.py businessbay --no-names      ablation: no name keywords (height-only class), reports only
  python scripts/lab_flooruse_build.py businessbay --no-glb
"""
import csv
import glob
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
BOARD = os.path.join(ROOT, "data", "board")
OUT = os.path.join(ROOT, "data", "lab", "flooruse")
RPK = os.path.join(OUT, "flooruse.rpk")
sys.path.insert(0, HERE)

PLATE_PRIOR_NET = 914.0       # m2, see the docstring; computed out of sample, never from Business Bay
NAF_HOMES = 0.85              # must match flooruse_space_types.csv
USES = ["homes", "hotel", "office", "retail", "parking", "services", "civic", "staff", "labour", "villa"]
UNIT_USES = ["homes", "hotel", "office", "retail", "parking"]          # the uses the table gives an AreaPerUnit

# A priori name keywords (written before looking at any Business Bay register row; not tuned on it).
KW = [
    ("hotel", re.compile(r"\b(hotel|hotels|inn|suites|marriott|hilton|sheraton|hyatt|radisson|novotel|ibis|mercure|westin|"
                         r"renaissance|meridien|pullman|sofitel|rove|fairmont|kempinski|steigenberger|movenpick|mövenpick|"
                         r"crowne|citymax|dusit|intercontinental|ritz|four seasons|premier inn)\b", re.I)),
    ("office", re.compile(r"\b(office|offices|business|commercial|corporate|executive|exchange|trade|hq|headquarters|"
                          r"bank)\b", re.I)),
    ("residential", re.compile(r"\b(residence|residences|residential|heights|apartments|apartment|living|homes|views|"
                               r"gardens|villas|lofts|loft)\b", re.I)),
]


def opt(n, d=None):
    return sys.argv[sys.argv.index(n) + 1] if n in sys.argv else d


def runs_of(floors):
    """Stack floors (bottom to top) -> 'use:count;use:count' runs."""
    out = []
    for f in floors:
        u = f.get("u") or "services"
        if u not in USES:
            u = "services"
        if out and out[-1][0] == u:
            out[-1][1] += 1
        else:
            out.append([u, 1])
    return ";".join("%s:%d" % (u, n) for u, n in out)


def class_from_name(name):
    name = re.sub(r"business\s+bay", " ", name or "", flags=re.I)      # the district's own name is not a use
    for cls, rx in KW:
        if name and rx.search(name):
            return cls
    return "auto"


def load(slug):
    j = lambda n: json.load(open(os.path.join(BOARD, "%s_%s.json" % (n, slug)), encoding="utf-8"))
    stack = j("stack").get("buildings_by_id", {}) if os.path.exists(os.path.join(BOARD, "stack_%s.json" % slug)) else {}
    um = j("unitmix").get("buildings_by_id", {}) if os.path.exists(os.path.join(BOARD, "unitmix_%s.json" % slug)) else {}
    return stack, um


def shape_inputs(slug, no_register=False):
    """PyPRT shapes + per-shape attributes for the floor-use rule, plus the provenance row per building."""
    import pyprt_district as pd
    shapes, base, idx, skipped, origin = pd.prepare(slug, 0)
    feats = json.load(open(os.path.join(ROOT, "data", "ce", slug, "buildings.geojson"), encoding="utf-8"))["features"]
    stack, um = load(slug)
    fp = os.path.join(BOARD, "bldgfacts_%s.json" % slug)
    facts = json.load(open(fp, encoding="utf-8")).get("buildings_by_id", {}) if os.path.exists(fp) else {}
    attrs, meta = [], {}
    for a, fi in zip(base, idx):
        pr = feats[fi]["properties"]
        name = pr.get("name") or (um.get(str(fi)) or {}).get("name") or ""
        s = stack.get(str(fi)) or {}
        at = {"shapeName": "b%d" % fi, "seed": fi, "status": a["status"]}
        if "bHeight" in a:
            at["bHeight"] = a["bHeight"]
        if "levels" in a:
            at["levels"] = a["levels"]
        basis = s.get("basis")
        cls = "auto" if "--no-names" in sys.argv else class_from_name(name)
        if not no_register and basis in ("dm_floors", "dm_permit") and s.get("floors"):
            at["floorStack"] = runs_of(s["floors"])
            at["stackSource"] = basis
            src = basis
        else:
            if not no_register and basis == "register_levels" and s.get("floors"):
                at["regFloors"] = float(len(s["floors"]))
                src = "register_levels+default"
            else:
                src = "default"
            at["useClass"] = cls
        plate, plate_src = 0.0, "footprint"
        if not no_register and basis == "dm_floors":
            typ = sorted(f["a"] for f in s["floors"] if f.get("n") and f.get("a") and f["u"] in ("homes", "office", "hotel"))
            if typ:
                plate, plate_src = typ[len(typ) // 2] / NAF_HOMES, "dm_floor_area"
        if not plate and (facts.get(str(fi)) or {}).get("plate_suspect") and "--no-plate" not in sys.argv:
            plate, plate_src = PLATE_PRIOR_NET / NAF_HOMES, "prior_oos"
        if "--no-plate" in sys.argv:
            plate, plate_src = 0.0, "footprint"
        if plate:
            at["typPlate"] = round(plate, 1)
        attrs.append(at)
        meta[fi] = {"plate_source": plate_src, "typ_plate_in_m2": round(plate), "name": name, "stack_source": src, "name_class": cls, "floor_stack_in": at.get("floorStack", ""),
                    "reg_floors_in": int(at.get("regFloors", 0)), "stack_fits_massing": s.get("fits"),
                    "height_flag": bool(s.get("height_flag")), "status": a["status"]}
    return shapes, attrs, idx, skipped, origin, meta


UPPER = ("homes", "office", "hotel", "staff", "labour")          # the uses the rule narrows to typPlate (flooruse.cga isUpper)


def plate_in_python(rep, attrs, idx):
    """FALLBACK ONLY, for a package compiled before flooruse.cga had typPlate (the CE lock was held by another agent for over an
    hour on 30 Sep, so the recompile could not run). Applies to the reports exactly what the rule's Floor(u) does: an upper-use
    floor whose footprint exceeds 1.05 x typPlate is scaled to typPlate, so its GFA, NFA and units scale by typPlate / footprint.
    Geometry is NOT narrowed on this path - only a recompiled rule does that."""
    for a, fi in zip(attrs, idx):
        p = a.get("typPlate") or 0
        r = rep.get(fi)
        fp = (r or {}).get("Footprint_m2") or 0
        if not p or not r or fp <= 1.05 * p:
            continue
        k = p / fp
        for u in UPPER:
            if r.get("Floors.%s" % u):
                old = r.get("GFA.%s" % u, 0.0)
                for key in ("GFA.%s" % u, "NFA.%s" % u, "Units_est.%s" % u):
                    if key in r:
                        r[key] *= k
                r["GFA"] = r.get("GFA", 0.0) - old + r["GFA.%s" % u]


def reports(shapes, attrs, idx):
    import pyprt
    models = pyprt.ModelGenerator(shapes).generate_model(attrs, RPK, "com.esri.pyprt.PyEncoder",
                                                         {"emitReport": True, "emitGeometry": False})
    out = {}
    for m in models:
        r = m.get_report()
        out[idx[m.get_initial_shape_index()]] = {k[:-4]: v for k, v in r.items() if k.endswith("_sum")}
    rule_has_plate = "typPlate" in pyprt.get_rpk_attributes_info(RPK)
    if not rule_has_plate and any(a.get("typPlate") for a in attrs):
        plate_in_python(out, attrs, idx)
    return out, ("rule" if rule_has_plate else "python_fallback")


def write_csv(slug, rep, meta, tag):
    path = os.path.join(OUT, "flooruse_%s%s.csv" % (slug, tag))
    cols = (["i", "name", "status", "stack_source", "name_class", "stack_used", "height_m", "footprint_m2", "floors", "gfa_m2"]
            + ["floors_%s" % u for u in USES] + ["gfa_%s_m2" % u for u in USES]
            + ["est_%s" % u for u in UNIT_USES] + ["est_units_total_excl_parking",
               "plate_source", "typ_plate_in_m2", "plate_applied_by", "stack_fits_massing", "height_flag", "floor_stack_in", "reg_floors_in", "label"])
    rows = []
    for fi in sorted(rep):
        r, m = rep[fi], meta[fi]
        stack_used = [k.split(".", 1)[1] for k in r if k.startswith("Stack.")]
        row = {"i": fi, "name": m["name"], "status": m["status"], "stack_source": m["stack_source"],
               "name_class": m["name_class"], "stack_used": stack_used[0] if stack_used else "",
               "height_m": round(r.get("Height_m", 0), 1), "footprint_m2": round(r.get("Footprint_m2", 0)),
               "floors": int(round(r.get("Floors", 0))), "gfa_m2": round(r.get("GFA", 0))}
        for u in USES:
            row["floors_%s" % u] = int(round(r.get("Floors.%s" % u, 0)))
            row["gfa_%s_m2" % u] = round(r.get("GFA.%s" % u, 0))
        tot = 0.0
        for u in UNIT_USES:
            v = r.get("Units_est.%s" % u, 0.0)
            row["est_%s" % u] = round(v, 1)
            if u != "parking":
                tot += v
        row["est_units_total_excl_parking"] = round(tot, 1)
        row.update({"plate_source": m["plate_source"], "typ_plate_in_m2": m["typ_plate_in_m2"],
                    "plate_applied_by": m["plate_applied_by"],
                    "stack_fits_massing": m["stack_fits_massing"], "height_flag": m["height_flag"],
                    "floor_stack_in": m["floor_stack_in"], "reg_floors_in": m["reg_floors_in"],
                    "label": "ESTIMATE - research use only"})
        rows.append(row)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    return path, rows


def export_glb(slug, shapes, attrs, origin):
    import pyprt
    from glb_merge_per_building import merge
    raw = "flooruse_%s_raw" % slug
    for f in glob.glob(os.path.join(OUT, raw + "*")):
        os.remove(f)
    pyprt.ModelGenerator(shapes).generate_model(
        attrs, RPK, "com.esri.prt.codecs.GLTFEncoder",
        {"outputPath": OUT, "baseName": raw, "meshGranularity": "AS_GENERATED", "outputFormat": "GLB"})
    parts = sorted(glob.glob(os.path.join(OUT, raw + "_*.glb")), key=lambda p: (len(p), p))
    if not parts:
        sys.exit("the glTF encoder wrote nothing")
    out = os.path.join(OUT, "flooruse_%s.glb" % slug)
    if len(parts) == 1:
        r = merge(parts[0], out)
    else:
        from glb_merge_parts import concat
        tmp, tris = [], 0
        for p in parts:
            mp = p.replace(".glb", ".m.glb"); tris += merge(p, mp)["triangles"]; tmp.append(mp)
        r = concat(tmp, out); r["triangles"] = tris
        for mp in tmp:
            os.remove(mp)
    for p in parts:
        os.remove(p)
    oe, on = origin
    meta = {"slug": slug, "crs": "EPSG:32640", "origin_ce_xyz": [oe, 0.0, -on], "origin_utm_en": [oe, on],
            "contract": "CE-frame metres (x = easting, y = up, z = -northing) = vertex + origin_ce_xyz (same as pyprt_district)",
            "rule": "najma/rules/lab/flooruse/flooruse.cga", "buildings": r.get("buildings"), "triangles": r.get("triangles"),
            "built": time.strftime("%Y-%m-%dT%H:%M:%S"), "builder": "pyprt", "use": "research only; unit figures are estimates"}
    json.dump(meta, open(os.path.join(OUT, "flooruse_%s_origin.json" % slug), "w", encoding="utf-8"), indent=1)
    return out, meta


def main():
    slug = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("--") else "businessbay"
    no_reg = "--no-register" in sys.argv
    if not os.path.exists(RPK):
        sys.exit("no %s - run scripts/lab_flooruse_rpk.py first" % RPK)
    t = time.time()
    shapes, attrs, idx, skipped, origin, meta = shape_inputs(slug, no_register=no_reg)
    rep, plate_by = reports(shapes, attrs, idx)
    for m in meta.values():
        m["plate_applied_by"] = plate_by if m["plate_source"] != "footprint" else ""
    tag = (("_noregister" if no_reg else "") + ("_noplate" if "--no-plate" in sys.argv else "")
           + ("_nonames" if "--no-names" in sys.argv else ""))
    path, rows = write_csv(slug, rep, meta, tag)
    print("%s: %d shapes (%d skipped), reports in %.1f s -> %s" % (slug, len(shapes), len(skipped), time.time() - t,
                                                                  os.path.relpath(path, ROOT)))
    from collections import Counter
    print("  stack source:", dict(Counter(r["stack_source"] for r in rows)))
    print("  stack used:  ", dict(Counter(r["stack_used"] for r in rows)))
    print("  GFA by use (m2):", {u: sum(r["gfa_%s_m2" % u] for r in rows) for u in USES if sum(r["gfa_%s_m2" % u] for r in rows)})
    print("  ESTIMATED units:", {u: round(sum(r["est_%s" % u] for r in rows)) for u in UNIT_USES})
    print("  plate source:", dict(Counter(r["plate_source"] for r in rows)), "applied by:", plate_by)
    if not tag:
        # the per-building rule inputs, as the integration patch would have ce_batch_v2 / pyprt_district push them
        keep = ("floorStack", "stackSource", "useClass", "regFloors", "typPlate")
        side = {"slug": slug, "rule": "najma/rules/lab/flooruse/flooruse.cga", "use": "research only; unit figures are estimates",
                "attrs_by_id": {str(fi): {k: v for k, v in a.items() if k in keep} for a, fi in zip(attrs, idx)}}
        json.dump(side, open(os.path.join(OUT, "flooruse_attrs_%s.json" % slug), "w", encoding="utf-8"), indent=0)
    if not tag and "--no-glb" not in sys.argv:
        t = time.time()
        out, m = export_glb(slug, shapes, attrs, origin)
        print("  GLB %s  %.1f MB  %s buildings  %s triangles  in %.1f s" % (os.path.relpath(out, ROOT),
              os.path.getsize(out) / 1048576.0, m["buildings"], m["triangles"], time.time() - t))
    return 0


if __name__ == "__main__":
    sys.exit(main())
