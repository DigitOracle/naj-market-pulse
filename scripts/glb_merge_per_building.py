"""Merge a CityEngine AS_GENERATED glTF export into ONE mesh per building — geometry AND textures.

CityEngine's glTF encoder writes one root node + one mesh per generated LEAF (a 60-storey tower with floor
bands = hundreds of meshes), and the per-mesh JSON overhead (~340 bytes each) dwarfs the geometry: Business
Bay at LOD 1 was 16 MB of which 13 MB was JSON. PER_MATERIAL granularity fixes the size but merges the whole
district into 9 meshes, losing per-building identity. This pass keeps both: it groups CE's leaf meshes by the
building prefix of the mesh name ("b<i>_<class>[_s<status>]", CE suffixes clashes with "_N"), concatenates
their triangle soup per material, and writes one root node -> one mesh (one primitive per material) per
building, named exactly like the shape.

v3 (textured rule): vertex attributes POSITION, NORMAL and TEXCOORD_0 are all carried (CE writes float32,
non-indexed triangles; NORMAL is copied when CE wrote it, otherwise left out so the viewer flat-shades),
materials are kept with their baseColorTexture etc., textures and images are carried and de-duplicated by
image bytes, and materials that end up byte-identical are folded together (so one primitive per REAL material
per building, not per CityEngineMaterial_N). Leaves of one material that lack TEXCOORD_0 while others have it
get zero UVs; a material with mixed NORMAL presence drops NORMAL (flat shading is what the viewer wants anyway).

Usage:  python scripts/glb_merge_per_building.py in.glb [out.glb]      (in place when out is omitted)
"""
import hashlib, json, re, struct, sys

GLB_MAGIC = 0x46546C67
BID = re.compile(r"^(b\d+)((?:_[A-Za-z]+)*)")
COMP_SIZE = {5120: 1, 5121: 1, 5122: 2, 5123: 2, 5125: 4, 5126: 4}
TYPE_N = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}
ATTRS = ("POSITION", "NORMAL", "TEXCOORD_0")


def read_glb(path):
    b = open(path, "rb").read()
    magic, ver, length = struct.unpack_from("<III", b, 0)
    assert magic == GLB_MAGIC and ver == 2, "not a glTF 2 binary"
    off = 12; js = None; bn = b""
    while off < length:
        clen, ctype = struct.unpack_from("<II", b, off); off += 8
        chunk = b[off:off + clen]; off += clen
        if ctype == 0x4E4F534A:
            js = json.loads(chunk.decode("utf-8"))
        elif ctype == 0x004E4942:
            bn = chunk
    return js, bn


def write_glb(path, js, bn):
    jb = json.dumps(js, separators=(",", ":")).encode("utf-8")
    jb += b" " * ((4 - len(jb) % 4) % 4)
    bn = bytes(bn) + b"\0" * ((4 - len(bn) % 4) % 4)
    total = 12 + 8 + len(jb) + 8 + len(bn)
    out = struct.pack("<III", GLB_MAGIC, 2, total) + struct.pack("<II", len(jb), 0x4E4F534A) + jb + struct.pack("<II", len(bn), 0x004E4942) + bn
    open(path, "wb").write(out)
    return len(out)


def accessor_raw(js, bn, acc_i):
    """Raw tightly-packed element bytes of an accessor + (count, fmt). fmt = (componentType, type, normalized, elemSize)."""
    a = js["accessors"][acc_i]; bv = js["bufferViews"][a["bufferView"]]
    esz = COMP_SIZE[a["componentType"]] * TYPE_N[a["type"]]
    stride = bv.get("byteStride", esz); start = bv.get("byteOffset", 0) + a.get("byteOffset", 0)
    if stride == esz:
        data = bn[start:start + esz * a["count"]]
    else:
        data = b"".join(bn[start + i * stride:start + i * stride + esz] for i in range(a["count"]))
    return data, a["count"], (a["componentType"], a["type"], bool(a.get("normalized", False)), esz)


def bufferview_bytes(js, bn, bv_i):
    bv = js["bufferViews"][bv_i]; s = bv.get("byteOffset", 0)
    return bn[s:s + bv["byteLength"]]


def _remap_textures(obj, tex_map, parent_key=""):
    """Recursively remap {"index": n} texture references (any key ending in 'Texture') in a material dict."""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if k == "index" and parent_key.endswith("Texture") and isinstance(v, int):
                out[k] = tex_map[v]
            else:
                out[k] = _remap_textures(v, tex_map, k)
        return out
    if isinstance(obj, list):
        return [_remap_textures(x, tex_map, parent_key) for x in obj]
    return obj


def merge(src, dst=None):
    dst = dst or src
    js, bn = read_glb(src)
    nodes = js.get("nodes", []); meshes = js["meshes"]
    roots = js["scenes"][js.get("scene", 0)]["nodes"] if js.get("scenes") else list(range(len(nodes)))

    # ---------------------------------------------------------------- images / textures / materials (dedupe)
    out_bin = bytearray(); bvs = []
    images_new = []; img_map = {}; img_by_hash = {}
    for i, img in enumerate(js.get("images", [])):
        if "bufferView" in img:
            data = bufferview_bytes(js, bn, img["bufferView"]); key = ("bv", hashlib.sha1(data).hexdigest())
        else:
            data = None; key = ("uri", img.get("uri"))
        if key not in img_by_hash:
            if data is not None:
                while len(out_bin) % 4: out_bin += b"\0"
                bvs.append({"buffer": 0, "byteOffset": len(out_bin), "byteLength": len(data)}); out_bin += data
                rec = {"mimeType": img.get("mimeType", "image/jpeg"), "bufferView": len(bvs) - 1}
            else:
                rec = {k: v for k, v in img.items()}
            if img.get("name"): rec["name"] = img["name"]
            img_by_hash[key] = len(images_new); images_new.append(rec)
        img_map[i] = img_by_hash[key]
    textures_new = []; tex_map = {}; tex_by_key = {}
    for i, t in enumerate(js.get("textures", [])):
        rec = {k: v for k, v in t.items() if k != "name"}
        if "source" in rec: rec["source"] = img_map[rec["source"]]
        key = json.dumps(rec, sort_keys=True)
        if key not in tex_by_key:
            tex_by_key[key] = len(textures_new); textures_new.append(rec)
        tex_map[i] = tex_by_key[key]
    materials_new = []; mat_map = {}; mat_by_key = {}
    for i, m in enumerate(js.get("materials", [])):
        rec = _remap_textures({k: v for k, v in m.items() if k != "name"}, tex_map)
        key = json.dumps(rec, sort_keys=True)
        if key not in mat_by_key:
            if m.get("name"): rec = dict(rec, name=m["name"])
            mat_by_key[key] = len(materials_new); materials_new.append(rec)
        mat_map[i] = mat_by_key[key]

    # ---------------------------------------------------------------- group leaves by building
    groups = {}   # building key -> {"name", "mats": {new material index: [chunk, ...]}, "tris"}
    order = []

    def walk(i, key):
        nd = nodes[i]
        assert not any(k in nd for k in ("matrix", "translation", "rotation", "scale")), "node transforms not supported (CE writes none)"
        if "mesh" in nd:
            m = meshes[nd["mesh"]]; nm = m.get("name", "")
            mt = BID.match(nm)
            k = key or (mt.group(1) if mt else nm)
            if k not in groups:
                groups[k] = {"name": (mt.group(1) + mt.group(2)) if mt else nm, "mats": {}, "tris": 0}
                order.append(k)
            g = groups[k]
            for p in m["primitives"]:
                assert p.get("mode", 4) == 4 and "indices" not in p, "expected non-indexed triangle primitives"
                chunk = {"attrs": {}}
                for an in ATTRS:
                    if an in p["attributes"]:
                        data, cnt, fmt = accessor_raw(js, bn, p["attributes"][an]); chunk["attrs"][an] = (data, fmt); chunk["count"] = cnt
                mat = mat_map[p["material"]] if "material" in p else -1
                g["mats"].setdefault(mat, []).append(chunk); g["tris"] += chunk["count"] // 3
            key = k
        for c in nd.get("children", []):
            walk(c, key)

    for r in roots:
        walk(r, None)

    # ---------------------------------------------------------------- write one mesh per building
    accs = []; new_meshes = []; new_nodes = []
    for k in order:
        g = groups[k]; prims = []
        for mat, chunks in g["mats"].items():
            n = sum(c["count"] for c in chunks)
            has = {an: sum(1 for c in chunks if an in c["attrs"]) for an in ATTRS}
            use = [an for an in ATTRS if has[an] == len(chunks) or (an == "TEXCOORD_0" and has[an] > 0)]
            attributes = {}
            for an in use:
                fmt = next(c["attrs"][an][1] for c in chunks if an in c["attrs"])
                parts = []
                for c in chunks:
                    if an in c["attrs"]: parts.append(c["attrs"][an][0])
                    else: parts.append(b"\0" * (fmt[3] * c["count"]))          # zero UVs for untextured leaves of this material
                data = b"".join(parts)
                while len(out_bin) % 4: out_bin += b"\0"
                bvs.append({"buffer": 0, "byteOffset": len(out_bin), "byteLength": len(data), "target": 34962}); out_bin += data
                acc = {"bufferView": len(bvs) - 1, "componentType": fmt[0], "count": n, "type": fmt[1]}
                if fmt[2]: acc["normalized"] = True
                if an == "POSITION":
                    xs = struct.unpack_from("<%df" % (3 * n), data)
                    acc["min"] = [min(xs[0::3]), min(xs[1::3]), min(xs[2::3])]; acc["max"] = [max(xs[0::3]), max(xs[1::3]), max(xs[2::3])]
                accs.append(acc); attributes[an] = len(accs) - 1
            prim = {"attributes": attributes, "mode": 4}
            if mat >= 0:
                prim["material"] = mat
            prims.append(prim)
        new_meshes.append({"name": g["name"], "primitives": prims})
        new_nodes.append({"name": g["name"], "mesh": len(new_meshes) - 1})
    asset = dict(js.get("asset", {}))
    asset["generator"] = (asset.get("generator", "") + " + najma glb_merge_per_building").strip()
    out = {"asset": asset, "scene": 0, "scenes": [{"nodes": list(range(len(new_nodes)))}], "nodes": new_nodes, "meshes": new_meshes,
           "materials": materials_new, "accessors": accs, "bufferViews": bvs, "buffers": [{"byteLength": len(out_bin)}]}
    if textures_new: out["textures"] = textures_new
    if images_new: out["images"] = images_new
    if js.get("samplers"): out["samplers"] = js["samplers"]
    for k in ("extensionsUsed", "extensionsRequired"):
        if k in js:
            out[k] = js[k]
    size = write_glb(dst, out, out_bin)
    return {"buildings": len(new_meshes), "leaf_meshes_in": len(meshes), "primitives": len(accs and [p for m in new_meshes for p in m["primitives"]]),
            "triangles": sum(g["tris"] for g in groups.values()), "bytes": size, "materials": len(materials_new), "materials_in": len(js.get("materials", [])),
            "textures": len(textures_new), "images": len(images_new), "images_in": len(js.get("images", [])),
            "image_bytes": sum(js["bufferViews"][im["bufferView"]]["byteLength"] for im in images_new if "bufferView" in im) if False else
                           sum(bvs[im["bufferView"]]["byteLength"] for im in images_new if "bufferView" in im),
            "uv": any("TEXCOORD_0" in p["attributes"] for m in new_meshes for p in m["primitives"])}


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    print(json.dumps(merge(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)))
