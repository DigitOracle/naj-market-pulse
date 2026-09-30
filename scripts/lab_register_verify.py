"""LAB (register thread, research only): open what lab_register_build.py wrote, AS FILES, and check that each
building carries its own register row - the CSV is the expectation, the GLB and the .udatasmith are the evidence.

GLB: parsed here from the raw bytes (struct + json, no project helper), so the check does not share code with the
writer. Also loaded with trimesh as a second, independent reader. Datasmith: the XML <MetaData> blocks.

  python scripts/lab_register_verify.py alyufrah1 [--tag attrs] [--show 5]
"""
import csv
import json
import os
import re
import struct
import sys
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
OUT = os.path.join(ROOT, "data", "lab", "register")
BID = re.compile(r"^b(\d+)(?:_|$)")
FIELDS = [("id", "id"), ("duid", "duid"), ("name", "name"), ("developer", "developer"), ("project", "project"),
          ("status", "status"), ("floors", "floors"), ("units", "units")]


def opt(n, d=None):
    return sys.argv[sys.argv.index(n) + 1] if n in sys.argv else d


def glb_json(path):
    b = open(path, "rb").read()
    magic, ver, _ = struct.unpack_from("<III", b, 0)
    assert magic == 0x46546C67 and ver == 2
    clen, ctype = struct.unpack_from("<II", b, 12)
    assert ctype == 0x4E4F534A
    return json.loads(b[20:20 + clen].decode("utf-8"))


def same(expect, got):
    if expect in ("", None):
        return got in ("", None)
    if got in ("", None):
        return False
    try:
        return abs(float(expect) - float(got)) < 1e-6
    except (TypeError, ValueError):
        return str(expect) == str(got)


def compare(rows, per):
    """per: {i: {field: value}} -> field-by-field agreement with the CSV."""
    res = {"buildings_expected": len(rows), "buildings_found": len(per), "missing": [], "field_ok": {}, "field_bad": {}, "bad_examples": []}
    for i, r in rows.items():
        got = per.get(i)
        if got is None:
            res["missing"].append("b%d" % i); continue
        for f, col in FIELDS:
            ok = same(r[col], got.get(f))
            res["field_ok" if ok else "field_bad"][f] = res["field_ok" if ok else "field_bad"].get(f, 0) + 1
            if not ok and len(res["bad_examples"]) < 8:
                res["bad_examples"].append({"b": i, "field": f, "csv": r[col], "model": got.get(f)})
    res["missing"] = res["missing"][:20]
    res["all_fields_match"] = not res["field_bad"] and not res["missing"]
    return res


def main():
    args = [a for i, a in enumerate(sys.argv[1:], 1) if not a.startswith("--") and sys.argv[i - 1] not in ("--tag", "--show")]
    if not args:
        print(__doc__); return 2
    slug, tag, show = args[0], opt("--tag", "attrs"), int(opt("--show", 4))
    with open(os.path.join(OUT, "register_%s.csv" % slug), encoding="utf-8", newline="") as fh:
        rows = {int(r["i"]): r for r in csv.DictReader(fh)}
    if tag.endswith("_utf8"):
        rows = None      # the probe changed one name on purpose; report what the files hold, do not grade them
    out = {"slug": slug, "tag": tag}

    # ---- GLB, raw
    gp = os.path.join(OUT, "%s_%s.glb" % (slug, tag))
    js = glb_json(gp)
    per_glb, sample = {}, []
    for nd in js["nodes"]:
        mt = BID.match(nd.get("name", ""))
        reg = (nd.get("extras") or {}).get("najma_register")
        if mt and reg:
            per_glb[int(mt.group(1))] = reg
            if len(sample) < show and (reg.get("name") or reg.get("project")):
                sample.append({"node": nd["name"], "extras.najma_register": reg})
    out["glb"] = {"file": os.path.relpath(gp, ROOT), "nodes": len(js["nodes"]), "nodes_with_register": len(per_glb),
                  "scene_extras": js["scenes"][js.get("scene", 0)].get("extras"), "sample": sample}
    if rows is not None:
        out["glb"]["vs_csv"] = compare(rows, per_glb)

    # ---- GLB, trimesh (second reader)
    try:
        import trimesh
        sc = trimesh.load(gp, force="scene")
        seen = 0
        for node in sc.graph.nodes_geometry:
            _, gname = sc.graph[node]
            md = sc.geometry[gname].metadata if gname in sc.geometry else {}
            nd_extras = sc.graph.transforms.node_data.get(node, {}).get("extras") if hasattr(sc.graph.transforms, "node_data") else None
            if (nd_extras or {}).get("najma_register") or "najma_register" in json.dumps(md, default=str):
                seen += 1
        out["glb"]["trimesh_nodes_with_register"] = seen
        out["glb"]["trimesh_geometries"] = len(sc.geometry)
    except Exception as e:
        out["glb"]["trimesh_error"] = str(e)[:200]

    # ---- Datasmith
    dp = os.path.join(OUT, "datasmith", "%s_%s.udatasmith" % (slug, tag))
    if os.path.exists(dp):
        root = ET.parse(dp).getroot()
        per_ds, ds_sample, keys = {}, [], set()
        for md in root.iter("MetaData"):
            mt = BID.match(md.get("name", ""))
            if not mt:
                continue
            kv = {p.get("name"): p.get("val") for p in md.iter("KeyValueProperty")}
            keys.update(kv)
            reg = {k[4:]: v for k, v in kv.items() if k.startswith("reg.") and k != "reg.table_rows"}
            per_ds[int(mt.group(1))] = reg
            if len(ds_sample) < show and (reg.get("name") or reg.get("project")):
                ds_sample.append({"MetaData": md.get("name"), "reg.*": reg,
                                  "reg_* attrs": {k: v for k, v in kv.items() if k.startswith("reg_")}})
        actors = sum(1 for a in root.iter("Actor"))
        out["datasmith"] = {"file": os.path.relpath(dp, ROOT), "actors": actors, "metadata_blocks": len(per_ds),
                            "keys_per_block_max": len(keys), "reg_keys": sorted(k for k in keys if k.startswith("reg")),
                            "sample": ds_sample}
        if rows is not None:
            out["datasmith"]["vs_csv"] = compare(rows, per_ds)
    json.dump(out, open(os.path.join(OUT, "%s_%s_verify.json" % (slug, tag)), "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    print(json.dumps(out, indent=1, ensure_ascii=False)[:6000])
    return 0


if __name__ == "__main__":
    sys.exit(main())
