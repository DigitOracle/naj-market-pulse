"""fetch_textures.py -- DigitAlchemy(R) / Digital Abbot
Pull CC0 PBR texture sets from ambientCG for the Unreal city's surfaces. Public domain, no licence key, no account: the files can be
redistributed inside a client deliverable without attribution (attribution is still polite and is written into the manifest).

Each set lands as data/textures/<role>/{color,normal,roughness,ao}.jpg plus a manifest, ready for da_build_pbr_materials.py to import.

    python scripts/fetch_textures.py [role ...] | all [--res 2K] [--force]
"""
import io, json, os, sys, time, urllib.request, zipfile

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, ".."))
OUT = os.path.join(ROOT, "data", "textures"); os.makedirs(OUT, exist_ok=True)
UA = {"User-Agent": "najma-unreal-kit/1.0 (contact@digitalabbot.io)"}
RES = sys.argv[sys.argv.index("--res") + 1] if "--res" in sys.argv else "2K"
FORCE = "--force" in sys.argv

# role -> ambientCG asset. Roles are the names the facade and ground materials ask for.
SETS = {
    "render_wall":   "PaintedPlaster017",     # white/cream painted plaster: the Dubai low-rise and villa default
    "stone_wall":    "Travertine009",         # beige limestone / travertine cladding
    "concrete_wall": "Concrete046",           # fair-faced concrete and precast
    "brick_wall":    "Bricks104",
    "podium":        "Marble012",             # polished stone podium and lobby
    "asphalt":       "Asphalt033",
    "paving":        "PavingStones151",       # pavements and plazas
    "sand":          "Ground054",             # desert ground
    "metal":         "Metal049A",             # mullions, louvres, garage shutters
    "roof":          "Concrete034",           # flat roof screed
    "grass":         "Grass004",               # mown lawn: parks, verges, golf fairways. Without a grass set the ground layers
    "pitch":         "Grass001",               # keep a flat colour, which paints lime green over the photoreal tiles (12 Sep)
}
MAPS = {"color": ("_Color.jpg", "_Color.png"), "normal": ("_NormalGL.jpg", "_NormalGL.png", "_Normal.jpg"),
        "roughness": ("_Roughness.jpg", "_Roughness.png"), "ao": ("_AmbientOcclusion.jpg", "_AmbientOcclusion.png"),
        "displacement": ("_Displacement.jpg", "_Displacement.png")}


def fetch(role, asset):
    d = os.path.join(OUT, role); os.makedirs(d, exist_ok=True)
    man = os.path.join(d, "manifest.json")
    if os.path.exists(man) and not FORCE:
        print(f"  {role:14s} already have {json.load(open(man))['asset']}", flush=True); return
    url = f"https://ambientcg.com/get?file={asset}_{RES}-JPG.zip"
    t0 = time.time()
    raw = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=600).read()
    z = zipfile.ZipFile(io.BytesIO(raw)); names = z.namelist(); wrote = {}
    for kind, suffixes in MAPS.items():
        hit = next((n for s in suffixes for n in names if n.endswith(s)), None)
        if not hit: continue
        ext = os.path.splitext(hit)[1]
        p = os.path.join(d, kind + ext)
        open(p, "wb").write(z.read(hit)); wrote[kind] = os.path.basename(p)
    json.dump({"role": role, "asset": asset, "resolution": RES, "source": "ambientCG", "licence": "CC0 1.0 public domain",
               "url": f"https://ambientcg.com/view?id={asset}", "maps": wrote, "bytes": len(raw), "fetched": time.strftime("%Y-%m-%dT%H:%M:%S")},
              open(man, "w"), indent=1)
    print(f"  {role:14s} {asset:20s} {len(raw)//1024:6d} KB  {', '.join(sorted(wrote))}  {round(time.time()-t0,1)}s", flush=True)


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--") and a != RES] or ["all"]
    roles = list(SETS) if args == ["all"] else args
    print(f"ambientCG {RES} sets -> {OUT}")
    for r in roles:
        if r not in SETS: print(f"  {r}: no such role"); continue
        for attempt in range(4):
            try: fetch(r, SETS[r]); break
            except Exception as ex:
                print(f"  {r}: attempt {attempt+1} {str(ex)[:110]}", flush=True); time.sleep(10 * (attempt + 1))
    have = [r for r in SETS if os.path.exists(os.path.join(OUT, r, "manifest.json"))]
    print(f"done: {len(have)} of {len(SETS)} roles on disk")
