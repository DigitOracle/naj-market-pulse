"""Overture Maps buildings -> per-footprint names / heights / attributes for the skyline districts.
For each district in data/ce/<slug>/buildings.geojson: take the footprint bbox (padded ~100 m), download Overture buildings
(theme buildings, type building) with the overturemaps CLI, cache the raw GeoJSON under data/names/overture_raw/<slug>.geojson,
then match Overture buildings to our footprints in EPSG:32640 metres: an Overture centroid inside or within 15 m of the footprint,
or polygon overlap > 50 % of the smaller of the two areas. Best candidate per footprint = largest overlap, then nearest centroid.
Output data/names/overture_<slug>.json:
  { "<feature index>": {"name", "height", "num_floors", "facade_color", "roof_shape", "class", "source": "overture",
                        "gers_id", "overlap", "dist_m"} }
Only footprints where Overture carries at least one useful attribute are written. build_anchors.py merges these
(name fills an unnamed footprint, height replaces the 3.2 m/level estimate when larger).
Licence: Overture buildings are ODbL 1.0 (OpenStreetMap-derived) / CDLA-Permissive 2.0 (other providers) - see data/names/README_sources.md.
Usage: python scripts/overture_names.py [--force] [--skip-download] [slug ...]
       (no slugs = priority districts first, then every other district)
"""
import glob, json, os, re, subprocess, sys, time
import geopandas as gpd
import pandas as pd
from shapely.geometry import shape

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, ".."))
CE = os.path.join(ROOT, "data", "ce"); OUT = os.path.join(ROOT, "data", "names"); RAW = os.path.join(OUT, "overture_raw")
os.makedirs(RAW, exist_ok=True)
UTM = "EPSG:32640"
PAD_DEG = 0.001          # ~100 m bbox padding so edge buildings are included
NEAR_M = 15.0            # Overture centroid within this distance of our footprint
OVERLAP = 0.50           # or intersection area / min(area) above this
PAUSE_S = 3              # polite gap between district downloads (anonymous S3 reads)
RETRIES = 4
PRIORITY = ["dubaimarina", "businessbay", "burjkhalifa", "palmjumeirah", "dubaimaritimecity", "alkhairanfirst", "dubaihills", "jumeirahvillagecircle"]
ARABIC = re.compile("[؀-ۿ]")


def bbox_of(feats):
    xs, ys = [], []
    for f in feats:
        g = f["geometry"]; coords = g["coordinates"]
        rings = coords if g["type"] == "Polygon" else [r for poly in coords for r in poly]
        for r in rings:
            for c in r: xs.append(c[0]); ys.append(c[1])
    return min(xs) - PAD_DEG, min(ys) - PAD_DEG, max(xs) + PAD_DEG, max(ys) + PAD_DEG


def download(slug, bbox, force=False):
    """overturemaps CLI -> data/names/overture_raw/<slug>.geojson (cached). Returns path or None."""
    out = os.path.join(RAW, f"{slug}.geojson")
    if os.path.exists(out) and os.path.getsize(out) > 0 and not force: return out
    tmp = out + ".part"
    cmd = [sys.executable, "-m", "overturemaps", "download", f"--bbox={bbox[0]:.5f},{bbox[1]:.5f},{bbox[2]:.5f},{bbox[3]:.5f}", "-f", "geojson", "--type=building", "-o", tmp]
    for attempt in range(1, RETRIES + 1):
        t0 = time.time()
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if r.returncode == 0 and os.path.exists(tmp) and os.path.getsize(tmp) > 0:
            os.replace(tmp, out)
            for junk in (tmp + ".state", out + ".state"):
                if os.path.exists(junk): os.remove(junk)
            print(f"  downloaded {slug} in {time.time() - t0:.0f}s ({os.path.getsize(out) / 1e6:.1f} MB)")
            return out
        wait = 10 * attempt
        err = (r.stderr or "").strip()[-300:]
        print(f"  download {slug} attempt {attempt} failed (rc={r.returncode}): {err} - retry in {wait}s")
        time.sleep(wait)
    return None


def pick_name(names):
    """Overture names: primary, with an English 'common' variant preferred when the primary is Arabic-only."""
    if not isinstance(names, dict): return None
    primary = (names.get("primary") or "").strip() or None
    common = names.get("common")
    en = None
    if isinstance(common, dict): en = common.get("en")
    elif isinstance(common, list):
        en = next((c.get("value") for c in common if isinstance(c, dict) and c.get("language") == "en"), None)
    if primary and ARABIC.search(primary) and en: return en.strip()
    return primary or (en.strip() if en else None)


def match(slug, feats, raw_path):
    raw = json.load(open(raw_path, encoding="utf-8"))["features"]
    if not raw: return {}
    ours = gpd.GeoDataFrame({"fi": [i for i, f in enumerate(feats)]}, geometry=[shape(f["geometry"]).buffer(0) for f in feats], crs="EPSG:4326").to_crs(UTM)
    ours = ours[~ours.geometry.is_empty]
    rows = []
    for f in raw:
        p = f.get("properties") or {}
        rows.append({"gers_id": f.get("id") or p.get("id"), "name": pick_name(p.get("names")), "height": p.get("height"), "num_floors": p.get("num_floors"),
                     "facade_color": p.get("facade_color"), "roof_shape": p.get("roof_shape"), "class": p.get("class") or p.get("subtype"),
                     "geometry": shape(f["geometry"]).buffer(0)})
    ov = gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:4326").to_crs(UTM)
    ov = ov[~ov.geometry.is_empty].reset_index(drop=True); ov["oi"] = ov.index
    ov["area"] = ov.geometry.area; ours["area"] = ours.geometry.area
    # candidate pairs: (a) Overture centroid within NEAR_M of our footprint, (b) polygons intersect (overlap tested below)
    cent = ov.set_geometry(ov.geometry.centroid.buffer(NEAR_M))[["oi", "geometry"]]
    a = gpd.sjoin(cent, ours[["fi", "geometry"]], predicate="intersects", how="inner")[["oi", "fi"]]
    b = gpd.sjoin(ov[["oi", "geometry"]], ours[["fi", "geometry"]], predicate="intersects", how="inner")[["oi", "fi"]]
    pairs = pd.concat([a, b]).drop_duplicates()
    if pairs.empty: return {}
    og = ov.geometry.values; oc = ov.geometry.centroid.values; ug = ours.set_index("fi").geometry; ua = ours.set_index("fi")["area"]
    best = {}
    for oi, fi in pairs.itertuples(index=False):
        g_o, g_u = og[oi], ug[fi]
        inter = g_o.intersection(g_u).area if g_o.intersects(g_u) else 0.0
        ratio = inter / max(1e-6, min(ov["area"].iat[oi], ua[fi]))
        dist = oc[oi].distance(g_u)
        if not (dist <= NEAR_M or ratio > OVERLAP): continue
        key = (ratio, -dist)
        if fi not in best or key > best[fi][0]: best[fi] = (key, oi, ratio, dist)
    out = {}
    for fi, (_, oi, ratio, dist) in best.items():
        r = ov.iloc[oi]
        rec = {"name": r["name"] if isinstance(r["name"], str) and r["name"] else None, "height": None if pd.isna(r["height"]) else round(float(r["height"]), 1),
               "num_floors": None if pd.isna(r["num_floors"]) else int(r["num_floors"]), "facade_color": r["facade_color"] if isinstance(r["facade_color"], str) else None,
               "roof_shape": r["roof_shape"] if isinstance(r["roof_shape"], str) else None, "class": r["class"] if isinstance(r["class"], str) else None,
               "source": "overture", "gers_id": r["gers_id"] if isinstance(r["gers_id"], str) else None, "overlap": round(ratio, 2), "dist_m": round(float(dist), 1)}
        if any(rec[k] is not None for k in ("name", "height", "num_floors", "facade_color", "roof_shape", "class")):
            out[str(int(fi))] = rec
    return dict(sorted(out.items(), key=lambda kv: int(kv[0])))


def run(slug, force=False, skip_download=False):
    gj = os.path.join(CE, slug, "buildings.geojson")
    if not os.path.exists(gj): return None
    feats = json.load(open(gj, encoding="utf-8"))["features"]
    raw = os.path.join(RAW, f"{slug}.geojson") if skip_download else download(slug, bbox_of(feats), force=force)
    if not raw or not os.path.exists(raw):
        print(f"  {slug}: no raw Overture file"); return None
    res = match(slug, feats, raw)
    n_raw = len(json.load(open(raw, encoding="utf-8"))["features"])
    json.dump(res, open(os.path.join(OUT, f"overture_{slug}.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=0)
    named = sum(1 for v in res.values() if v["name"]); heights = sum(1 for v in res.values() if v["height"] is not None)
    unnamed_filled = sum(1 for k, v in res.items() if v["name"] and not (feats[int(k)]["properties"].get("name") or "").strip())
    return len(feats), n_raw, len(res), named, unnamed_filled, heights


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    force = "--force" in sys.argv; skip = "--skip-download" in sys.argv
    all_slugs = sorted(os.path.basename(p) for p in glob.glob(os.path.join(CE, "*")) if os.path.isdir(p) and not p.endswith("_glb"))
    slugs = args or [s for s in PRIORITY if s in all_slugs] + [s for s in all_slugs if s not in PRIORITY]
    print(f"{'district':<26} {'bldgs':>6} {'overture':>8} {'matched':>7} {'named':>6} {'new names':>9} {'heights':>7}")
    T = [0] * 6
    for k, s in enumerate(slugs):
        r = run(s, force=force, skip_download=skip)
        if not r: continue
        T = [T[i] + r[i] for i in range(6)]
        print(f"{s:<26} {r[0]:>6} {r[1]:>8} {r[2]:>7} {r[3]:>6} {r[4]:>9} {r[5]:>7}")
        if k < len(slugs) - 1 and not skip: time.sleep(PAUSE_S)
    print(f"{'TOTAL':<26} {T[0]:>6} {T[1]:>8} {T[2]:>7} {T[3]:>6} {T[4]:>9} {T[5]:>7}")
