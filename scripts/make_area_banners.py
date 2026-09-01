"""Generate satellite banner strips for Najma area/development cards from Esri World Imagery.

Why pre-generate rather than proxy live tiles: each tile view bills Esri credits. One stitched
strip per area, pushed to Worker KV, is a fixed one-off cost that then serves free forever —
same frugality rule we apply to MEED units. Re-run only when the area list changes.

Auth: fetches a short-lived token from the Worker's /esri_token (never stores Esri secrets here).
Env: AZIMUTH_URL, READ_KEY (or pass --key). Output: public/banners/sat_<slug>.jpg
Push:  python scripts/push_assets.py --banners
"""
import io, json, math, os, re, sys, time, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "public", "banners")
IMAGERY = "https://ibasemaps-api.arcgis.com/arcgis/rest/services/World_Imagery/MapServer/tile"
REFERER = "https://azimuth-2.digitalchemy.workers.dev/"

# The curated community coordinates the map already uses (kept in sync with DXB_COORDS
# in azimuth-worker/src/index.js). lon, lat, zoom — zoom tuned per area footprint.
PLACES = {
    "business bay": (55.264, 25.186, 14), "jumeirah village circle": (55.207, 25.058, 14),
    "downtown dubai": (55.276, 25.194, 15), "dubai marina": (55.138, 25.080, 14),
    "palm jumeirah": (55.138, 25.112, 13), "jumeirah lakes towers": (55.141, 25.069, 14),
    "dubai hills estate": (55.246, 25.104, 13), "arjan": (55.243, 25.055, 14),
    "al furjan": (55.145, 25.026, 14), "dubai south": (55.161, 24.896, 13),
    "madinat al mataar": (55.16, 24.90, 13), "city of arabia": (55.30, 25.13, 14),
    "jumeirah village triangle": (55.19, 25.05, 14), "damac hills": (55.25, 25.03, 13),
    "dubai creek harbour": (55.34, 25.20, 14), "meydan": (55.30, 25.16, 14),
    "town square": (55.28, 25.02, 14), "the valley": (55.45, 25.02, 13),
    "sobha hartland": (55.30, 25.18, 14), "majan": (55.26, 25.07, 14),
    "dubai land residence complex": (55.28, 25.06, 14), "al barsha": (55.20, 25.11, 14),
    "deira": (55.32, 25.27, 14), "palm deira": (55.32, 25.30, 13),
    "dubai islands": (55.33, 25.30, 13), "jabal ali first": (55.13, 25.00, 13),
    "wadi al safa 5": (55.30, 25.07, 14),
}

TILE, TW, TH = 256, 4, 2          # 1024x512 strip — matches the card's 2:1 band


def slug(s):
    return re.sub(r"[^a-z0-9]", "", s.lower())


def deg2tile(lon, lat, z):
    n = 2 ** z
    return ((lon + 180) / 360 * n,
            (1 - math.log(math.tan(math.radians(lat)) + 1 / math.cos(math.radians(lat))) / math.pi) / 2 * n)


def get_token(base, key):
    u = base.rstrip("/") + "/esri_token?key=" + key
    with urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "najma-market-pulse/1.0"}), timeout=60) as r:
        d = json.load(r)
    if not d.get("ok"):
        sys.exit("Esri token unavailable — check ESRI_CLIENT_ID/SECRET on the worker: " + json.dumps(d)[:200])
    return d["token"]


def strip(name, lon, lat, z, token):
    from PIL import Image
    fx, fy = deg2tile(lon, lat, z)
    x0, y0 = int(fx - TW / 2), int(fy - TH / 2)
    im = Image.new("RGB", (TILE * TW, TILE * TH))
    for i in range(TW):
        for j in range(TH):
            u = f"{IMAGERY}/{z}/{y0 + j}/{x0 + i}?token={token}"
            req = urllib.request.Request(u, headers={"Referer": REFERER, "User-Agent": "najma-market-pulse/1.0"})
            for attempt in range(3):
                try:
                    with urllib.request.urlopen(req, timeout=45) as r:
                        im.paste(Image.open(io.BytesIO(r.read())), (TILE * i, TILE * j))
                    break
                except Exception as e:
                    if attempt == 2:
                        print(f"  ! {name} tile {i},{j}: {e}")
                    time.sleep(1.5 * (attempt + 1))
    os.makedirs(OUT, exist_ok=True)
    p = os.path.join(OUT, f"sat_{slug(name)}.jpg")
    im.save(p, "JPEG", quality=82, progressive=True, optimize=True)
    return p


def main():
    base = os.environ.get("AZIMUTH_URL", "https://azimuth-2.digitalchemy.workers.dev")
    key = os.environ.get("READ_KEY") or (sys.argv[sys.argv.index("--key") + 1] if "--key" in sys.argv else "")
    if not key:
        sys.exit("need READ_KEY env or --key <read key>")
    only = sys.argv[sys.argv.index("--only") + 1].lower() if "--only" in sys.argv else None
    token = get_token(base, key)
    total = 0
    for name, (lon, lat, z) in PLACES.items():
        if only and only not in name:
            continue
        p = strip(name, lon, lat, z, token)
        kb = os.path.getsize(p) // 1024
        total += kb
        print(f"  {name:32s} -> {os.path.basename(p)} ({kb} KB)")
    print(f"done — {total // 1024 or total} {'MB' if total > 1024 else 'KB'} total in {OUT}")
    print("next: python scripts/push_assets.py --banners")


if __name__ == "__main__":
    main()
