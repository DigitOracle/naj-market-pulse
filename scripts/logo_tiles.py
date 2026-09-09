"""Developer logo tiles for the Azimuth board (v73 /home grid).
1. Pull inline SVGs saved from the browser probe (Iman, Meraas) and download the remaining raster logos.
2. Rasterise every raw_<key>.* into a 512x256 PNG plate data/board/logos/<key>.png:
   transparent background, logo fitted into 80 % of the tile, white-on-transparent marks recoloured to the board ink (#0B2A3A)
   so every tile reads on the light card. SVG rasterisation via cairosvg when present, otherwise via the browser (see logo_tiles_browser.html).
"""
import glob, json, os, re, sys, urllib.request
from PIL import Image, ImageOps

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, ".."))
LOGOS = os.path.join(ROOT, "data", "board", "logos"); os.makedirs(LOGOS, exist_ok=True)
INK = (11, 42, 58)
TILE_W, TILE_H = 512, 256   # 2:1 plate: wordmarks fill the width, square marks fill the height

def fetch(url, out):
    if os.path.exists(out): return out
    data = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=30).read()
    open(out, "wb").write(data); print("fetched", os.path.basename(out), len(data)); return out

def pull_inline_svgs():
    files = sorted(glob.glob(r"C:\Users\kwils\.claude\projects\C--Users-kwils-Downloads\13220613-8afb-4073-9b13-9321c45576ee\tool-results\mcp-Claude_Browser-browser_batch-*.txt"), key=os.path.getmtime)
    for f in files[::-1][:6]:
        txt = open(f, encoding="utf-8").read()
        for key, marker in (("iman", 'viewBox=\\"0 0 166 65\\"'), ("meraas", 'viewBox=\\"0 0 253 64\\"')):
            out = os.path.join(LOGOS, "raw", "raw_%s.svg" % key)
            if os.path.exists(out) and os.path.getsize(out) > 500: continue
            m = re.search(r'"svg":\s*"(<svg[^"]*?' + re.escape(marker) + r'.*?</svg>)"', txt, re.S)
            if m:
                svg = json.loads('"' + m.group(1) + '"'); open(out, "w", encoding="utf-8").write(svg); print("saved", out, len(svg))

def is_white_mark(im):
    """True when the visible pixels are (near) white -> recolour to ink."""
    px = im.convert("RGBA").getdata(); vis = [p for p in px if p[3] > 40]
    if not vis: return False
    bright = sum(1 for p in vis if min(p[:3]) > 200)
    return bright / len(vis) > 0.85

def recolour(im, rgb):
    im = im.convert("RGBA"); a = im.getchannel("A")
    solid = Image.new("RGBA", im.size, rgb + (255,)); solid.putalpha(a); return solid

def tile(im, out):
    im = im.convert("RGBA"); bbox = im.getbbox()
    if bbox: im = im.crop(bbox)
    if is_white_mark(im): im = recolour(im, INK)
    im.thumbnail((int(TILE_W * 0.86), int(TILE_H * 0.74)), Image.LANCZOS)
    canvas = Image.new("RGBA", (TILE_W, TILE_H), (0, 0, 0, 0)); canvas.paste(im, ((TILE_W - im.width) // 2, (TILE_H - im.height) // 2), im)
    canvas.save(out, optimize=True); print("tile", os.path.basename(out), im.size)

def svg_to_png(src, scale_px=1600):
    try:
        import cairosvg
    except Exception:
        return None
    tmp = src[:-4] + "_r.png"; cairosvg.svg2png(url=src, write_to=tmp, output_width=scale_px); return tmp

RASTER = {"fakhruddin": "https://portal.fandcproperties.ae/uploads/panel/developers/logo/fakhruddin_properties_logo_1713885144.png"}
PICK = {"omniyat": "raw_omniyat_word.svg", "hh": "raw_hh.svg", "meraas": "raw_meraas.svg", "select": "raw_select.svg", "ellington": "raw_ellington.png",
        "arada": "raw_arada.svg", "zaya": "raw_zaya.png", "palma": "raw_palma_art.png", "sobha": "raw_sobha.png", "fakhruddin": "raw_fakhruddin.png", "beyond": "raw_beyond.webp", "imtiaz": "raw_imtiaz.svg", "prestigeone": "raw_prestigeone.svg", "iman": "raw_iman.svg"}

if __name__ == "__main__":
    pull_inline_svgs()
    for k, u in RASTER.items():
        try: fetch(u, os.path.join(LOGOS, "raw", "raw_%s.png" % k))
        except Exception as e: print("fetch", k, "FAILED", str(e)[:80])
    pending = []
    for k, f in PICK.items():
        src = os.path.join(LOGOS, "raw", f)
        if not os.path.exists(src): print("MISSING", k, f); continue
        if f.endswith(".svg"):
            r = svg_to_png(src)
            if not r: pending.append(k); continue
            tile(Image.open(r), os.path.join(LOGOS, k + ".png")); os.remove(r)
        else:
            tile(Image.open(src), os.path.join(LOGOS, k + ".png"))
    if pending: print("SVG needs browser rasterisation:", pending)
