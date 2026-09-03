"""Georeferenced aerial ground texture for a NAJMA district (Esri World Imagery via ArcGIS Online).

    python scripts/ground_imagery.py <slug> [--px auto|4096|3072|2048] [--pad 150] [--quality 82]
                                            [--max-mb 1.2] [--auth auto|env|arcpy|worker|anon]
                                            [--fetch-px 4096] [--tile-px 2048] [--variant NAME] [--check PATH.png]

Reads  data/ce/<slug>/buildings.geojson (WGS84 footprints) -> bbox -> EPSG:32640 metres -> padded,
pixel-square bbox -> World_Imagery MapServer `export` (bbox/imageSR 32640, PNG24, tiled if > 4096 px)
-> one Lanczos downscale -> JPEG that obeys the size guard.

Writes data/ce/<slug>/ground_imagery.jpg          north-up, EPSG:32640, square pixels
       data/ce/<slug>/ground_imagery.json         bbox (m), scene box (x = easting, z = -northing), px, attribution
       data/ce/<slug>/ground_imagery.README.md    three.js drop-in + on-screen attribution text
`--variant hi` writes ground_imagery_hi.* instead (canonical files untouched).

Scene convention (matches ctx.json / the CE GLBs): x = easting, z = -northing, absolute EPSG:32640 metres.
The image's top row is north, i.e. the SMALLER z. Nothing here touches the Worker or its KV.
"""
import argparse
import datetime as dt
import io
import json
import math
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))
DATA = os.path.join(ROOT, "data", "ce")

SERVICE = "https://services.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer"
MAX_REQ_PX = 4096            # service maxImageWidth/Height
TILE_PX = 2048               # request size actually used - the service 500s intermittently on 4096-wide PNG exports
SIZE_LADDER = (4096, 3072, 2048, 1536, 1024)
QUALITY_FLOOR = 60
PROPY = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "ArcGIS", "Pro", "bin", "Python", "Scripts", "propy.bat")
WORKER_TOKEN_URL = "https://azimuth-2.digitalchemy.workers.dev/esri_token"
LISTENER_ENV = r"C:\Dev\azimuth-listener-naj\.env"
UA = "naj-market-pulse/ground_imagery (DigitAlchemy)"


def log(*a):
    print("[ground_imagery]", *a, flush=True)


# ---------------------------------------------------------------- projection (WGS84 -> UTM 40N)
def _make_projector():
    try:
        from pyproj import Transformer
        tr = Transformer.from_crs("EPSG:4326", "EPSG:32640", always_xy=True)
        return lambda lon, lat: tr.transform(lon, lat)
    except Exception:
        pass

    # Kruger series transverse Mercator (agrees with pyproj to < 1 mm inside the zone)
    a, f, k0, lon0 = 6378137.0, 1 / 298.257223563, 0.9996, math.radians(57.0)
    n = f / (2 - f)
    A = a / (1 + n) * (1 + n * n / 4 + n ** 4 / 64)
    al = (n / 2 - 2 * n * n / 3 + 5 * n ** 3 / 16, 13 * n * n / 48 - 3 * n ** 3 / 5, 61 * n ** 3 / 240)
    e = math.sqrt(f * (2 - f))

    def proj(lon, lat):
        phi, lam = math.radians(lat), math.radians(lon) - lon0
        t = math.sinh(math.atanh(math.sin(phi)) - e * math.atanh(e * math.sin(phi)))
        xi, eta = math.atan2(t, math.cos(lam)), math.atanh(math.sin(lam) / math.sqrt(1 + t * t))
        E, N = eta, xi
        for j, aj in enumerate(al, 1):
            E += aj * math.cos(2 * j * xi) * math.sinh(2 * j * eta)
            N += aj * math.sin(2 * j * xi) * math.cosh(2 * j * eta)
        return 500000 + k0 * A * E, k0 * A * N

    return proj


def footprint_bbox_utm(geojson_path):
    g = json.load(open(geojson_path, encoding="utf-8"))
    proj = _make_projector()
    xs, ys = [], []

    def walk(c):
        if isinstance(c[0], (int, float)):
            x, y = proj(c[0], c[1])
            xs.append(x)
            ys.append(y)
        else:
            for k in c:
                walk(k)

    for f in g["features"]:
        if f.get("geometry"):
            walk(f["geometry"]["coordinates"])
    if not xs:
        raise SystemExit("no footprint vertices in " + geojson_path)
    return min(xs), min(ys), max(xs), max(ys), len(g["features"])


def padded_pixel_bbox(bb, pad, long_px):
    """Pad the bbox, then grow the short side so the raster has exactly square pixels."""
    xmin, ymin, xmax, ymax = bb[0] - pad, bb[1] - pad, bb[2] + pad, bb[3] + pad
    w_m, h_m = xmax - xmin, ymax - ymin
    res = max(w_m, h_m) / long_px
    w_px, h_px = (long_px, math.ceil(h_m / res)) if w_m >= h_m else (math.ceil(w_m / res), long_px)
    cx, cy = (xmin + xmax) / 2, (ymin + ymax) / 2
    w_m, h_m = w_px * res, h_px * res
    return (cx - w_m / 2, cy - h_m / 2, cx + w_m / 2, cy + h_m / 2), (w_px, h_px), res


# ---------------------------------------------------------------- auth
def _read_worker_key():
    t = open(LISTENER_ENV, encoding="utf-8", errors="ignore").read()
    m = re.search(r"GROUPS_URL\s*=\s*(\S+)", t)
    k = re.search(r"[?&]key=([^&\s\"']+)", m.group(1)) if m else None
    if not k:
        raise RuntimeError("GROUPS_URL key= not found in listener .env")
    return k.group(1)


def token_arcpy():
    try:
        import arcpy  # running under propy
        tok = arcpy.GetSigninToken()
        if tok and tok.get("token"):
            return tok["token"], tok.get("referer")
        raise RuntimeError("arcpy.GetSigninToken() returned nothing - is Pro signed in?")
    except ImportError:
        pass
    if not os.path.exists(PROPY):
        raise RuntimeError("propy.bat not found")
    code = "import arcpy,json;print('TOKENJSON'+json.dumps(arcpy.GetSigninToken() or {}))"
    p = subprocess.run([PROPY, "-c", code], capture_output=True, text=True, timeout=180)
    for line in p.stdout.splitlines():
        if line.startswith("TOKENJSON"):
            tok = json.loads(line[len("TOKENJSON"):])
            if tok.get("token"):
                return tok["token"], tok.get("referer")
    raise RuntimeError("no sign-in token from propy (Pro not signed in?)")


def token_worker():
    url = WORKER_TOKEN_URL + "?" + urllib.parse.urlencode({"key": _read_worker_key()})
    r = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=30)
    body = r.read().decode("utf-8", "ignore").strip()
    try:
        j = json.loads(body)
        tok = j.get("token") or j.get("access_token")
    except ValueError:
        tok = body if re.fullmatch(r"[A-Za-z0-9_\-\.]{20,}", body) else None
    if not tok:
        raise RuntimeError("worker esri_token: unrecognised response")
    return tok, None


def resolve_token(mode):
    order = {"auto": ("env", "arcpy", "worker", "anon"), "env": ("env",), "arcpy": ("arcpy",),
             "worker": ("worker",), "anon": ("anon",)}[mode]
    for src in order:
        try:
            if src == "env":
                if os.environ.get("ESRI_TOKEN"):
                    return os.environ["ESRI_TOKEN"], None, "env:ESRI_TOKEN"
                raise RuntimeError("ESRI_TOKEN not set")
            if src == "arcpy":
                t, ref = token_arcpy()
                return t, ref, "arcgis-pro-signin (arcpy.GetSigninToken)"
            if src == "worker":
                t, ref = token_worker()
                return t, ref, "azimuth-worker esri_token"
            return None, None, "anonymous (public World_Imagery MapServer)"
        except Exception as e:  # noqa: BLE001
            log(f"auth {src}: {e}")
    raise SystemExit("no usable auth path")


# ---------------------------------------------------------------- fetch
def http_get(url, referer=None, retries=4, timeout=180):
    last = None
    for i in range(retries):
        try:
            hdr = {"User-Agent": UA}
            if referer:
                hdr["Referer"] = referer
            r = urllib.request.urlopen(urllib.request.Request(url, headers=hdr), timeout=timeout)
            body = r.read()
            ct = r.headers.get("content-type", "")
            if not ct.startswith("image/"):
                raise RuntimeError(f"non-image response ({ct}): {body[:200]!r}")
            return body
        except Exception as e:  # noqa: BLE001
            last = e
            log(f"fetch attempt {i + 1}/{retries} failed: {e}")
            time.sleep(2 * (i + 1))
    raise SystemExit(f"export failed: {last}")


def export_tile(bbox, size, token, referer):
    q = {"bbox": ",".join(f"{v:.3f}" for v in bbox), "bboxSR": 32640, "imageSR": 32640,
         "size": f"{size[0]},{size[1]}", "format": "png24", "transparent": "false", "f": "image"}
    if token:
        q["token"] = token
    return http_get(SERVICE + "/export?" + urllib.parse.urlencode(q), referer)


def fetch_mosaic(bbox, px, res, token, referer, tile_px=TILE_PX):
    from PIL import Image
    W, H = px
    tile_px = min(tile_px, MAX_REQ_PX)
    cols, rows = math.ceil(W / tile_px), math.ceil(H / tile_px)
    xs = [round(i * W / cols) for i in range(cols + 1)]
    ys = [round(j * H / rows) for j in range(rows + 1)]
    out = Image.new("RGB", (W, H))
    n = 0
    for j in range(rows):
        for i in range(cols):
            x0, x1, y0, y1 = xs[i], xs[i + 1], ys[j], ys[j + 1]
            tb = (bbox[0] + x0 * res, bbox[3] - y1 * res, bbox[0] + x1 * res, bbox[3] - y0 * res)
            log(f"export tile {i},{j} {x1 - x0}x{y1 - y0}px")
            im = Image.open(io.BytesIO(export_tile(tb, (x1 - x0, y1 - y0), token, referer))).convert("RGB")
            if im.size != (x1 - x0, y1 - y0):
                im = im.resize((x1 - x0, y1 - y0), Image.LANCZOS)
            out.paste(im, (x0, y0))
            n += 1
    return out, n


def service_copyright():
    try:
        r = urllib.request.urlopen(urllib.request.Request(SERVICE + "?f=pjson", headers={"User-Agent": UA}), timeout=30)
        return json.loads(r.read().decode("utf-8", "ignore")).get("copyrightText") or ""
    except Exception:  # noqa: BLE001
        return "Source: Esri, Maxar, Earthstar Geographics, and the GIS User Community"


# ---------------------------------------------------------------- encode with size guard
def encode_guarded(img, px_mode, quality, max_bytes, force):
    from PIL import Image
    W0 = max(img.size)
    sizes = [int(px_mode)] if px_mode != "auto" else [s for s in SIZE_LADDER if s <= W0]

    def enc(im, q):
        b = io.BytesIO()
        im.save(b, "JPEG", quality=q, optimize=True, subsampling=2)
        return b.getvalue()

    def at(long_px):
        if long_px == W0:
            return img
        sc = long_px / W0
        return img.resize((round(img.width * sc), round(img.height * sc)), Image.LANCZOS)

    tried = []
    for s in sizes:                       # resolution first, at the requested quality
        im = at(s)
        data = enc(im, quality)
        tried.append((s, quality, len(data)))
        if len(data) <= max_bytes:
            return im, data, quality, tried
    if px_mode != "auto":                 # explicit size: trade quality down to the floor
        im = at(sizes[0])
        for q in range(quality - 4, QUALITY_FLOOR - 1, -4):
            data = enc(im, q)
            tried.append((sizes[0], q, len(data)))
            if len(data) <= max_bytes:
                return im, data, q, tried
    if force:
        im = at(sizes[-1])
        data = enc(im, quality)
        log("WARNING size guard exceeded; --force wrote", len(data), "bytes")
        return im, data, quality, tried
    raise SystemExit("size guard: nothing <= %.2f MB; tried %s (use --max-mb, --px or --force)"
                     % (max_bytes / 1e6, [(s, q, round(b / 1e6, 2)) for s, q, b in tried]))


# ---------------------------------------------------------------- outputs
def draw_check(img, meta, ctx, path):
    """Overlay ctx.json roads (scene metres) on the raster to prove registration."""
    from PIL import ImageDraw
    im = img.copy()
    d = ImageDraw.Draw(im)
    x0, ymax, res = meta["xmin"], meta["ymax"], meta["m_per_px"]

    def to_px(p):  # p = [x, z] scene metres; z = -northing
        return (p[0] - x0) / res, (ymax + p[1]) / res

    for key, col in (("roads", (255, 220, 80)), ("water", (80, 200, 255)), ("green", (120, 255, 120))):
        for rings in ctx.get(key, []):
            for ring in rings:
                pts = [to_px(p) for p in ring]
                if len(pts) > 1:
                    d.line(pts + [pts[0]], fill=col, width=2)
    im.save(path)
    log("check overlay ->", path)


README = """# Ground imagery - {district}

`{jpg}` is Esri World Imagery for this district's footprint bbox padded {pad} m, exported from
ArcGIS Online in EPSG:32640 (UTM 40N), north-up, square pixels. `{jsn}` carries the placement.

| | |
|---|---|
| bbox (m, EPSG:32640) | xmin {xmin:.1f}  ymin {ymin:.1f}  xmax {xmax:.1f}  ymax {ymax:.1f} |
| scene box (x = easting, z = -northing) | x {x0:.1f} .. {x1:.1f}   z {z0:.1f} .. {z1:.1f} |
| pixels / resolution | {w} x {h} px, {res:.2f} m/px, JPEG q{q}, {mb:.2f} MB |
| fetched | {fetched} |

Scene x/z are absolute metres, the same frame as `ctx.json` and the CE GLBs. The image's TOP row is
north, which is the SMALLER z. A `PlaneGeometry` rotated `-PI/2` about X puts its local +y (uv v = 1,
the image top with the default `flipY = true`) at world -z, so no texture flip is needed.

## three.js drop-in (after `ROOTREF` and `ground` exist - e.g. next to `drawCtx()`)

```js
const G = await fetch("/img/ground_{slug}").then(r => r.json());                 // this .json
const tex = new THREE.TextureLoader().load("/img/ground_{slug}_jpg");            // this .jpg
tex.colorSpace = THREE.SRGBColorSpace;                                          // flipY stays true
tex.anisotropy = ren.capabilities.getMaxAnisotropy();
const geo = new THREE.PlaneGeometry(G.scene.x1 - G.scene.x0, G.scene.z1 - G.scene.z0);
geo.rotateX(-Math.PI / 2);                                                      // +y (north) -> -z
const mat = new THREE.MeshStandardMaterial({{ map: tex, roughness: 1, metalness: 0,
  color: 0x8F958F }});                                                            // ~55 % multiplier keeps the dark brand look; 0x707570 for darker
const gp = new THREE.Mesh(geo, mat);
gp.position.set((G.scene.x0 + G.scene.x1) / 2 + ROOTREF.position.x,             // GLB root is re-centred; ctx uses the same offset
  ground.position.y + 0.05,                                                     // 5 cm above the ground disc, below ctx green (0.3) / roads (0.55)
  (G.scene.z0 + G.scene.z1) / 2 + ROOTREF.position.z);
gp.receiveShadow = true; gp.renderOrder = -1;                                   // draws before the massing
scene.add(gp);
```

Notes: the ctx `roads` polygons (dark grey, y + 0.55) will sit on top of the photographed roads - drop
them or set their opacity ~0.35 once the imagery is on. The ground disc stays as the outer ground
beyond the padded bbox. Serve the two files from the Worker under whatever `/img/` keys you prefer;
the snippet assumes `ground_<slug>` (json) and `ground_<slug>_jpg`.

## Attribution (must be visible on screen while the imagery is shown)

`{attribution}`

Esri World Imagery is licensed for use inside ArcGIS-licensed applications and apps built on ArcGIS
(the export was made under the organisation's ArcGIS Online sign-in). Keep the attribution line in
the viewer footer, do not redistribute the JPEG as a standalone product, and do not strip the
source note from `{jsn}`.
"""


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("slug")
    ap.add_argument("--px", default="auto", help="long side in px: auto (largest that passes the size guard) or a number")
    ap.add_argument("--fetch-px", type=int, default=4096, help="long side requested from the service (tiled above 4096)")
    ap.add_argument("--pad", type=float, default=150.0, help="padding around the footprint bbox, metres")
    ap.add_argument("--quality", type=int, default=82)
    ap.add_argument("--max-mb", type=float, default=1.2, help="JPEG size guard")
    ap.add_argument("--auth", default="auto", choices=("auto", "env", "arcpy", "worker", "anon"))
    ap.add_argument("--variant", default="", help="suffix -> ground_imagery_<variant>.*")
    ap.add_argument("--check", default="", help="write a registration-check PNG (ctx roads/water drawn over the raster)")
    ap.add_argument("--tile-px", type=int, default=TILE_PX, help="per-request tile size (<= 4096)")
    ap.add_argument("--force", action="store_true", help="write even if the size guard cannot be met")
    a = ap.parse_args()

    from PIL import Image
    Image.MAX_IMAGE_PIXELS = None

    ddir = os.path.join(DATA, a.slug)
    gj = os.path.join(ddir, "buildings.geojson")
    if not os.path.exists(gj):
        raise SystemExit("missing " + gj)
    base = "ground_imagery" + (("_" + a.variant) if a.variant else "")
    out_jpg, out_json, out_md = (os.path.join(ddir, base + ext) for ext in (".jpg", ".json", ".README.md"))

    fb = footprint_bbox_utm(gj)
    log(f"{a.slug}: {fb[4]} footprints, bbox E {fb[0]:.1f}..{fb[2]:.1f} N {fb[1]:.1f}..{fb[3]:.1f} "
        f"({fb[2] - fb[0]:.0f} x {fb[3] - fb[1]:.0f} m)")
    fetch_px = a.fetch_px if a.px == "auto" else max(a.fetch_px, int(a.px))
    bbox, px, res = padded_pixel_bbox(fb[:4], a.pad, fetch_px)
    log(f"padded bbox {bbox[0]:.1f},{bbox[1]:.1f},{bbox[2]:.1f},{bbox[3]:.1f}  {px[0]}x{px[1]} px @ {res:.3f} m/px")

    token, referer, auth = resolve_token(a.auth)
    log("auth:", auth)
    img, ntiles = fetch_mosaic(bbox, px, res, token, referer, a.tile_px)
    if img.size != px:
        raise SystemExit(f"mosaic size {img.size} != {px}")

    im, data, q, tried = encode_guarded(img, a.px, a.quality, a.max_mb * 1e6, a.force)
    with open(out_jpg, "wb") as f:
        f.write(data)
    res_out = (bbox[2] - bbox[0]) / im.width

    ctx_path = os.path.join(ddir, "ctx.json")
    ctx = json.load(open(ctx_path, encoding="utf-8")) if os.path.exists(ctx_path) else {}
    attribution = service_copyright()
    fetched = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    meta = {
        "district": a.slug,
        "crs": "EPSG:32640",
        "xmin": round(bbox[0], 3), "ymin": round(bbox[1], 3), "xmax": round(bbox[2], 3), "ymax": round(bbox[3], 3),
        "scene": {"x0": round(bbox[0], 3), "x1": round(bbox[2], 3), "z0": round(-bbox[3], 3), "z1": round(-bbox[1], 3)},
        "plane": {"center": [round((bbox[0] + bbox[2]) / 2, 3), round(-(bbox[1] + bbox[3]) / 2, 3)],
                  "size": [round(bbox[2] - bbox[0], 3), round(bbox[3] - bbox[1], 3)],
                  "note": "x = easting, z = -northing (absolute metres); image top row = north = smaller z"},
        "px": [im.width, im.height],
        "m_per_px": round(res_out, 4),
        "footprint_bbox": [round(v, 3) for v in fb[:4]],
        "pad_m": a.pad,
        "glb_center": ctx.get("glb_center"),
        "file": os.path.basename(out_jpg),
        "bytes": len(data),
        "jpeg_quality": q,
        "fetch_px": list(px),
        "tiles": ntiles,
        "source": "Esri World Imagery via ArcGIS Online (World_Imagery MapServer export, PNG24 -> JPEG)",
        "service": SERVICE,
        "attribution": attribution,
        "licence": "Esri World Imagery - use within ArcGIS-licensed applications with on-screen attribution; not for standalone redistribution",
        "auth": auth,
        "fetched": fetched,
    }
    json.dump(meta, open(out_json, "w", encoding="utf-8"), indent=1)

    s = meta["scene"]
    open(out_md, "w", encoding="utf-8").write(README.format(
        district=ctx.get("district") or a.slug, slug=a.slug, jpg=os.path.basename(out_jpg), jsn=os.path.basename(out_json),
        pad=int(a.pad), xmin=meta["xmin"], ymin=meta["ymin"], xmax=meta["xmax"], ymax=meta["ymax"],
        x0=s["x0"], x1=s["x1"], z0=s["z0"], z1=s["z1"], w=im.width, h=im.height, res=res_out, q=q,
        mb=len(data) / 1e6, fetched=fetched, attribution=attribution))

    if a.check:
        draw_check(im, meta, ctx, a.check)

    log(f"wrote {out_jpg} {im.width}x{im.height} q{q} {len(data) / 1e6:.2f} MB ({res_out:.2f} m/px); tried {[(t[0], t[1], round(t[2] / 1e6, 2)) for t in tried]}")
    log("wrote", out_json, "and", out_md)


if __name__ == "__main__":
    main()
