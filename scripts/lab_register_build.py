"""LAB (register thread, research only): build a district with the register riding ON the model, headless (PyPRT).

One rule (data/lab/register/najma_v4_register.rpk = najma_v4.cga + the register block), three passes over the same
shapes and attributes as scripts/pyprt_district.py prepare() (imported, not copied):

  1. reports   com.esri.pyprt.PyEncoder, emitReports  -> the rule's own reg.* reports per building
  2. GLB       com.esri.prt.codecs.GLTFEncoder AS_GENERATED -> glb_merge_per_building.merge -> one node per b<i>;
               then each node gets  extras.najma_register = {the reg.* reports of THAT shape}
               (PRT's glTF encoder has no metadata option at all - measured, see encoder_options/*.xml - so the
               extras are written from the rule's reports of the same shapes, joined on the shape index)
  3. Datasmith com.esri.prt.unreal.encoder, meshMerging perInitialShape, instancing disabled, metadata all
               -> <MetaData> per actor, written by the encoder itself (no post-processing)

How the register gets INTO the rule (--mode):
  attrs   (default) reg_* pushed per building from data/lab/register/register_<slug>.csv
  table   only regTable = <abs path of that CSV>; the rule looks its row up by b<i> (readStringTable)
  none    control: rule unchanged in behaviour, nothing pushed -> no reg.* beyond the id

Writes data/lab/register/<slug>_<mode>.glb, <slug>_<mode>_reports.json, datasmith/<slug>_<mode>.udatasmith (+ _Assets).
Never writes into data/ce/.

  python scripts/lab_register_build.py alyufrah1                 attrs mode, all three passes
  python scripts/lab_register_build.py alyufrah1 --mode table --no-datasmith
  python scripts/lab_register_build.py alyufrah1 --utf8-probe    b0's name replaced by its OSM (Arabic) name
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
OUT = os.path.join(ROOT, "data", "lab", "register")
RPK = os.path.join(OUT, "najma_v4_register.rpk")
sys.path.insert(0, HERE)
BID = re.compile(r"^b(\d+)(?:_|$)")
SCHEMA = "najma-register/1"


def opt(n, d=None):
    return sys.argv[sys.argv.index(n) + 1] if n in sys.argv else d


def register_rows(slug):
    p = os.path.join(OUT, "register_%s.csv" % slug)
    with open(p, encoding="utf-8", newline="") as fh:
        return {int(r["i"]): r for r in csv.DictReader(fh)}, p


def reg_attrs(r):
    """CSV row -> the rule's reg_* attrs. Unknowns are left at the rule default ("" / -1), never invented."""
    a = {"reg_id": r["id"]}
    for k, col in (("reg_duid", "duid"), ("reg_name", "name"), ("reg_dev", "developer"), ("reg_project", "project"),
                   ("reg_status", "status"), ("reg_floors_src", "floors_src")):
        if r.get(col):
            a[k] = r[col]
    for k, col in (("reg_floors", "floors"), ("reg_units", "units")):
        if r.get(col) not in (None, ""):
            a[k] = float(r[col])
    if r.get("floor_uses"):
        a["reg_floor_uses"] = r["floor_uses"].split("|")
    return a


def reports_of(rep):
    """PyPRT's PyEncoder hands back every report five ways (<key>_n / _sum / _avg / _min / _max, measured); the value
    the rule reported is <key>_sum (a string report's _sum is the string itself, a tick report's is the count)."""
    return {k[:-4]: v for k, v in rep.items() if k.endswith("_sum")}


def payload(rep):
    """The reg.* reports of one shape -> the extras object (prefix dropped, use ticks grouped)."""
    out, uses = {}, {}
    for k, v in rep.items():
        if not k.startswith("reg.") or k == "reg.table_rows":
            continue
        k = k[4:]
        if k.startswith("use."):
            uses[k[4:]] = int(v) if isinstance(v, float) and v == int(v) else v
        else:
            out[k] = int(v) if isinstance(v, float) and v == int(v) else v
    if uses:
        out["uses"] = uses
    return out


def main():
    args = [a for i, a in enumerate(sys.argv[1:], 1) if not a.startswith("--") and sys.argv[i - 1] not in ("--mode", "--lod", "--rpk", "--table-path", "--reports-lod")]
    if not args:
        print(__doc__); return 2
    slug = args[0]
    mode = opt("--mode", "attrs")
    lod = int(opt("--lod", 3))
    import pyprt
    from pyprt_district import prepare
    from glb_merge_per_building import merge, read_glb, write_glb

    shapes, attrs, idx, skipped, (oe, on) = prepare(slug, lod, name_style="class")
    rows, csv_p = register_rows(slug)
    tag = mode + ("_utf8" if "--utf8-probe" in sys.argv else "")
    if "--utf8-probe" in sys.argv:
        feats = json.load(open(os.path.join(ROOT, "data", "ce", slug, "buildings.geojson"), encoding="utf-8"))["features"]
        fi = next(i for i in idx if any(ord(c) > 127 for c in str(feats[i]["properties"].get("name") or "")))
        rows[fi] = dict(rows[fi], name=feats[fi]["properties"]["name"])
        print("  utf8 probe: b%d name -> %r" % (fi, rows[fi]["name"]))
    for a, fi in zip(attrs, idx):
        if mode == "attrs":
            a.update(reg_attrs(rows[fi]))
        elif mode == "table":
            # a path INSIDE the .rpk (lab_register_rpk.py --tables packs it): PyPRT's readStringTable cannot reach a
            # file outside the package - absolute path, file:/// URI and backslash path all gave nRows = 0 (30 Sep)
            a["regTable"] = opt("--table-path", "tables/register_%s.csv" % slug)
    rpk = os.path.abspath(opt("--rpk", RPK))
    t_all = time.time()

    # 1 --- reports: the rule's own view of each building's register
    # At LOD 0: reg.* is reported in Lot before the LOD dispatch, so the payload is the same at any LOD (measured on
    # alhebiahfifth: 94/94 identical, 0.63 s at LOD 0 against 10.83 s at LOD 3) - data/lab/register/reports_lod0_vs_lod3_*.json
    t = time.time()
    rep_lod = float(opt("--reports-lod", 0))
    models = pyprt.ModelGenerator(shapes).generate_model([dict(a, LOD=rep_lod) for a in attrs], rpk, "com.esri.pyprt.PyEncoder",
                                                         {"emitReports": True, "emitGeometry": False})
    reps = {}
    for m in models:
        fi = idx[m.get_initial_shape_index()]
        reps[fi] = reports_of(m.get_report())
    t_rep = round(time.time() - t, 2)
    json.dump({"slug": slug, "mode": mode, "rpk": os.path.relpath(rpk, ROOT), "shapes": len(shapes), "skipped": skipped,
               "reports": {("b%d" % fi): {k: v for k, v in r.items() if k.startswith("reg.") or k in ("Height_m", "Storeys_est", "LOD")}
                           for fi, r in sorted(reps.items())}},
              open(os.path.join(OUT, "%s_%s_reports.json" % (slug, tag)), "w", encoding="utf-8"), indent=1, ensure_ascii=False)

    # 2 --- GLB: geometry from the glTF encoder, register from the same shapes' reports
    t = time.time()
    gdir = os.path.join(OUT, "glb_raw")
    os.makedirs(gdir, exist_ok=True)
    base = "%s_%s_raw" % (slug, tag)
    for f in glob.glob(os.path.join(gdir, base + "*")):
        os.remove(f)
    pyprt.ModelGenerator(shapes).generate_model(attrs, rpk, "com.esri.prt.codecs.GLTFEncoder",
                                                {"outputPath": gdir, "baseName": base, "meshGranularity": "AS_GENERATED",
                                                 "outputFormat": "GLB"})
    parts = sorted(glob.glob(os.path.join(gdir, base + "_*.glb")), key=lambda p: (len(p), p))
    if not parts:
        sys.exit("glTF encoder wrote nothing")
    out_glb = os.path.join(OUT, "%s_%s.glb" % (slug, tag))
    if len(parts) == 1:
        merge(parts[0], out_glb)
    else:
        from glb_merge_parts import concat
        tmp = []
        for p in parts:
            mp = p.replace(".glb", ".m.glb"); merge(p, mp); tmp.append(mp)
        concat(tmp, out_glb)
        for mp in tmp:
            os.remove(mp)
    for p in parts:
        os.remove(p)
    js, bn = read_glb(out_glb)
    tagged, untagged = 0, []
    for nd in js["nodes"]:
        mt = BID.match(nd.get("name", ""))
        if not mt:
            continue
        pl = payload(reps.get(int(mt.group(1)), {}))
        if pl:
            nd.setdefault("extras", {})["najma_register"] = pl
            tagged += 1
        else:
            untagged.append(nd.get("name"))
    js.setdefault("scenes", [{}])[js.get("scene", 0)].setdefault("extras", {})["najma_register"] = {
        "schema": SCHEMA, "slug": slug, "mode": mode, "rule": os.path.basename(rpk), "register_csv": os.path.relpath(csv_p, ROOT).replace("\\", "/"),
        "origin_ce_xyz": [oe, 0.0, -on], "crs": "EPSG:32640", "built": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "research_only": True}
    js["asset"]["generator"] = js["asset"].get("generator", "") + " + lab_register_build"
    size = write_glb(out_glb, js, bn)
    t_glb = round(time.time() - t, 2)

    # 3 --- Datasmith, headless, metadata written by the encoder
    ds = None
    if "--no-datasmith" not in sys.argv:
        t = time.time()
        ddir = os.path.join(OUT, "datasmith")
        os.makedirs(ddir, exist_ok=True)
        pyprt.ModelGenerator(shapes).generate_model(attrs, rpk, "com.esri.prt.unreal.encoder",
                                                    {"outputPath": ddir, "baseName": "%s_%s" % (slug, tag),
                                                     "meshMerging": "perInitialShape", "instancing": "disabled",
                                                     "metadata": "all"})
        p = os.path.join(ddir, "%s_%s.udatasmith" % (slug, tag))
        ds = {"path": os.path.relpath(p, ROOT), "exists": os.path.exists(p), "s": round(time.time() - t, 2),
              "metadata_blocks": open(p, encoding="utf-8", errors="replace").read().count("<MetaData ") if os.path.exists(p) else 0}

    res = {"slug": slug, "mode": mode, "shapes": len(shapes), "reports_s": t_rep, "glb_s": t_glb,
           "glb": os.path.relpath(out_glb, ROOT), "glb_bytes": size, "nodes": len(js["nodes"]), "nodes_with_register": tagged,
           "nodes_without": untagged[:10], "datasmith": ds, "total_s": round(time.time() - t_all, 1)}
    json.dump(res, open(os.path.join(OUT, "%s_%s_build.json" % (slug, tag)), "w", encoding="utf-8"), indent=1)
    print(json.dumps(res, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
