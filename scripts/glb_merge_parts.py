"""Merge EVERY part of a split CityEngine export into one per-building GLB.

CityEngine writes sky_<slug>_<ver>_0.glb, _1.glb, _2.glb ... when an export is too large for one buffer, and
glb_merge_per_building only ever opened _0. On 22 Sep 2026 Business Bay at LOD 3 produced 357.1 MB across two
parts; the pipeline merged, packed, pushed and verified the first 202.6 MB of it and reported 54 buildings of
654 as though that were the district. Nothing downstream knew the other file existed.

The split lands on a building boundary - measured on the 150 m run, 326 buildings in _0 and 328 in _1, union
654, intersection 0 - so the parts partition the district cleanly and nothing needs stitching across the cut.

This composes rather than rewrites: glb_merge_per_building.merge already groups leaves by the b<id> prefix of
the MESH name, which is where identity lives in a raw part (raw parts have 733,320 unnamed nodes; the node
names you see in merged output are created BY the merge). So each part is merged on its own proven path, then
the merged results are concatenated with accessor, bufferView, material, texture and image indices remapped and
materials deduped across parts.

  python scripts/glb_merge_parts.py businessbay --ver v4
  python scripts/glb_merge_parts.py --glb data/ce/_glb/sky_businessbay_v4_0.glb   (explicit part 0)

Writes the combined district over part _0 and deletes the higher parts once it has verified the building count,
so the rest of the pipeline - pack, gzip, push - keeps working on _0 exactly as before.
"""
import hashlib, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from glb_merge_per_building import read_glb, write_glb, merge, BID  # noqa: E402

ROOT = os.path.abspath(os.path.join(HERE, ".."))
GLB = os.path.join(ROOT, "data", "ce", "_glb")


def parts_for(glb0):
    """Every part belonging to the same export, in order. glb0 is the _0 path."""
    d, base = os.path.dirname(glb0), os.path.basename(glb0)
    assert base.endswith("_0.glb"), "expected a _0.glb path, got %s" % base
    stem = base[:-len("0.glb")]
    out = []
    for f in sorted(os.listdir(d), key=lambda x: (len(x), x)):
        if f.startswith(stem) and f.endswith(".glb") and f[len(stem):-len(".glb")].isdigit():
            out.append(os.path.join(d, f))
    return out


def concat(srcs, dst):
    """Concatenate already-merged per-building GLBs into one. Each input has one node per building, one mesh per
    node, and one bufferView per accessor, so remapping is index arithmetic - no geometry is touched."""
    out_bin = bytearray()
    bvs, accs, nodes, meshes = [], [], [], []
    images, textures, materials = [], [], []
    img_by_hash, tex_by_key, mat_by_key = {}, {}, {}
    asset = None

    for src in srcs:
        js, bn = read_glb(src)
        if asset is None:
            asset = dict(js.get("asset", {}))

        # images, by content hash so a texture shared across parts is stored once
        img_map = {}
        for i, im in enumerate(js.get("images", [])):
            if "bufferView" in im:
                bv = js["bufferViews"][im["bufferView"]]
                data = bn[bv.get("byteOffset", 0): bv.get("byteOffset", 0) + bv["byteLength"]]
                key = ("bv", hashlib.sha1(data).hexdigest())
            else:
                data, key = None, ("uri", im.get("uri"))
            if key not in img_by_hash:
                if data is not None:
                    while len(out_bin) % 4:
                        out_bin += b"\0"
                    bvs.append({"buffer": 0, "byteOffset": len(out_bin), "byteLength": len(data)})
                    out_bin += data
                    rec = {"mimeType": im.get("mimeType", "image/jpeg"), "bufferView": len(bvs) - 1}
                else:
                    rec = dict(im)
                if im.get("name"):
                    rec["name"] = im["name"]
                img_by_hash[key] = len(images)
                images.append(rec)
            img_map[i] = img_by_hash[key]

        tex_map = {}
        for i, t in enumerate(js.get("textures", [])):
            rec = {k: v for k, v in t.items() if k != "name"}
            if "source" in rec:
                rec["source"] = img_map[rec["source"]]
            key = json.dumps(rec, sort_keys=True)
            if key not in tex_by_key:
                tex_by_key[key] = len(textures)
                textures.append(rec)
            tex_map[i] = tex_by_key[key]

        mat_map = {}
        for i, m in enumerate(js.get("materials", [])):
            rec = json.loads(json.dumps({k: v for k, v in m.items() if k != "name"}))
            _retex(rec, tex_map)
            key = json.dumps(rec, sort_keys=True)
            if key not in mat_by_key:
                if m.get("name"):
                    rec = dict(rec, name=m["name"])
                mat_by_key[key] = len(materials)
                materials.append(rec)
            mat_map[i] = mat_by_key[key]

        # bufferViews verbatim (merged output packs one per accessor), then accessors pointing at the new index
        bv_map = {}
        for i, bv in enumerate(js.get("bufferViews", [])):
            s = bv.get("byteOffset", 0)
            data = bn[s:s + bv["byteLength"]]
            while len(out_bin) % 4:
                out_bin += b"\0"
            rec = {"buffer": 0, "byteOffset": len(out_bin), "byteLength": len(data)}
            if "target" in bv:
                rec["target"] = bv["target"]
            bvs.append(rec)
            out_bin += data
            bv_map[i] = len(bvs) - 1

        acc_map = {}
        for i, a in enumerate(js.get("accessors", [])):
            rec = dict(a)
            rec["bufferView"] = bv_map[a["bufferView"]]
            accs.append(rec)
            acc_map[i] = len(accs) - 1

        mesh_map = {}
        for i, m in enumerate(js.get("meshes", [])):
            prims = []
            for p in m["primitives"]:
                q = {"attributes": {k: acc_map[v] for k, v in p["attributes"].items()}, "mode": p.get("mode", 4)}
                if "material" in p:
                    q["material"] = mat_map[p["material"]]
                prims.append(q)
            meshes.append({"name": m.get("name", ""), "primitives": prims})
            mesh_map[i] = len(meshes) - 1

        for nd in js.get("nodes", []):
            if "mesh" not in nd:
                continue      # merged output carries no transforms and no empties; anything else is not ours
            nodes.append({"name": nd.get("name", ""), "mesh": mesh_map[nd["mesh"]]})

    asset = asset or {}
    asset["generator"] = (asset.get("generator", "") + " + najma glb_merge_parts").strip()
    out = {"asset": asset, "scene": 0, "scenes": [{"nodes": list(range(len(nodes)))}],
           "nodes": nodes, "meshes": meshes, "materials": materials,
           "accessors": accs, "bufferViews": bvs, "buffers": [{"byteLength": len(out_bin)}]}
    if textures:
        out["textures"] = textures
    if images:
        out["images"] = images
    size = write_glb(dst, out, out_bin)
    return {"buildings": len(nodes), "meshes": len(meshes), "materials": len(materials),
            "images": len(images), "bytes": size}


def _retex(obj, tex_map, parent_key=""):
    """Remap {"index": n} texture references in place (any key ending in 'Texture')."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == "index" and parent_key.endswith("Texture") and isinstance(v, int):
                obj[k] = tex_map.get(v, v)
            else:
                _retex(v, tex_map, k)
    elif isinstance(obj, list):
        for x in obj:
            _retex(x, tex_map, parent_key)


def merge_all(glb0, keep_parts=False):
    """Merge every part of the export at glb0 into glb0. Returns stats, or None if there is only one part
    (in which case the caller's ordinary single-file merge already did the job)."""
    srcs = parts_for(glb0)
    if len(srcs) < 2:
        return None
    tmp, per_part = [], []
    for i, p in enumerate(srcs):
        # A part is raw unless it IS _0 and something already merged it in place. Merging an already-merged
        # file is a no-op that regroups the same buildings, so this is safe either way.
        t = p.replace(".glb", ".part.glb")
        r = merge(p, t)
        per_part.append({"part": os.path.basename(p), "buildings": r["buildings"], "triangles": r["triangles"]})
        tmp.append(t)
    stats = concat(tmp, glb0)
    stats["parts"] = per_part
    stats["triangles"] = sum(p["triangles"] for p in per_part)
    for t in tmp:
        try:
            os.remove(t)
        except OSError:
            pass
    if not keep_parts:
        for p in srcs[1:]:
            try:
                os.remove(p)
            except OSError:
                pass
    return stats


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    ver = sys.argv[sys.argv.index("--ver") + 1] if "--ver" in sys.argv else "v4"
    if "--glb" in sys.argv:
        glb0 = sys.argv[sys.argv.index("--glb") + 1]
    elif args:
        glb0 = os.path.join(GLB, "sky_%s_%s_0.glb" % (args[0], ver))
    else:
        print(__doc__)
        return 2
    r = merge_all(glb0, keep_parts="--keep-parts" in sys.argv)
    if r is None:
        print("single part - nothing to do")
        return 0
    print(json.dumps(r, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
