"""Elevation grid for a NAJMA district, in the same scene frame as the aerial ground imagery.

    python scripts/terrain_grid.py <slug> [--n 128] [--source auto|esri|srtm] [--zoom 13]
                                          [--smooth-m 150] [--flat-m 1.5] [--auth auto|env|arcpy|worker|anon]

Reads  data/ce/<slug>/ground_imagery.json  (the padded, pixel-square bbox in EPSG:32640 metres)
Writes data/ce/<slug>/terrain.json         {"crs","scene":{x0,x1,z0,z1},"nx","nz","min_m","max_m","z":[...]}
       data/ce/<slug>/terrain.README.md    source, licence and the viewer contract

Scene convention (matches ground_imagery.json, ctx.json and the CE GLBs): x = easting, z = -northing,
absolute EPSG:32640 metres.  `z` is ROW-MAJOR starting at the NORTH edge (z = scene.z0, the smaller z)
and running east, i.e. exactly the vertex order of a THREE.PlaneGeometry(w, h, nx-1, nz-1) that has been
rotated -PI/2 about X.  Samples sit ON the grid nodes.

Sources, in the order `auto` tries them
---------------------------------------
esri  Esri WorldElevation3D/Terrain3D ImageServer exportImage (F32 TIFF), same ArcGIS token path as
      scripts/ground_imagery.py.  PREFERRED, but VERIFY IT: over Dubai this service currently answers
      with a degenerate surface - a single tilted plane with no horizontal detail, identical at every
      requested pixel size, and it flattens the Hajar mountains near Hatta to about a sixth of their
      real height.  `auto` therefore fits a plane to whatever Esri returns and rejects the answer when
      the residual is essentially zero, i.e. when the "terrain" is only that plane.
srtm  SRTM 30 m via the AWS Open Data terrain tiles (terrarium PNG encoding, no key).  Spot checks
      agree to 1 m with SRTMGL1 point queries.  Being a year-2000 survey it is effectively bare earth
      for modern Dubai, which is what a massing model wants to stand on. It does, however, carry
      +/- 10 m of radar speckle over flat coastal sand, which over Dubai is larger than the real
      relief - hence the --smooth-m low-pass, which recovers the trend surface.

Heights are rounded to 0.1 m and written without whitespace: a 128-node district lands near 60 KB.
Nothing here touches CityEngine, the Worker or its KV.
"""
import argparse
import datetime as dt
import io
import json
import math
import os
import sys
import time
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))
DATA = os.path.join(ROOT, "data", "ce")
sys.path.insert(0, HERE)

ESRI = "https://elevation3d.arcgis.com/arcgis/rest/services/WorldElevation3D/Terrain3D/ImageServer"
TERRARIUM = "https://elevation-tiles-prod.s3.amazonaws.com/terrarium/{z}/{x}/{y}.png"
UA = "naj-market-pulse/terrain_grid (DigitAlchemy)"
MAX_REQ_PX = 4100          # ImageServer maxImageWidth/Height; a 128-node grid never comes near it
FLAT_M = 1.5               # total relief below this and the district is reported as flat
PLANE_RESID_M = 0.05       # Esri residual-to-a-plane below this = degenerate, fall through to srtm

ESRI_ATTR = ("Source: Esri, Airbus, USGS, NGA, NASA, CGIAR, NCEAS, NLS, OS, NMA, Geodatastyrelsen "
             "and the GIS User Community")
SRTM_ATTR = "Elevation: SRTM (NASA/USGS, public domain) via the AWS Open Data terrain tiles"


def log(*a):
    print("[terrain_grid]", *a, flush=True)


def http_get(url, referer=None, retries=4, timeout=180, want="image/"):
    last = None
    for i in range(retries):
        try:
            hdr = {"User-Agent": UA}
            if referer:
                hdr["Referer"] = referer
            r = urllib.request.urlopen(urllib.request.Request(url, headers=hdr), timeout=timeout)
            body = r.read()
            ct = r.headers.get("content-type", "")
            if want and not ct.startswith(want):
                raise RuntimeError("unexpected content-type %s: %r" % (ct, body[:200]))
            return body
        except Exception as e:  # noqa: BLE001
            last = e
            log("fetch attempt %d/%d failed: %s" % (i + 1, retries, e))
            time.sleep(2 * (i + 1))
    raise RuntimeError("GET failed: %s" % last)


# ---------------------------------------------------------------- source: Esri Terrain3D
def esri_grid(bbox, size, auth_mode):
    """bbox = (xmin, ymin, xmax, ymax) EPSG:32640 metres (NORTHING, not scene z)."""
    try:
        from ground_imagery import resolve_token
        token, referer, auth = resolve_token(auth_mode)
    except Exception as e:  # noqa: BLE001
        log("token resolution fell back to anonymous:", e)
        token, referer, auth = None, None, "anonymous (public Terrain3D ImageServer)"
    log("esri auth:", auth)
    q = {"bbox": ",".join("%.4f" % v for v in bbox), "bboxSR": 32640, "imageSR": 32640,
         "size": "%d,%d" % (size[0], size[1]), "format": "tiff", "pixelType": "F32",
         "interpolation": "RSP_BilinearInterpolation",
         "noDataInterpretation": "esriNoDataMatchAny", "f": "image"}
    if token:
        q["token"] = token
    raw = http_get(ESRI + "/exportImage?" + urllib.parse.urlencode(q), referer)
    from PIL import Image
    im = Image.open(io.BytesIO(raw))
    if im.size != tuple(size):
        raise RuntimeError("service returned %s, asked for %s" % (im.size, tuple(size)))
    if im.mode != "F":
        im = im.convert("F")
    vals = list(im.getdata())
    meta = {"source": "Esri WorldElevation3D/Terrain3D ImageServer exportImage (F32 TIFF, bilinear)",
            "service": ESRI, "attribution": ESRI_ATTR, "auth": auth,
            "licence": ("Esri World Elevation - use within ArcGIS-licensed applications with on-screen "
                        "attribution; not for standalone redistribution")}
    return vals, meta


def plane_residual(vals, nx, nz):
    """RMS of the field about its own best-fit plane. ~0 means the 'terrain' IS a plane."""
    good = [(i % nx, i // nx, v) for i, v in enumerate(vals) if v == v and -1e4 < v < 1e4]
    n = len(good)
    if n < 6:
        return float("inf")
    sx = sum(g[0] for g in good); sy = sum(g[1] for g in good); sv = sum(g[2] for g in good)
    mx, my, mv = sx / n, sy / n, sv / n
    sxx = syy = sxy = sxv = syv = 0.0
    for x, y, v in good:
        dx, dy, dv = x - mx, y - my, v - mv
        sxx += dx * dx; syy += dy * dy; sxy += dx * dy; sxv += dx * dv; syv += dy * dv
    det = sxx * syy - sxy * sxy
    if abs(det) < 1e-9:
        return float("inf")
    a = (sxv * syy - syv * sxy) / det
    b = (syv * sxx - sxv * sxy) / det
    return math.sqrt(sum((v - (mv + a * (x - mx) + b * (y - my))) ** 2 for x, y, v in good) / n)


# ---------------------------------------------------------------- source: SRTM terrain tiles
def _merc(lon, lat, z):
    n = 2.0 ** z
    la = math.radians(lat)
    return (lon + 180.0) / 360.0 * n, (1 - math.log(math.tan(la) + 1 / math.cos(la)) / math.pi) / 2 * n


def srtm_grid(nodes, zoom):
    """nodes = [(lon, lat), ...] in row-major grid order. Returns heights in metres."""
    from PIL import Image
    px = [(_merc(lon, lat, zoom)[0] * 256.0, _merc(lon, lat, zoom)[1] * 256.0) for lon, lat in nodes]
    need = set()
    for X, Y in px:
        for dx in (0, 1):
            for dy in (0, 1):
                need.add((int((X - 0.5 + dx) // 256), int((Y - 0.5 + dy) // 256)))
    log("srtm: %d terrarium tiles at z%d" % (len(need), zoom))
    tiles = {}
    for tx, ty in sorted(need):
        raw = http_get(TERRARIUM.format(z=zoom, x=tx, y=ty), want="image/")
        tiles[(tx, ty)] = Image.open(io.BytesIO(raw)).convert("RGB").load()

    def at(ix, iy):
        t = tiles.get((ix // 256, iy // 256))
        if t is None:
            return None
        r, g, b = t[ix % 256, iy % 256]
        return r * 256.0 + g + b / 256.0 - 32768.0

    out = []
    for X, Y in px:                     # bilinear on the tile lattice; pixel centres are at +0.5
        fx, fy = X - 0.5, Y - 0.5
        ix, iy = int(math.floor(fx)), int(math.floor(fy))
        tx, ty = fx - ix, fy - iy
        c = [at(ix, iy), at(ix + 1, iy), at(ix, iy + 1), at(ix + 1, iy + 1)]
        if any(v is None for v in c):
            out.append(next((v for v in c if v is not None), float("nan")))
            continue
        out.append((c[0] * (1 - tx) + c[1] * tx) * (1 - ty) + (c[2] * (1 - tx) + c[3] * tx) * ty)
    meta = {"source": "SRTM 30 m via the AWS Open Data terrain tiles (terrarium PNG, z%d, bilinear)" % zoom,
            "service": TERRARIUM, "attribution": SRTM_ATTR, "auth": "none (open data)",
            "licence": "SRTM is US public domain; the AWS terrain-tile distribution is free to use with attribution"}
    return out, meta


# ---------------------------------------------------------------- helpers
def fill_nodata(vals, nx):
    def bad(v):
        return v is None or v != v or v < -500.0 or v > 9000.0
    idx = [i for i, v in enumerate(vals) if bad(v)]
    if not idx:
        return 0
    good = [v for v in vals if not bad(v)]
    if not good:
        raise SystemExit("every sample is nodata - wrong bbox, or the source is down")
    fill = sorted(good)[len(good) // 2]
    n = len(vals)
    for i in idx:
        r, v = i // nx, None
        for step in range(1, n):
            for j in (i - step, i + step):
                if 0 <= j < n and j // nx == r and not bad(vals[j]):
                    v = vals[j]; break
            if v is None:
                for j in (i - step * nx, i + step * nx):
                    if 0 <= j < n and not bad(vals[j]):
                        v = vals[j]; break
            if v is not None:
                break
        vals[i] = fill if v is None else v
    return len(idx)


def smooth(vals, nx, nz, rad, passes=3):
    """Separable box mean, `passes` times (a box repeated 3x is a good Gaussian).

    A 30 m radar survey over flat coastal sand carries +/- 10 m of speckle - over Dubai that noise is
    larger than the real relief, so the trend surface is the only usable signal. Three passes at a
    ~150 m radius bring every district back to a physically sensible profile (Downtown 1..11 m, JVC
    2..28 m, Palm Jumeirah -2..6 m) while leaving the coast, the creek banks and the inland rise intact.
    """
    if rad <= 0 or passes <= 0:
        return vals
    for _ in range(passes):
        vals = _box(vals, nx, nz, rad)
    return vals


def _box(vals, nx, nz, rad):
    tmp = [0.0] * len(vals)
    for r in range(nz):
        base = r * nx
        for c in range(nx):
            a, b = max(0, c - rad), min(nx - 1, c + rad)
            tmp[base + c] = sum(vals[base + k] for k in range(a, b + 1)) / (b - a + 1)
    out = [0.0] * len(vals)
    for c in range(nx):
        for r in range(nz):
            a, b = max(0, r - rad), min(nz - 1, r + rad)
            out[r * nx + c] = sum(tmp[k * nx + c] for k in range(a, b + 1)) / (b - a + 1)
    return out


README = """# Terrain grid - {district}

`terrain.json` is a {nx} x {nz} lattice of ground heights covering exactly the bbox that
`ground_imagery.json` covers, so the aerial photo drapes onto it with unchanged UVs.

| | |
|---|---|
| CRS | EPSG:32640 (UTM 40N), heights in metres |
| scene box (x = easting, z = -northing) | x {x0:.1f} .. {x1:.1f}   z {z0:.1f} .. {z1:.1f} |
| grid | {nx} x {nz} nodes, {dx:.1f} m x {dz:.1f} m spacing |
| relief | min {mn:.1f} m, max {mx:.1f} m, range {rng:.1f} m{flat} |
| low-pass | 3 box passes, radius {rad} cells (~{radm:.0f} m) |
| before the low-pass | {rawmn:.1f} .. {rawmx:.1f} m (raw radar speckle) |
| nodata nodes | {nodata} (filled from the nearest valid sample) |
| fetched | {fetched} |

## Array order

`z` is row-major and starts at the NORTH edge, `scene.z0` (the SMALLER z, because z = -northing),
running east along each row. That is the vertex order of

```js
const g = new THREE.PlaneGeometry(x1 - x0, z1 - z0, nx - 1, nz - 1);
g.rotateX(-Math.PI / 2);                                // local +y (first row) -> world -z
const p = g.attributes.position;
for (let i = 0; i < p.count; i++) p.setY(i, zArr[i]);   // heights are already scene metres
g.computeVertexNormals();
```

Samples sit ON the nodes - no half-pixel shift is needed.

## Source and licence

{source}

`{attribution}`

{licence}

{note}
"""

ESRI_NOTE = """Esri's WorldElevation3D/Terrain3D was tried first, as the preferred source. Over Dubai it
answers with a degenerate surface: a single tilted plane, no horizontal detail, byte-identical
statistics whether you ask for 32 or 1024 samples across the same box, and the Hajar mountains near
Hatta flattened from ~350 m (SRTM point query) to ~200 m. This script fits a plane to the Esri
response and falls through to SRTM when the residual is under {resid} m, which is what happened here.
Re-run with `--source esri` to see the raw Esri answer for yourself."""


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("slug")
    ap.add_argument("--n", type=int, default=128, help="nodes on the long side (short side follows, square cells)")
    ap.add_argument("--source", default="auto", choices=("auto", "esri", "srtm"))
    ap.add_argument("--zoom", type=int, default=13, help="terrarium tile zoom for --source srtm (13 ~ 17 m/px)")
    ap.add_argument("--smooth-m", type=float, default=150.0, dest="smooth_m",
                    help="low-pass radius in metres (0 = raw); 3 box passes, see smooth()")
    ap.add_argument("--auth", default="auto", choices=("auto", "env", "arcpy", "worker", "anon"))
    ap.add_argument("--flat-m", type=float, default=FLAT_M, help="total relief below this is reported as flat")
    a = ap.parse_args()

    ddir = os.path.join(DATA, a.slug)
    gpath = os.path.join(ddir, "ground_imagery.json")
    if not os.path.exists(gpath):
        raise SystemExit("missing " + gpath + " - run scripts/ground_imagery.py first")
    G = json.load(open(gpath, encoding="utf-8"))
    xmin, ymin, xmax, ymax = G["xmin"], G["ymin"], G["xmax"], G["ymax"]
    w_m, h_m = xmax - xmin, ymax - ymin

    # node counts: long side = --n, short side follows so the cells stay square
    if w_m >= h_m:
        nx = a.n
        nz = max(2, int(round((nx - 1) * h_m / w_m)) + 1)
    else:
        nz = a.n
        nx = max(2, int(round((nz - 1) * w_m / h_m)) + 1)
    dx, dz = w_m / (nx - 1), h_m / (nz - 1)
    if max(nx, nz) > MAX_REQ_PX:
        raise SystemExit("grid too large for one exportImage request")
    log("%s: bbox %.0f x %.0f m -> %d x %d nodes (%.1f x %.1f m)" % (a.slug, w_m, h_m, nx, nz, dx, dz))

    vals = meta = None
    note = ""
    if a.source in ("auto", "esri"):
        try:
            # grow by half a cell so the service's pixel CENTRES land on the grid NODES
            req = (xmin - dx / 2, ymin - dz / 2, xmax + dx / 2, ymax + dz / 2)
            v, m = esri_grid(req, (nx, nz), a.auth)
            resid = plane_residual(v, nx, nz)
            log("esri plane residual: %.4f m" % resid)
            if a.source == "esri" or resid >= PLANE_RESID_M:
                vals, meta = v, m
            else:
                log("esri answer is a bare plane (residual < %.2f m) - falling through to srtm" % PLANE_RESID_M)
                note = ESRI_NOTE.format(resid=PLANE_RESID_M)
        except Exception as e:  # noqa: BLE001
            log("esri source failed:", e)
            if a.source == "esri":
                raise SystemExit("esri source failed and --source esri was forced")
            note = "Esri WorldElevation3D was tried first and failed: %s" % e

    if vals is None:
        from pyproj import Transformer
        inv = Transformer.from_crs("EPSG:32640", "EPSG:4326", always_xy=True)
        nodes = []
        for r in range(nz):
            N = ymax - r * dz                       # row 0 = north edge
            for c in range(nx):
                nodes.append(inv.transform(xmin + c * dx, N))
        vals, meta = srtm_grid(nodes, a.zoom)

    nfill = fill_nodata(vals, nx)
    log("nodata nodes filled: %d" % nfill)
    rad = 0 if a.smooth_m <= 0 else max(1, int(round(a.smooth_m / dx)))
    raw_mn, raw_mx = min(vals), max(vals)
    vals = smooth(vals, nx, nz, rad)
    log("low-pass: radius %d cells (~%.0f m) x3; raw %.1f..%.1f m" % (rad, rad * dx, raw_mn, raw_mx))

    z = [round(v, 1) + 0.0 for v in vals]
    mn, mx = min(z), max(z)
    rng = mx - mn
    scene = {"x0": round(xmin, 3), "x1": round(xmax, 3), "z0": round(-ymax, 3), "z1": round(-ymin, 3)}
    fetched = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    out = {
        "crs": "EPSG:32640",
        "district": a.slug,
        "scene": scene,
        "nx": nx, "nz": nz,
        "dx_m": round(dx, 3), "dz_m": round(dz, 3),
        "min_m": round(mn, 1), "max_m": round(mx, 1), "range_m": round(rng, 1),
        "flat": rng < a.flat_m,
        "order": "row-major from z0 (north) to z1 (south), each row x0 -> x1",
        "smooth_m": round(rad * dx, 1), "smooth_cells": rad, "smooth_passes": 3,
        "raw_min_m": round(raw_mn, 1), "raw_max_m": round(raw_mx, 1),
        "nodata_filled": nfill,
        "fetched": fetched,
        "z": z,
    }
    out.update(meta)
    if note:
        out["source_note"] = " ".join(note.split())
    tpath = os.path.join(ddir, "terrain.json")
    with open(tpath, "w", encoding="utf-8") as f:
        json.dump(out, f, separators=(",", ":"), ensure_ascii=False)
    nb = os.path.getsize(tpath)

    flat_note = ("  **FLAT** - below the %.1f m threshold; the viewer skips the mesh" % a.flat_m) if rng < a.flat_m else ""
    open(os.path.join(ddir, "terrain.README.md"), "w", encoding="utf-8").write(README.format(
        district=a.slug, nx=nx, nz=nz, dx=dx, dz=dz, mn=mn, mx=mx, rng=rng, flat=flat_note,
        rad=rad, radm=rad * dx, rawmn=raw_mn, rawmx=raw_mx, nodata=nfill, fetched=fetched, source=meta["source"],
        attribution=meta["attribution"], licence=meta["licence"], note=note, **scene))

    log("wrote %s  %dx%d  min %.1f m  max %.1f m  range %.1f m  %.0f KB%s"
        % (tpath, nx, nz, mn, mx, rng, nb / 1024.0, "  [FLAT]" if rng < a.flat_m else ""))
    if nb > 120 * 1024:
        log("WARNING %.0f KB exceeds the ~120 KB budget - drop --n" % (nb / 1024.0))


if __name__ == "__main__":
    main()
