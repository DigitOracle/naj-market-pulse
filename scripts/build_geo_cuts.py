"""build_geo_cuts.py -- the coordinates we already had and had not looked inside.

The DDA API carries no geometry (checked, 21 Sep 2026: every RTA GIS dataset 404s on PROD and nothing else holds a coordinate).
The PORTAL extracts do: data/raw_downloads/dd/*.kml, pulled 9 Sep 2026, hold community and sector POLYGONS, the full Makani
entrance layer, and every RTA point layer with lon/lat. This turns them into what the building page can read.

  communities.geojson      every DM community as a polygon, carrying comm_num - so a footprint is placed in its community by
                           POINT-IN-POLYGON instead of by matching a district name. The resident mix is keyed on comm_num, and
                           name matching was giving a building at the canal the same mix as one against the Burj Khalifa line.
  transit_<slug>.json      per district: metro/tram/marine stations, bus stops and Salik gates INSIDE the community polygon,
                           plus the nearest of each kind anywhere in Dubai with its straight-line distance, because most
                           districts contain no rail at all and "nearest" is the useful number either way.

    python scripts/build_geo_cuts.py                 # communities.geojson + transit for every district
    python scripts/build_geo_cuts.py --only communities

KML attributes live in two shapes in these files: ExtendedData/SchemaData/SimpleData, and an HTML table inside the description
CDATA. Both are read, because the community layer uses the first and the entrance layer only the second.
"""
import argparse, collections, html, io, json, math, os, re, sys, xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from lake import connect  # noqa: E402

ROOT = os.path.abspath(os.path.join(HERE, ".."))
BOARD = os.path.join(ROOT, "data", "board")
DD = os.path.join(ROOT, "data", "raw_downloads", "dd")
K = "{http://www.opengis.net/kml/2.2}"
DUBAI = (24.6, 25.6, 54.8, 56.1)                      # lat lo/hi, lon lo/hi - anything outside is not a Dubai coordinate
# the point layers worth putting on a building page, and what to call each on screen
POINTS = [("bus_stops_gis", "bus stop", ("STOPS_NAME_EN", "SHORT_NAME"), ("FAREZONE_resolved", "FAREZONE")),
          ("tram_stations_gis", "tram station", ("STATION_NAME_EN",), ()),
          ("marine_stations_gis", "marine station", ("STATION_NAME_EN", "NAME_EN", "STATION_NAME"), ()),
          ("salik_tolling_gates_location", "salik gate", ("GATE_NAME_EN", "NAME_EN", "TOLL_GATE_NAME"), ()),
          ("rta_customer_service_centers", "RTA service centre", ("NAME_EN", "CENTER_NAME_EN"), ())]


def kml_file(stem):
    hit = [f for f in os.listdir(DD) if f.startswith(stem) and f.endswith(".kml")]
    return os.path.join(DD, sorted(hit)[-1]) if hit else None


def attrs_from_description(desc):
    """The portal writes attributes as an HTML table inside the description CDATA: <th>KEY</th><td>VALUE</td> or two <td>s."""
    if not desc:
        return {}
    txt = html.unescape(desc)
    out = {}
    for k, v in re.findall(r"<t[hd][^>]*>\s*([^<>]{1,40}?)\s*</t[hd]>\s*<td[^>]*>\s*([^<>]{0,120}?)\s*</td>", txt, re.I):
        k = k.strip()
        if k and k.lower() not in ("attributes",):
            out[k] = None if v in ("<Null>", "") else v
    return out


def placemarks(path):
    """Stream one KML, yielding (attributes, geometry-kind, coordinate list). iterparse keeps the 268 MB entrance layer flat."""
    for _, el in ET.iterparse(path, events=("end",)):
        if el.tag != K + "Placemark":
            continue
        at = {}
        for sd in el.iter(K + "SimpleData"):
            at[sd.get("name")] = (sd.text or "").strip() or None
        d = el.find(K + "description")
        if d is not None and d.text:
            at.update({k: v for k, v in attrs_from_description(d.text).items() if k not in at or at[k] is None})
        kind, coords = None, []
        for tag, k2 in ((K + "Point", "point"), (K + "LineString", "line"), (K + "Polygon", "polygon")):
            g = el.find(".//" + tag)
            if g is None:
                continue
            kind = k2
            for c in g.iter(K + "coordinates"):
                ring = []
                for tok in (c.text or "").split():
                    p = tok.split(",")
                    if len(p) >= 2:
                        try: ring.append((float(p[0]), float(p[1])))
                        except ValueError: pass
                if ring:
                    coords.append(ring)
            break
        if kind:
            yield at, kind, coords
        el.clear()


def in_dubai(lon, lat):
    return DUBAI[0] <= lat <= DUBAI[1] and DUBAI[2] <= lon <= DUBAI[3]


def km(a, b):
    """Straight-line km between (lon, lat) pairs, with longitude scaled for this latitude."""
    return 111.2 * math.sqrt((a[1] - b[1]) ** 2 + ((a[0] - b[0]) * 0.906) ** 2)


def inside(pt, rings):
    """Ray casting against a polygon's outer ring(s). Holes are rare in this layer and are ignored deliberately."""
    x, y = pt
    hit = False
    for ring in rings:
        for i in range(len(ring)):
            x1, y1 = ring[i]
            x2, y2 = ring[(i + 1) % len(ring)]
            if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / ((y2 - y1) or 1e-12) + x1:
                hit = not hit
    return hit


def build_communities():
    p = kml_file("community__")
    feats, seen = [], set()
    for at, kind, coords in placemarks(p):
        if kind != "polygon" or not coords:
            continue
        num = at.get("COMM_NUM") or (at.get("COMMUNITY_E") or "").rsplit("-", 1)[-1].strip()
        try: num = int(float(num))
        except Exception: num = None
        name = (at.get("CNAME_E") or at.get("LABEL_E") or "").strip() or None
        ring = [r for r in coords if len(r) >= 4 and all(in_dubai(*q) for q in r[:3])]
        if not ring:
            continue
        feats.append({"type": "Feature",
                      "properties": {"comm_num": num, "name_en": name, "name_ar": (at.get("CNAME_A") or "").strip() or None},
                      "geometry": {"type": "Polygon", "coordinates": [[[round(x, 6), round(y, 6)] for x, y in r] for r in ring]}})
        if num: seen.add(num)
    doc = {"type": "FeatureCollection",
           "note": "DM community boundaries from the portal KML (9 Sep 2026). comm_num is the key the resident mix is keyed on; "
                   "place a building by point-in-polygon rather than by matching a district name.",
           "features": feats}
    out = os.path.join(BOARD, "communities.geojson")
    tmp = out + ".tmp"
    json.dump(doc, io.open(tmp, "w", encoding="utf-8"), ensure_ascii=False)
    os.replace(tmp, out)
    print("communities.geojson: %d polygons, %d distinct comm_num -> %s" % (len(feats), len(seen), os.path.relpath(out, ROOT)))
    return feats


def load_points():
    """Every point layer once, as (kind, name, extra, lon, lat)."""
    out = []
    for stem, kind, name_keys, extra_keys in POINTS:
        p = kml_file(stem)
        if not p:
            print("   (no file for %s)" % stem); continue
        n = 0
        for at, k2, coords in placemarks(p):
            if k2 != "point" or not coords or not coords[0]:
                continue
            lon, lat = coords[0][0]
            if not in_dubai(lon, lat):
                continue
            name = next((at[k] for k in name_keys if at.get(k)), None)
            extra = next((at[k] for k in extra_keys if at.get(k)), None)
            out.append((kind, name, extra, lon, lat)); n += 1
        print("   %-28s %6d points" % (kind, n))
    return out


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--only", default=""); a = ap.parse_args()
    only = set(a.only.split(",")) if a.only else None
    os.makedirs(BOARD, exist_ok=True)
    feats = build_communities()
    if only and "communities" in only and "transit" not in only:
        return
    print("point layers:")
    pts = load_points()
    con = connect()
    for lid, name, mode, lon, lat in con.execute("select location_id, name_en, mode, lon, lat from lk_d_station where lat is not null").fetchall():
        pts.append(("%s station" % mode, name, None, lon, lat))
    print("   %-28s %6d points" % ("metro/rail (station spine)", sum(1 for p in pts if p[0].endswith("station") and "tram" not in p[0] and "marine" not in p[0])))
    import build_district_cuts as bdc
    poly = {}
    for f in feats:
        if f["properties"]["comm_num"]:
            poly.setdefault(f["properties"]["comm_num"], []).extend(f["geometry"]["coordinates"])
    for d in bdc.districts():
        if not d["comm"]:
            continue
        rings = poly.get(d["comm"]) or []
        c = con.execute("select avg(lat), avg(lon) from lk_makani_entrances where comm_num = ?", [d["comm"]]).fetchone()
        centre = (c[1], c[0]) if c and c[0] else None
        inside_pts, nearest = collections.defaultdict(list), {}
        for kind, name, extra, lon, lat in pts:
            if rings and inside((lon, lat), rings):
                inside_pts[kind].append({"name": name, "detail": extra, "lon": round(lon, 6), "lat": round(lat, 6)})
            if centre:
                dkm = km((lon, lat), centre)
                if kind not in nearest or dkm < nearest[kind]["km"]:
                    nearest[kind] = {"name": name, "detail": extra, "lon": round(lon, 6), "lat": round(lat, 6), "km": round(dkm, 2)}
        doc = {"area": d["area"], "comm_num": d["comm"], "centre": {"lon": centre[0], "lat": centre[1]} if centre else None,
               "inside": {k: v for k, v in sorted(inside_pts.items())},
               "nearest_anywhere": nearest,
               "note": "Points are RTA/DM portal layers (9 Sep 2026) plus the metro and rail station spine. 'inside' is "
                       "point-in-polygon against the DM community boundary; 'nearest_anywhere' is measured from the community "
                       "centre, so recompute it from a building's own anchor for a per-building distance."}
        tmp = os.path.join(BOARD, "transit_%s.json" % d["slug"])
        json.dump(doc, io.open(tmp + ".tmp", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        os.replace(tmp + ".tmp", tmp)
        for al, real in bdc.ALIAS.items():
            if d["slug"] == al:
                json.dump(doc, io.open(os.path.join(BOARD, "transit_%s.json" % real), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print("transit %-26s inside: %s" % (d["slug"], {k: len(v) for k, v in inside_pts.items()} or "none"))


if __name__ == "__main__":
    main()
