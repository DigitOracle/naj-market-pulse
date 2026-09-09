"""Dubai Municipality building entrances (GIS Net KML, Makani points) -> a flat table, then per-district subsets in scene metres.

Each Placemark is one entrance: a 10-digit MAKANI number, the PARCEL identifier (community x 10000 + plot, the same key the Land
Department uses), street number and name, building/unit hints, DLTM coordinates and a lon/lat point. This is the geometry the
register lacks: parcel -> point. Streams the 256 MB file, never loads it whole.

Output data/dm/entrances.csv                     all entrances (lon, lat, makani, parcel_id, community_no, plot, street, building ...)
       data/dm/entrances_<slug>.json             entrances inside each modelled district's footprint bbox, with scene x/z (UTM 40N: x=E, z=-N)
Usage: python scripts/dm_entrances.py [path/to/entrances.kml]
"""
import csv, glob, json, os, re, sys, time, collections
import pyproj
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, ".."))
OUT = os.path.join(ROOT, "data", "dm"); os.makedirs(OUT, exist_ok=True)
CE = os.path.join(ROOT, "data", "ce")
TO_UTM = pyproj.Transformer.from_crs("EPSG:4326", "EPSG:32640", always_xy=True).transform
KML = sys.argv[1] if len(sys.argv) > 1 else sorted(glob.glob(r"C:\Dev\naj-market-pulse\data\raw_downloads\entrances_*.kml"))[-1]
ROW = re.compile(r"<td>([^<]*)</td>\s*<td>([^<]*)</td>", re.S)
COORD = re.compile(r"<coordinates>\s*([-0-9.]+),([-0-9.]+)", re.S)


def district_bboxes():
    out = {}
    for d in sorted(os.listdir(CE)):
        gj = os.path.join(CE, d, "buildings.geojson")
        if not os.path.exists(gj): continue
        xs, ys = [], []
        def walk(c):
            if isinstance(c[0], (int, float)): xs.append(c[0]); ys.append(c[1])
            else:
                for k in c: walk(k)
        for f in json.load(open(gj, encoding="utf-8"))["features"]: walk(f["geometry"]["coordinates"])
        if xs: out[d] = (min(xs) - 0.002, min(ys) - 0.002, max(xs) + 0.002, max(ys) + 0.002)
    return out


def main():
    t = time.time(); bb = district_bboxes(); per = {d: [] for d in bb}
    keys = collections.Counter(); n = 0; truncated = False
    csvf = open(os.path.join(OUT, "entrances.csv"), "w", newline="", encoding="utf-8"); w = None
    buf = ""; size = os.path.getsize(KML)
    with open(KML, encoding="utf-8", errors="ignore") as fh:
        while True:
            chunk = fh.read(8 * 1024 * 1024)
            if not chunk: break
            buf += chunk
            while True:
                a = buf.find("<Placemark"); b = buf.find("</Placemark>", a) if a >= 0 else -1
                if a < 0 or b < 0: break
                pm = buf[a:b]; buf = buf[b + 12:]
                attrs = {k.strip(): v.strip() for k, v in ROW.findall(pm)}
                m = COORD.search(pm)
                if not m: continue
                lon, lat = float(m.group(1)), float(m.group(2))
                for k in attrs: keys[k] += 1
                rec = {"lon": lon, "lat": lat}; rec.update(attrs); n += 1
                if w is None:
                    cols = ["lon", "lat"] + sorted(attrs.keys()); w = csv.DictWriter(csvf, fieldnames=cols, extrasaction="ignore"); w.writeheader()
                w.writerow(rec)
                for d, (x0, y0, x1, y1) in bb.items():
                    if x0 <= lon <= x1 and y0 <= lat <= y1:
                        e, nn = TO_UTM(lon, lat); per[d].append(dict(rec, x=round(e, 1), z=round(-nn, 1)))
            if len(buf) > 50_000_000: buf = buf[-20_000_000:]      # a broken placemark should not pin memory
    truncated = "</kml>" not in buf[-2000:]
    csvf.close()
    print(f"entrances parsed: {n:,} from {size/1048576:.0f} MB in {time.time()-t:.0f}s | file {'TRUNCATED (export cap)' if truncated else 'complete'}")
    print("attributes:", [k for k, _ in keys.most_common(30)])
    for d, rows in per.items():
        json.dump({"district": d, "source": "Dubai Municipality GIS Net entrances (Makani), KML export", "n": len(rows), "entrances": rows}, open(os.path.join(OUT, f"entrances_{d}.json"), "w", encoding="utf-8"), ensure_ascii=False)
        pk = collections.Counter(r.get("PARCEL") or r.get("PARCELID") or r.get("PARCEL_ID") for r in rows)
        print(f"  {d:<24} entrances {len(rows):>6} | distinct parcels {len(pk):>5}")


if __name__ == "__main__":
    main()
