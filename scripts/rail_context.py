"""Rail for the twin: Dubai Metro (Red, Green, Route 2020, Blue Line works), Palm Monorail, tram, Etihad Rail - as a
3D context layer per district, in the same scene frame as ctx.json / ground_imagery.json (x = easting, z = -northing,
absolute EPSG:32640 metres).

Source: OpenStreetMap, fetched ONCE for the emirate and cached (data/names/rail_raw.json); each district clips its own
window. Nothing is drawn from press releases - what OpenStreetMap tags as built, construction or proposed is what shows.

Profile (heights are NOT tagged in OpenStreetMap - these are standard figures, illustrative like unknown building heights):
    viaduct   metro on `bridge=yes` / `layer>=1`, and every metro segment not tagged tunnel (Dubai Metro is elevated)   deck 13 m
    tunnel    `tunnel=yes` or `layer<0`                                                                                 not drawn
    grade     heavy rail on the ground (Etihad Rail)                                                                    ballast 0.6 m
    bridge    heavy rail on `bridge=yes`                                                                                deck 8 m
Stations: `railway=station` nodes, named from name:en; they sit on the nearest line and inherit its deck height.

Output data/ce/<slug>/rail.json
    {district, lines:[{net, prof, h, w, pts:[[x,z],...]}], stations:[{name, net, x, z, h, brg}], note}
pushed as KV rail_<slug> (viewer fetches /img/rail_<slug>).

Usage: python scripts/rail_context.py [slug ...] [--dry] [--force]      (no slugs = every district with a ctx.json)
"""
import json, math, os, re, sys, time, urllib.parse, urllib.request
from shapely.geometry import LineString, Point, box
from shapely.ops import transform as shp_transform
import pyproj

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
CE = os.path.join(ROOT, "data", "ce"); RAW = os.path.join(ROOT, "data", "names", "rail_raw.json")
BBOX = "24.70,54.80,25.45,55.70"                                             # the emirate, generously
MIRRORS = ["https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter", "https://overpass.private.coffee/api/interpreter"]
TO_UTM = pyproj.Transformer.from_crs("EPSG:4326", "EPSG:32640", always_xy=True).transform
Q = f"""[out:json][timeout:180];
( way["railway"~"^(subway|light_rail|monorail|tram|rail|construction|proposed)$"]({BBOX}); );
out geom;
( node["railway"="station"]({BBOX}); node["public_transport"="station"]["station"~"^(subway|monorail|light_rail)$"]({BBOX}); );
out;
( relation["route"~"^(subway|light_rail|monorail|tram|train)$"]({BBOX}); );
out body;"""

DECK = {"viaduct": 13.0, "bridge": 8.0, "grade": 0.6}
WIDTH = {"metro": 9.0, "monorail": 4.0, "tram": 7.0, "trolley": 5.0, "apm": 5.0, "etihad": 11.0, "rail": 9.0}


def fetch(force=False):
    if os.path.exists(RAW) and not force and time.time() - os.path.getmtime(RAW) < 30 * 86400:
        return json.load(open(RAW, encoding="utf-8"))
    last = None
    for host in MIRRORS:
        for attempt in range(2):
            try:
                r = urllib.request.urlopen(urllib.request.Request(host, data=urllib.parse.urlencode({"data": Q}).encode(),
                                                                  headers={"User-Agent": "najma-market-pulse/1.0 (rail context)"}), timeout=240)
                J = json.load(r); os.makedirs(os.path.dirname(RAW), exist_ok=True)
                json.dump(J, open(RAW, "w", encoding="utf-8")); print(f"  rail fetched from {host.split('/')[2]}: {len(J.get('elements', []))} elements")
                return J
            except Exception as e:
                last = e; time.sleep(8)
    sys.exit(f"Overpass unavailable: {str(last)[:80]}")


def net_of(tags, routes):
    """Which network a way belongs to; the route relation is the authority, the way's own tags the fallback."""
    rw = tags.get("railway"); cons = tags.get("construction") or tags.get("proposed") or ""
    op = (tags.get("operator") or "") + " " + (tags.get("network") or "") + " " + (tags.get("name") or "") + " " + " ".join(routes)
    opl = op.lower()
    if "etihad" in opl or "الاتحاد" in op or "اتحاد" in op:
        return "etihad_construction" if rw in ("construction", "proposed") else "etihad"
    if "apm" in opl.split() or "people mover" in opl or "terminal 3 apm" in opl or "terminal 1 apm" in opl: return "apm"
    if "trolley" in opl: return "trolley"
    if rw == "monorail" or cons == "monorail" or "monorail" in opl: return "monorail"
    if rw == "tram" or cons == "tram" or "tram" in opl: return "tram"
    if rw in ("subway", "light_rail") or cons in ("subway", "light_rail"):
        if rw in ("construction", "proposed") or "blue" in opl: return "metro_blue"
        # the Route 2020 branch is signed as part of the Red Line: a way whose route names ALL say 2020/Expo is the branch,
        # a way that is also on a plain Red Line route is the trunk (JLT, Marina, Business Bay sit on the trunk)
        rn = [n.lower() for n in routes] or [opl]
        red = [n for n in rn if "red" in n]; br = [n for n in rn if "2020" in n or "expo" in n]
        if red and any(n not in br for n in red): return "metro_red"
        if br: return "metro_2020"
        if any("green" in n for n in rn): return "metro_green"
        return "metro_red"
    if rw == "rail": return "rail"
    return None                                                    # other construction / proposed we do not draw


def prof_of(tags, net):
    lay = tags.get("layer")
    try: lay = int(lay)
    except Exception: lay = None
    if tags.get("tunnel") in ("yes", "building_passage") or (lay is not None and lay < 0): return "tunnel"
    if tags.get("bridge") or (lay is not None and lay >= 1): return "viaduct" if net.startswith("metro") or net in ("monorail",) else "bridge"
    if net.startswith("metro") or net in ("monorail", "apm"): return "viaduct"       # Dubai Metro and the Palm Monorail are elevated unless tunnelled
    return "grade"


def build(J):
    routes_by_way = {}
    for e in J["elements"]:
        if e["type"] != "relation": continue
        nm = (e.get("tags") or {}).get("name") or (e.get("tags") or {}).get("ref") or ""
        for m in e.get("members", []):
            if m.get("type") == "way": routes_by_way.setdefault(m["ref"], []).append(nm)
    lines, stations = [], []
    for e in J["elements"]:
        t = e.get("tags") or {}
        if e["type"] == "way" and e.get("geometry"):
            net = net_of(t, routes_by_way.get(e["id"], []))
            if not net: continue
            prof = prof_of(t, net)
            if prof == "tunnel": continue
            ls = shp_transform(TO_UTM, LineString([(p["lon"], p["lat"]) for p in e["geometry"]]))
            fam = "metro" if net.startswith("metro") else net if net in ("monorail", "tram", "trolley", "apm") else "etihad" if net.startswith("etihad") else "rail"
            lines.append({"net": net, "prof": prof, "h": DECK[prof], "w": WIDTH[fam], "geom": ls, "osm": e["id"]})
        elif e["type"] == "node":
            nm = t.get("name:en") or t.get("name") or ""
            if not nm or not re.search(r"[A-Za-z]", nm): continue
            if not (t.get("station") or t.get("network") or t.get("operator")): continue            # a bare railway=station pin with no network is noise (a pharmacy got in)
            if re.search(r"pharmacy|clinic|cafe|restaurant|shop|market|bank", nm, re.I): continue
            st = t.get("station") or ("rail" if t.get("railway") == "station" else "")
            stations.append({"name": nm, "kind": st, "pt": shp_transform(TO_UTM, Point(e["lon"], e["lat"]))})
    return lines, stations


AGOL = [("1ff39034c0574693aab34018744fd318", "Dubai Metro and Tram Stations 2018 (NYU, ArcGIS Online)", "station_na", "line"),
        ("29463fa0d4d24243a3644314a9ed1ad4", "Dubai Metro Stations 2023 (ArcGIS Online)", "Station_Name", "Line")]
AGOL_RAW = os.path.join(ROOT, "data", "names", "rail_agol_stations.json")


def agol_stations():
    """Station points from public ArcGIS Online feature layers - a second, independent source. Cached; failures are non-fatal."""
    if os.path.exists(AGOL_RAW) and time.time() - os.path.getmtime(AGOL_RAW) < 30 * 86400:
        return json.load(open(AGOL_RAW, encoding="utf-8"))
    out = []
    for iid, label, fname, fline in AGOL:
        try:
            it = json.load(urllib.request.urlopen(urllib.request.Request(f"https://www.arcgis.com/sharing/rest/content/items/{iid}?f=json", headers={"User-Agent": "najma-market-pulse/1.0"}), timeout=60))
            url = it.get("url")
            if not url: continue
            q = url + "/0/query?" + urllib.parse.urlencode({"where": "1=1", "outFields": "*", "outSR": 4326, "f": "geojson", "resultRecordCount": 500})
            G = json.load(urllib.request.urlopen(urllib.request.Request(q, headers={"User-Agent": "najma-market-pulse/1.0"}), timeout=90))
            for f in G.get("features", []):
                pr = f.get("properties") or {}; g = f.get("geometry") or {}
                if g.get("type") != "Point" or not pr.get(fname): continue
                out.append({"name": str(pr[fname]).strip(), "line": str(pr.get(fline) or "").strip(), "lon": g["coordinates"][0], "lat": g["coordinates"][1], "source": label})
            print(f"  ArcGIS Online: {label} -> {len(G.get('features', []))} stations")
        except Exception as e:
            print(f"  ArcGIS Online {label[:30]} unavailable: {str(e)[:60]}")
    json.dump(out, open(AGOL_RAW, "w", encoding="utf-8"), ensure_ascii=False)
    return out


def merge_stations(stations, agol):
    """OSM stations are kept; an ArcGIS station within 150 m confirms one (adds its line as evidence), one farther than 150 m from
    every OSM station is ADDED (source = the layer). So the twin shows the union, and each station says where it came from."""
    for s in stations: s["src"] = "OpenStreetMap"; s["confirm"] = 0
    added = 0
    for a in agol:
        pt = shp_transform(TO_UTM, Point(a["lon"], a["lat"]))
        near = [s for s in stations if s["pt"].distance(pt) < 150]
        if near:
            for s in near: s["confirm"] += 1; s.setdefault("agol_line", a["line"])
        else:
            stations.append({"name": a["name"], "kind": "subway", "pt": pt, "src": a["source"], "confirm": 0, "agol_line": a["line"]}); added += 1
    print(f"  stations: {len(stations)} after merge ({added} added from ArcGIS Online, {sum(1 for s in stations if s['confirm'])} confirmed by it)")
    return stations


def window(slug):
    gi = os.path.join(CE, slug, "ground_imagery.json")
    if os.path.exists(gi):
        g = json.load(open(gi)); return box(g["xmin"], g["ymin"], g["xmax"], g["ymax"])      # EPSG:32640 metres, already padded
    gj = os.path.join(CE, slug, "buildings.geojson")
    J = json.load(open(gj, encoding="utf-8"))
    xs, ys = [], []
    for f in J["features"]:
        for ring in (f["geometry"]["coordinates"] if f["geometry"]["type"] == "Polygon" else [r for pg in f["geometry"]["coordinates"] for r in pg]):
            for c in ring:
                x, y = TO_UTM(c[0], c[1]); xs.append(x); ys.append(y)
    return box(min(xs) - 300, min(ys) - 300, max(xs) + 300, max(ys) + 300)


def clip(slug, lines, stations):
    win = window(slug); out_l, out_s = [], []
    for L in lines:
        g = L["geom"].intersection(win)
        if g.is_empty: continue
        for part in getattr(g, "geoms", [g]):
            if part.geom_type != "LineString" or part.length < 5: continue
            pts = [[round(x, 1), round(-y, 1)] for x, y in part.simplify(0.5).coords]        # scene: x = easting, z = -northing
            out_l.append({"net": L["net"], "prof": L["prof"], "h": L["h"], "w": L["w"], "pts": pts})
    for S in stations:
        if not win.buffer(60).contains(S["pt"]): continue
        best, bd = None, 1e9
        for L in lines:
            d = L["geom"].distance(S["pt"])
            if d < bd: bd, best = d, L
        if best is None or bd > 120: continue
        # bearing of the line at the station, so the platform box lies along the track
        p0 = best["geom"].interpolate(max(0.0, best["geom"].project(S["pt"]) - 40)); p1 = best["geom"].interpolate(min(best["geom"].length, best["geom"].project(S["pt"]) + 40))
        brg = math.degrees(math.atan2(-(p1.y - p0.y), p1.x - p0.x))                              # scene-plane angle (x east, z south)
        on = best["geom"].interpolate(best["geom"].project(S["pt"]))
        out_s.append({"name": S["name"], "net": best["net"], "x": round(on.x, 1), "z": round(-on.y, 1), "h": best["h"], "brg": round(brg, 1),
                      "src": S.get("src", "OpenStreetMap"), "confirmed": bool(S.get("confirm"))})
    return out_l, out_s


def main():
    slugs = [a for a in sys.argv[1:] if not a.startswith("--")]; dry = "--dry" in sys.argv
    if not slugs: slugs = sorted(d for d in os.listdir(CE) if os.path.exists(os.path.join(CE, d, "ctx.json")))
    J = fetch("--force" in sys.argv)
    lines, stations = build(J)
    stations = merge_stations(stations, agol_stations())
    from collections import Counter
    print(f"emirate: {len(lines)} drawable segments {dict(Counter(l['net'] for l in lines))} | {len(stations)} named stations")
    tok = None
    if not dry:
        from build_avail_index import env_token, push
        tok = env_token("INGEST_TOKEN")
    for s in slugs:
        try: L, S = clip(s, lines, stations)
        except Exception as e: print(f"  {s:<24} skipped: {str(e)[:70]}"); continue
        doc = {"district": s, "lines": L, "stations": S, "frame": "EPSG:32640, x = easting, z = -northing",
               "sources": ["OpenStreetMap (track, stations, construction status)", "ArcGIS Online station layers (NYU 2018, 2023) - cross-check and fill", "Esri World Imagery (ground), SRTM (terrain) already under the model"],
               "note": "Deck heights are standard figures (viaduct 13 m, rail bridge 8 m), not measured; tunnels are not drawn. Each station names its source and whether a second source confirms it."}
        os.makedirs(os.path.join(CE, s), exist_ok=True)
        json.dump(doc, open(os.path.join(CE, s, "rail.json"), "w", encoding="utf-8"), separators=(",", ":"), ensure_ascii=False)
        nets = dict(Counter(l["net"] for l in L)); names = ", ".join(x["name"] for x in S[:4])
        ok = "" if dry else (" -> pushed" if push("rail_" + s, doc, tok).get("ok") else " -> PUSH FAILED")
        print(f"  {s:<24} {len(L):>3} segments {nets} | {len(S)} stations {names}{ok}")


if __name__ == "__main__":
    main()
