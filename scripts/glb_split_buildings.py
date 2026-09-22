"""Split per-building meshes out of a merged district GLB into one GLB per building.

This is the LOD 3 delivery lane. LOD 3 does not fit a district tile at any useful threshold: Business Bay is
1.80 MB gzipped for all 654 buildings at LOD 1, 6.49 MB at >=200 m with only 17 towers, and 10.10 MB at
>=150 m with 44 - against a 5 MB KV cap. The budget buys roughly eleven buildings, which is a hero feature,
not a district feature.

The distribution is what makes the split obvious. In the >=200 m build the MEDIAN building is 18 triangles and
18 buildings carry 892,998 of 1,091,954 - 82% of the district sits in under 3% of its buildings. So ship the
district flat and cheap as it is today, and fetch a tower's real geometry only when someone taps it.

The merged GLB already has exactly one node and one mesh per building, named b<id>_<class>, so this is the
inverse of glb_merge_parts.concat: take one node, carry its accessors, bufferViews and the materials it
actually references, and write a standalone GLB.

  python scripts/glb_split_buildings.py data/ce/_glb/sky_businessbay_v4_0.glb --min-tris 5000
  python scripts/glb_split_buildings.py <glb> --names b603_glassclear,b573_glassclear
  python scripts/glb_split_buildings.py <glb> --min-tris 5000 --out data/ce/_glb/bld/businessbay

Writes <out>/<b-id>.glb plus manifest.json listing every building with its triangle count, raw bytes and
gzipped bytes, so the size question is measured rather than estimated.
"""
import gzip
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from glb_merge_per_building import read_glb, write_glb, BID  # noqa: E402

ROOT = os.path.abspath(os.path.join(HERE, ".."))


def _retex(obj, tex_map, parent_key=""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == "index" and parent_key.endswith("Texture") and isinstance(v, int):
                obj[k] = tex_map.get(v, v)
            else:
                _retex(v, tex_map, k)
    elif isinstance(obj, list):
        for x in obj:
            _retex(x, tex_map, parent_key)


def mesh_tris(js, mesh):
    t = 0
    for p in mesh["primitives"]:
        t += js["accessors"][p["attributes"]["POSITION"]]["count"] // 3
    return t


def extract(js, bn, node, dst):
    """Write one building's node+mesh as a standalone GLB, carrying only what it references."""
    mesh = js["meshes"][node["mesh"]]
    out_bin = bytearray()
    bvs, accs, prims = [], [], []
    mat_map, materials = {}, []
    img_map, images = {}, []
    tex_map, textures = {}, []

    def take_accessor(i):
        a = js["accessors"][i]
        bv = js["bufferViews"][a["bufferView"]]
        s = bv.get("byteOffset", 0) + a.get("byteOffset", 0)
        esz = {5120: 1, 5121: 1, 5122: 2, 5123: 2, 5125: 4, 5126: 4}[a["componentType"]]
        esz *= {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}[a["type"]]
        data = bn[s:s + esz * a["count"]]
        while len(out_bin) % 4:
            out_bin.extend(b"\0")
        rec = {"buffer": 0, "byteOffset": len(out_bin), "byteLength": len(data)}
        if "target" in bv:
            rec["target"] = bv["target"]
        bvs.append(rec)
        out_bin.extend(data)
        new = {k: v for k, v in a.items() if k not in ("bufferView", "byteOffset")}
        new["bufferView"] = len(bvs) - 1
        accs.append(new)
        return len(accs) - 1

    for p in mesh["primitives"]:
        q = {"attributes": {k: take_accessor(v) for k, v in p["attributes"].items()},
             "mode": p.get("mode", 4)}
        if "material" in p:
            mi = p["material"]
            if mi not in mat_map:
                m = dict(js["materials"][mi])
                # LOD 3 ships zero texture images - the facade is geometry, not a map - so every material here
                # is colour only. Refuse rather than emit a GLB whose material points at a texture we did not
                # carry: a silently invalid payload is the exact failure mode this whole day was about.
                assert not js.get("textures"), "source has textures; per-building split does not carry them yet"
                _retex(m, tex_map)
                mat_map[mi] = len(materials)
                materials.append(m)
            q["material"] = mat_map[mi]
        prims.append(q)

    out = {"asset": {"version": "2.0", "generator": "najma glb_split_buildings"},
           "scene": 0, "scenes": [{"nodes": [0]}],
           "nodes": [{"name": node.get("name", ""), "mesh": 0}],
           "meshes": [{"name": mesh.get("name", ""), "primitives": prims}],
           "materials": materials, "accessors": accs, "bufferViews": bvs,
           "buffers": [{"byteLength": len(out_bin)}]}
    if textures:
        out["textures"] = textures
    if images:
        out["images"] = images
    return write_glb(dst, out, out_bin)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        print(__doc__)
        return 2
    src = args[0]
    min_tris = int(sys.argv[sys.argv.index("--min-tris") + 1]) if "--min-tris" in sys.argv else 0
    names = sys.argv[sys.argv.index("--names") + 1].split(",") if "--names" in sys.argv else None
    slug = os.path.basename(src).split("_")[1] if "_" in os.path.basename(src) else "district"
    out_dir = sys.argv[sys.argv.index("--out") + 1] if "--out" in sys.argv else \
        os.path.join(ROOT, "data", "ce", "_glb", "bld", slug)
    os.makedirs(out_dir, exist_ok=True)

    js, bn = read_glb(src)
    rows = []
    for nd in js["nodes"]:
        if "mesh" not in nd:
            continue
        nm = nd.get("name", "")
        t = mesh_tris(js, js["meshes"][nd["mesh"]])
        if names is not None and nm not in names:
            continue
        if names is None and t < min_tris:
            continue
        m = BID.match(nm)
        bid = m.group(1) if m else nm
        dst = os.path.join(out_dir, bid + ".glb")
        size = extract(js, bn, nd, dst)
        gz = len(gzip.compress(open(dst, "rb").read(), 9))
        rows.append({"bid": bid, "name": nm, "triangles": t, "bytes": size, "gz": gz})

    rows.sort(key=lambda r: -r["triangles"])
    man = {"source": os.path.basename(src), "slug": slug, "buildings": len(rows),
           "triangles": sum(r["triangles"] for r in rows),
           "bytes": sum(r["bytes"] for r in rows), "gz": sum(r["gz"] for r in rows),
           "items": rows}
    json.dump(man, open(os.path.join(out_dir, "manifest.json"), "w", encoding="utf-8"), indent=1)
    print("%-22s %10s %12s %12s" % ("building", "triangles", "bytes", "gzipped"))
    for r in rows:
        print("%-22s %10d %12d %12d" % (r["name"], r["triangles"], r["bytes"], r["gz"]))
    print()
    print("%d buildings, %d triangles, %.2f MB raw, %.2f MB gzipped total; largest single %.2f MB gz" % (
        len(rows), man["triangles"], man["bytes"] / 1048576.0, man["gz"] / 1048576.0,
        max((r["gz"] for r in rows), default=0) / 1048576.0))
    print("-> %s" % out_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
