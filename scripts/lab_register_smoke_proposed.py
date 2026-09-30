"""LAB (register thread, research only): run the PROPOSED production module data/lab/register/proposed/register_thread.py
the way the patched pyprt_district.export_glb would, on one district, writing only under data/lab/register/.

  prepare() -> + reg_attrs -> GLTFEncoder -> glb_merge_per_building -> reports_pass (LOD 0) -> inject -> check

  python scripts/lab_register_smoke_proposed.py arjan
"""
import glob
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
OUT = os.path.join(ROOT, "data", "lab", "register")
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(OUT, "proposed"))


def main():
    slug = sys.argv[1] if len(sys.argv) > 1 else "arjan"
    import pyprt
    import register_thread as RT
    from pyprt_district import prepare
    from glb_merge_per_building import merge
    rpk = os.path.join(OUT, "najma_v4_register_snap.rpk")
    shapes, attrs, idx, skipped, (oe, on) = prepare(slug, 3, name_style="class")
    reg = RT.rows(slug, path=os.path.join(OUT, "register_%s.csv" % slug))
    for a, fi in zip(attrs, idx):
        if fi in reg:
            a.update(RT.reg_attrs(reg[fi]))
    gdir = os.path.join(OUT, "glb_raw")
    os.makedirs(gdir, exist_ok=True)
    base = "%s_smoke_raw" % slug
    for f in glob.glob(os.path.join(gdir, base + "*")):
        os.remove(f)
    t = time.time()
    pyprt.ModelGenerator(shapes).generate_model(attrs, rpk, "com.esri.prt.codecs.GLTFEncoder",
                                                {"outputPath": gdir, "baseName": base, "meshGranularity": "AS_GENERATED", "outputFormat": "GLB"})
    parts = sorted(glob.glob(os.path.join(gdir, base + "_*.glb")), key=lambda p: (len(p), p))
    out = os.path.join(OUT, "%s_smoke.glb" % slug)
    if len(parts) == 1:
        m = merge(parts[0], out)
    else:
        from glb_merge_parts import concat
        tmp = []
        for p in parts:
            mp = p.replace(".glb", ".m.glb"); merge(p, mp); tmp.append(mp)
        m = concat(tmp, out)
        for mp in tmp:
            os.remove(mp)
    for p in parts:
        os.remove(p)
    t_glb = time.time() - t
    t = time.time()
    per = RT.reports_pass(shapes, attrs, idx, rpk)
    t_rep = time.time() - t
    inj = RT.inject(out, per, {"slug": slug, "rule": os.path.basename(rpk), "origin_ce_xyz": [oe, 0.0, -on]})
    # check against the CSV, reading the file back
    from glb_merge_per_building import read_glb
    js, _ = read_glb(out)
    ok = bad = 0
    ex = []
    for nd in js["nodes"]:
        mt = RT.BID.match(nd.get("name", ""))
        if not mt:
            continue
        r = reg[int(mt.group(1))]
        e = (nd.get("extras") or {}).get("najma_register", {})
        good = (e.get("id") == r["id"] and str(e.get("name", "")) == r["name"] and str(e.get("project", "")) == r["project"]
                and str(e.get("developer", "")) == r["developer"] and str(e.get("units", "")) == r["units"])
        ok += good; bad += not good
        if not good and len(ex) < 5:
            ex.append({"node": nd["name"], "extras": e, "csv": {k: r[k] for k in ("id", "name", "project", "developer", "units")}})
    res = {"slug": slug, "shapes": len(shapes), "skipped": skipped, "glb_generate_merge_s": round(t_glb, 1),
           "reports_pass_s": round(t_rep, 2), "overhead_pct": round(100 * t_rep / t_glb, 1), "inject": inj,
           "glb_bytes": os.path.getsize(out), "merge": {k: m.get(k) for k in ("buildings", "triangles")},
           "nodes_match_csv": ok, "nodes_mismatch": bad, "mismatch_examples": ex,
           "sample": [nd for nd in js["nodes"] if (nd.get("extras") or {}).get("najma_register", {}).get("units")][:2]}
    for s in res["sample"]:
        s.pop("mesh", None)
    json.dump(res, open(os.path.join(OUT, "%s_smoke_proposed.json" % slug), "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    print(json.dumps(res, indent=1, ensure_ascii=False))
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
