"""fetch_polyhaven_models.py -- DigitAlchemy(R) / Digital Abbot
Pull CC0 models from Poly Haven (public domain, no key, no account) for the Unreal city: broadleaf trees for parks and avenues,
street lamps and seating for pavements. glTF at the chosen texture resolution, textures included, ready for Unreal's Interchange
importer (da_import_models.py).

Lands as data/models/polyhaven/<asset>/<asset>_<res>.gltf (+ textures/) and a manifest per asset.

    python scripts/fetch_polyhaven_models.py [asset ...] | default [--res 1k|2k] [--force]
"""
import json, os, sys, time, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, ".."))
OUT = os.path.join(ROOT, "data", "models", "polyhaven"); os.makedirs(OUT, exist_ok=True)
UA = {"User-Agent": "najma-unreal-kit/1.0 (contact@digitalabbot.io)"}
RES = sys.argv[sys.argv.index("--res") + 1] if "--res" in sys.argv else "1k"
FORCE = "--force" in sys.argv
DEFAULT = ["jacaranda_tree", "island_tree_01", "island_tree_02", "island_tree_03", "fir_tree_01", "street_lamp_01", "street_lamp_02",
           "modular_street_seating", "outdoor_table_chair_set_01", "fire_hydrant", "covered_car"]


def get(url, binary=False):
    for attempt in range(4):
        try:
            r = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=300); return r.read() if binary else json.load(r)
        except Exception as ex:
            if attempt == 3: raise
            time.sleep(5 * (attempt + 1))


def fetch(asset):
    d = os.path.join(OUT, asset); os.makedirs(d, exist_ok=True); man = os.path.join(d, "manifest.json")
    if os.path.exists(man) and not FORCE:
        print(f"  {asset:28s} already on disk", flush=True); return
    files = get(f"https://api.polyhaven.com/files/{asset}")
    g = files.get("gltf", {}).get(RES, {}).get("gltf")
    if not g:
        print(f"  {asset:28s} no glTF at {RES}: {list(files.get('gltf', {}).keys())}", flush=True); return
    t0 = time.time(); total = 0
    main = os.path.join(d, os.path.basename(g["url"])); open(main, "wb").write(get(g["url"], True)); total += g.get("size", 0)
    for rel, inc in (g.get("include") or {}).items():
        p = os.path.join(d, rel.replace("/", os.sep)); os.makedirs(os.path.dirname(p), exist_ok=True)
        open(p, "wb").write(get(inc["url"], True)); total += inc.get("size", 0)
    info = get(f"https://api.polyhaven.com/info/{asset}")
    json.dump({"asset": asset, "resolution": RES, "gltf": os.path.basename(main), "source": "Poly Haven", "licence": "CC0 1.0 public domain",
               "url": f"https://polyhaven.com/a/{asset}", "categories": info.get("categories"), "tags": info.get("tags"), "authors": info.get("authors"),
               "bytes": total, "fetched": time.strftime("%Y-%m-%dT%H:%M:%S")}, open(man, "w"), indent=1)
    print(f"  {asset:28s} {total//1024:7d} KB  {len(g.get('include') or {}) + 1} files  {round(time.time()-t0,1)}s", flush=True)


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--") and a != RES] or ["default"]
    assets = DEFAULT if args == ["default"] else args
    print(f"Poly Haven {RES} models -> {OUT}")
    for a in assets:
        try: fetch(a)
        except Exception as ex: print(f"  {a}: {str(ex)[:120]}", flush=True)
    print("done:", len([a for a in assets if os.path.exists(os.path.join(OUT, a, 'manifest.json'))]), "of", len(assets))
