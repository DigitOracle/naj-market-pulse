"""Satellite banners v2 — framed by the community's REAL boundary, outlined in gold.

Answers "where is it?" on the image itself: each banner is zoomed to fit that community's
Dubai Municipality polygon (from public/mp_areas.json), with the boundary drawn in Najma
gold directly onto the imagery. Communities without a polygon fall back to a centered frame
with a gold ring marker. Higher zoom than v1 wherever the polygon allows.

Env: AZIMUTH_URL, READ_KEY. Output: public/banners/sat_<slug>.jpg (overwrites v1).
Then: python scripts/push_assets.py --banners
"""
import io, json, math, os, re, sys, time, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
PUB = os.path.join(HERE, "..", "public")
OUT = os.path.join(PUB, "banners")
IMAGERY = "https://ibasemaps-api.arcgis.com/arcgis/rest/services/World_Imagery/MapServer/tile"
REFERER = "https://azimuth-2.digitalchemy.workers.dev/"
W, H, TILE = 1024, 512, 256
GOLD = (197, 165, 106)
HALO = (12, 20, 19)

from make_area_banners import PLACES, slug, get_token  # reuse v1 coordinates + auth


def merc(lon, lat, z):
    n = 256 * (2 ** z)
    x = (lon + 180) / 360 * n
    y = (1 - math.log(math.tan(math.radians(lat)) + 1 / math.cos(math.radians(lat))) / math.pi) / 2 * n
    return x, y


def rings_of(geom):
    if geom["type"] == "Polygon":
        return geom["coordinates"]
    return [r for poly in geom["coordinates"] for r in poly]


def fetch_tile(z, ty, tx, token):
    from PIL import Image
    u = f"{IMAGERY}/{z}/{ty}/{tx}?token={token}"
    req = urllib.request.Request(u, headers={"Referer": REFERER, "User-Agent": "najma-market-pulse/1.0"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=45) as r:
                return Image.open(io.BytesIO(r.read())).convert("RGB")
        except Exception:
            time.sleep(1.5 * (attempt + 1))
    return Image.new("RGB", (TILE, TILE), (10, 26, 34))


def banner(name, token, geom, fallback):
    from PIL import Image, ImageDraw
    if geom:
        pts = [p for r in rings_of(geom) for p in r]
        lons = [p[0] for p in pts]; lats = [p[1] for p in pts]
        cx, cy = (min(lons) + max(lons)) / 2, (min(lats) + max(lats)) / 2
        # pick the largest zoom whose mercator-projected bbox (with margin) fits 1024x512
        z = 16
        while z > 11:
            x0, y0 = merc(min(lons), max(lats), z)
            x1, y1 = merc(max(lons), min(lats), z)
            if (x1 - x0) * 1.25 <= W and (y1 - y0) * 1.25 <= H:
                break
            z -= 1
    else:
        cx, cy, z = fallback[0], fallback[1], fallback[2] + 1   # v2: one zoom sharper than v1
        z = min(z, 16)
    cpx, cpy = merc(cx, cy, z)
    ox, oy = cpx - W / 2, cpy - H / 2                            # top-left of crop in global px
    tx0, ty0 = int(ox // TILE), int(oy // TILE)
    tx1, ty1 = int((ox + W) // TILE), int((oy + H) // TILE)
    mosaic = Image.new("RGB", ((tx1 - tx0 + 1) * TILE, (ty1 - ty0 + 1) * TILE))
    for j, ty in enumerate(range(ty0, ty1 + 1)):
        for i, tx in enumerate(range(tx0, tx1 + 1)):
            mosaic.paste(fetch_tile(z, ty, tx, token), (i * TILE, j * TILE))
    img = mosaic.crop((int(ox - tx0 * TILE), int(oy - ty0 * TILE),
                       int(ox - tx0 * TILE) + W, int(oy - ty0 * TILE) + H))
    dr = ImageDraw.Draw(img)
    if geom:
        for ring in rings_of(geom):
            px = [(merc(p[0], p[1], z)[0] - ox, merc(p[0], p[1], z)[1] - oy) for p in ring]
            dr.line(px + [px[0]], fill=HALO, width=9, joint="curve")
            dr.line(px + [px[0]], fill=GOLD, width=4, joint="curve")
    else:
        r = 26
        dr.ellipse([W / 2 - r - 3, H / 2 - r - 3, W / 2 + r + 3, H / 2 + r + 3], outline=HALO, width=8)
        dr.ellipse([W / 2 - r, H / 2 - r, W / 2 + r, H / 2 + r], outline=GOLD, width=4)
    os.makedirs(OUT, exist_ok=True)
    p = os.path.join(OUT, f"sat_{slug(name)}.jpg")
    img.save(p, "JPEG", quality=86, progressive=True, optimize=True)
    return p, z


def main():
    base = os.environ.get("AZIMUTH_URL", "https://azimuth-2.digitalchemy.workers.dev")
    key = os.environ.get("READ_KEY") or sys.exit("need READ_KEY")
    token = get_token(base, key)
    areas = json.load(open(os.path.join(PUB, "mp_areas.json"), encoding="utf-8"))
    polys = {re.sub(r"[^a-z0-9]", "", f["properties"]["n"].lower()): f["geometry"] for f in areas["features"]}
    only = sys.argv[sys.argv.index("--only") + 1].lower().replace(" ", "") if "--only" in sys.argv else None
    for name, fb in PLACES.items():
        sl = slug(name)
        if only and only not in sl:
            continue
        p, z = banner(name, token, polys.get(sl), fb)
        print(f"  {name:32s} z{z} {'poly' if polys.get(sl) else 'ring'} -> {os.path.getsize(p)//1024} KB")


if __name__ == "__main__":
    main()
