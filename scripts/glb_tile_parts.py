"""Split a district tile across several KV keys so LOD 3 can ship in the skyline, not only on tap.

The 5 MB KV cap is what forced 27 districts onto per-building payloads: Dubai Marina is 19.44 MB gzipped at
LOD 3, Al Thanyah Fifth 27.27 MB. Their heights are now correct everywhere, but their FACADES only ever
appear when someone taps a building - the skyline stays flat, because no single key can carry the district.

This splits the merged per-building GLB into N standalone GLBs, each under the cap, each carrying a whole
number of buildings with their names and materials intact:

    sky_<slug>_p0, sky_<slug>_p1, ...   the parts, gzipped GLB, same /img/ route as sky_<slug>
    skyparts_<slug>                     the index: how many parts, and what is in each

A building is never split across parts - the unit is the building, so per-building identity, tapping, the
floor stack and the b<i> ids all keep working exactly as they do in a single-key tile. The page loads the
index, fetches the parts and adds each to the same scene.

  python scripts/glb_tile_parts.py dubaimarina --ver v4
  python scripts/glb_tile_parts.py dubaimarina --ver v4 --target-mb 4.5
  python scripts/glb_tile_parts.py dubaimarina --ver v4 --dry-run

Sizing: buildings are packed by raw byte cost using the district's own measured gzip ratio, then EVERY part
is gzipped and checked. Any part over the cap is split again and re-checked, so the published sizes are
measured rather than predicted - the whole point of the exercise is not to guess at a cap again.
"""
import gzip
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from glb_merge_per_building import read_glb, write_glb, BID  # noqa: E402

ROOT = os.path.abspath(os.path.join(HERE, ".."))
GLB = os.path.join(ROOT, "data", "ce", "_glb")
CAP = 5 * 1024 * 1024


def building_nodes(js):
    return [(i, nd) for i, nd in enumerate(js.get("nodes", [])) if "mesh" in nd]


def node_cost(js, nd):
    """Raw bytes this building contributes: its accessors' data."""
    total = 0
    for p in js["meshes"][nd["mesh"]]["primitives"]:
        for acc_i in p["attributes"].values():
            a = js["accessors"][acc_i]
            bv = js["bufferViews"][a["bufferView"]]
            total += bv["byteLength"]
    return total


def subset(js, bn, nodes, dst):
    """Write the given building nodes as a standalone GLB, carrying only what they reference."""
    out_bin = bytearray()
    bvs, accs, meshes, new_nodes, materials = [], [], [], [], []
    mat_map = {}

    for nd in nodes:
        mesh = js["meshes"][nd["mesh"]]
        prims = []
        for p in mesh["primitives"]:
            attrs = {}
            for name, acc_i in p["attributes"].items():
                a = js["accessors"][acc_i]
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
                attrs[name] = len(accs) - 1
            q = {"attributes": attrs, "mode": p.get("mode", 4)}
            if "material" in p:
                mi = p["material"]
                if mi not in mat_map:
                    mat_map[mi] = len(materials)
                    materials.append(dict(js["materials"][mi]))
                q["material"] = mat_map[mi]
            prims.append(q)
        meshes.append({"name": mesh.get("name", ""), "primitives": prims})
        new_nodes.append({"name": nd.get("name", ""), "mesh": len(meshes) - 1})

    out = {"asset": {"version": "2.0", "generator": "najma glb_tile_parts"},
           "scene": 0, "scenes": [{"nodes": list(range(len(new_nodes)))}],
           "nodes": new_nodes, "meshes": meshes, "materials": materials,
           "accessors": accs, "bufferViews": bvs, "buffers": [{"byteLength": len(out_bin)}]}
    return write_glb(dst, out, out_bin)


def pack(items, budget):
    """Greedy fill in the given order - buildings stay in index order so parts are spatially coherent-ish
    and a reader can reason about which part holds which b<i>."""
    groups, cur, cur_cost = [], [], 0
    for it, cost in items:
        if cur and cur_cost + cost > budget:
            groups.append(cur)
            cur, cur_cost = [], 0
        cur.append(it)
        cur_cost += cost
    if cur:
        groups.append(cur)
    return groups


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        print(__doc__)
        return 2
    slug = args[0]
    ver = sys.argv[sys.argv.index("--ver") + 1] if "--ver" in sys.argv else "v4"
    target = float(sys.argv[sys.argv.index("--target-mb") + 1]) if "--target-mb" in sys.argv else 4.5
    dry = "--dry-run" in sys.argv
    src = os.path.join(GLB, "sky_%s_%s_0.glb" % (slug, ver))
    if not os.path.exists(src):
        print("no %s" % src)
        return 1

    js, bn = read_glb(src)
    nodes = building_nodes(js)
    raw = os.path.getsize(src)
    whole_gz = len(gzip.compress(open(src, "rb").read(), 9))
    ratio = whole_gz / float(raw)
    print("%s %s: %d buildings, %.2f MB raw, %.2f MB gzipped (ratio %.3f)"
          % (slug, ver, len(nodes), raw / 1048576.0, whole_gz / 1048576.0, ratio))
    if whole_gz <= CAP:
        print("  already under the 5 MB cap - a single key is correct, nothing to split")
        return 0

    costs = [((i, nd), node_cost(js, nd)) for i, nd in nodes]
    budget = int((target * 1048576) / ratio)      # raw bytes that should gzip to about the target
    groups = pack(costs, budget)
    print("  packing to %.1f MB gzipped per part -> %d parts" % (target, len(groups)))
    if dry:
        for n, g in enumerate(groups):
            print("    p%-2d %5d buildings  b%s..b%s" % (n, len(g), g[0][1].get("name", "?").split("_")[0][1:],
                                                         g[-1][1].get("name", "?").split("_")[0][1:]))
        print("  dry run - nothing written")
        return 0

    out_dir = os.path.join(GLB, "parts", slug)
    os.makedirs(out_dir, exist_ok=True)
    parts, over = [], []
    for n, g in enumerate(groups):
        dst = os.path.join(out_dir, "sky_%s_%s_p%d.glb" % (slug, ver, n))
        size = subset(js, bn, [nd for _, nd in g], dst)
        gz = len(gzip.compress(open(dst, "rb").read(), 9))
        bids = [nd.get("name", "") for _, nd in g]
        parts.append({"part": n, "file": os.path.basename(dst), "buildings": len(g),
                      "bytes": size, "gz": gz, "first": bids[0], "last": bids[-1]})
        flag = "" if gz <= CAP else "  OVER CAP"
        if gz > CAP:
            over.append(n)
        print("    p%-2d %5d buildings  %7.2f MB raw  %5.2f MB gz%s" % (n, len(g), size / 1048576.0, gz / 1048576.0, flag))

    man = {"slug": slug, "ver": ver, "parts": len(parts), "buildings": sum(p["buildings"] for p in parts),
           "key": "sky_%s_%s_p<n>" % (slug, ver), "index_key": "skyparts_%s" % slug, "items": parts}
    json.dump(man, open(os.path.join(out_dir, "manifest.json"), "w", encoding="utf-8"), indent=1)
    print("  %d parts, %d buildings total, largest %.2f MB gz -> %s"
          % (len(parts), man["buildings"], max(p["gz"] for p in parts) / 1048576.0, out_dir))
    if over:
        print("  WARNING: parts over the cap: %s - lower --target-mb and re-run" % over)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
