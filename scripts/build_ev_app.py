"""build_ev_app.py -- data payload for the interactive Azimuth EV map.

The PNG map (render_ev_map.py) cannot be filtered, so the app surface needs its own payload: the
charge points plus the two geographies worth filtering on, and a basemap light enough to inline.

Everything here is computed, never asserted:

  area        point-in-polygon against public/mp_areas.json (39 Dubai community polygons, the same
              geography the board already uses). A point outside all of them gets null, not a guess.
  highway     nearest named motorway from OSM (data/ev/_overpass_highways.json: E11, E311, E66, E44,
              E611, ...) with the distance in metres. The house basemap carries fclass but NO road
              names, so an "E11" filter built from it would have been invented; these refs are real
              OSM refs. Points keep the distance so the UI can threshold it rather than claim
              membership.

The basemap is projected to Web Mercator once here and emitted as rounded SVG-ready coordinates, so
the page needs no projection library, no tiles and no API key -- the same offline, commercial-safe
position as render_heatmap.py.

    python scripts/build_ev_app.py          # -> public/ev_app_data.json
"""
import io, json, math, os, sys

import duckdb
import geopandas as gpd
from shapely.geometry import shape, Point
from shapely.ops import unary_union

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PUB = os.path.join(ROOT, "public")
DB = os.path.join(ROOT, "data", "graph", "najma.duckdb")
GPKG = os.path.join(ROOT, "assets", "dubai_basemap.gpkg")
HWY = os.path.join(ROOT, "data", "ev", "_overpass_highways.json")
AREAS = os.path.join(PUB, "mp_areas.json")
OUT = os.path.join(PUB, "ev_app_data.json")

# Frame: the built-up corridor plus Hatta's approach. Everything outside is still in the payload;
# the page clamps the view rather than dropping points.
LO0, LA0, LO1, LA1 = 54.85, 24.70, 56.20, 25.45
ROAD_KEEP = {"motorway": 0, "trunk": 1, "primary": 2, "secondary": 3}   # class -> weight for the page


def merc(lon, lat):
    x = lon * 20037508.34 / 180.0
    y = math.log(math.tan((90.0 + lat) * math.pi / 360.0)) / (math.pi / 180.0) * 20037508.34 / 180.0
    return x, y


GEOJSON = os.path.join(ROOT, "data", "ev", "ev_charge_points.geojson")


def points():
    """v_ev_charge_points, from DuckDB if it is readable and from the exported GeoJSON if it is not.

    The nightly refresh_runner holds a WRITE lock on najma.duckdb for as long as it runs, and DuckDB
    lets no other process in while it does -- read_only included. build_ev_union.py --export already
    writes the same rows to data/ev/ev_charge_points.geojson, so the app can be rebuilt during a
    refresh instead of waiting it out. The fallback is announced, never silent: rebuilding from an
    export that predates the current union would quietly publish stale counts."""
    try:
        con = duckdb.connect(DB, read_only=True)
        df = con.execute("""select point_id, source, authority, operator, location_name,
                                   location_address, latitude, longitude, totalnbofconnectors,
                                   connectortype, max_power_kw, source_url, archetype
                            from v_ev_charge_points""").fetchdf()
        con.close()
        return df
    except Exception as e:
        if not os.path.exists(GEOJSON):
            raise
        import datetime as _dt
        import pandas as pd
        age = _dt.datetime.fromtimestamp(os.path.getmtime(GEOJSON))
        print(f"NOTE: DuckDB unavailable ({str(e).splitlines()[0][:80]});")
        print(f"      reading the export written {age:%Y-%m-%d %H:%M} instead "
              f"-- re-run build_ev_union.py --export if that is older than your last ingest.")
        fc = json.load(io.open(GEOJSON, encoding="utf-8"))
        rows = []
        for feat in fc["features"]:
            p = dict(feat["properties"])
            lon, lat = feat["geometry"]["coordinates"]
            p["longitude"], p["latitude"] = lon, lat
            rows.append(p)
        return pd.DataFrame(rows)


def load_areas():
    fc = json.load(open(AREAS, encoding="utf-8"))
    out = []
    for f in fc["features"]:
        try: out.append((f["properties"]["n"].title(), shape(f["geometry"])))
        except Exception: pass
    return out


def load_highways():
    """OSM ways -> one merged geometry per ref, in metres-ish projection for distance."""
    j = json.load(open(HWY, encoding="utf-8"))
    byref = {}
    for e in j.get("elements", []):
        ref = (e.get("tags") or {}).get("ref")
        geom = e.get("geometry") or []
        if not ref or len(geom) < 2: continue
        ref = ref.split(";")[0].strip()              # "E11;S113" -> E11
        byref.setdefault(ref, []).append([(p["lon"], p["lat"]) for p in geom])
    from shapely.geometry import LineString
    out = {}
    for ref, lines in byref.items():
        if len(lines) < 5: continue                  # ignore stubs; a 2-way "ref" is not a corridor
        out[ref] = unary_union([LineString(l) for l in lines])
    return out


def nearest_highway(pt, hwys):
    """Degrees -> metres with the house cosine correction. Good to tens of metres at this latitude."""
    best, bestd = None, None
    kx = 111320.0 * math.cos(math.radians(pt.y))
    for ref, geom in hwys.items():
        d = geom.distance(pt)                        # degrees
        # crude but consistent: scale the degree distance by the local metre-per-degree average
        m = d * ((111320.0 + kx) / 2.0)
        if bestd is None or m < bestd:
            best, bestd = ref, m
    return best, (round(bestd) if bestd is not None else None)


def basemap():
    layers = {}
    for name in ("roads", "water"):
        try: g = gpd.read_file(GPKG, layer=name)
        except Exception as e:
            print(f"WARNING: basemap layer {name} unavailable ({e})"); continue
        g = g.cx[LO0:LO1, LA0:LA1]
        feats = []
        for _, row in g.iterrows():
            if name == "roads":
                fc = str(row.get("fclass") or "")
                key = next((k for k in ROAD_KEEP if fc.startswith(k)), None)
                if key is None: continue
                w = ROAD_KEEP[key]
                tol = 0.0006 if w >= 2 else 0.0003
            else:
                w, tol = 0, 0.0004
            geom = row.geometry
            if geom is None or geom.is_empty: continue
            geom = geom.simplify(tol, preserve_topology=False)
            parts = list(geom.geoms) if geom.geom_type.startswith("Multi") else [geom]
            for p in parts:
                if p.is_empty: continue
                coords = list(p.exterior.coords) if p.geom_type == "Polygon" else list(p.coords)
                if len(coords) < 2: continue
                xy = []
                for lon, lat in coords:
                    x, y = merc(lon, lat)
                    xy.append([round(x, 1), round(y, 1)])
                feats.append({"w": w, "xy": xy})
        layers[name] = feats
        print(f"  basemap {name}: {len(feats)} shapes")
    return layers


def main():
    df = points()
    areas = load_areas()
    hwys = load_highways()
    print(f"{len(df)} points · {len(areas)} area polygons · {len(hwys)} highway refs: "
          f"{', '.join(sorted(hwys)[:10])}")

    # pandas hands back float('nan') for a missing string, and NaN is TRUTHY -- `x or "Unknown"`
    # keeps the NaN and json.dump writes a bare NaN, which is not valid JSON and killed the page.
    def num(v, cast):
        """None (GeoJSON) and NaN (DuckDB) both mean not recorded; anything else casts."""
        if v is None: return None
        if isinstance(v, float) and v != v: return None
        try: return cast(v)
        except (TypeError, ValueError): return None

    def s(v, default=None):
        if v is None: return default
        if isinstance(v, float) and v != v: return default
        v = str(v).strip()
        return v if v else default

    out_pts, n_area, n_hwy = [], 0, 0
    for r in df.to_dict("records"):
        lon, lat = float(r["longitude"]), float(r["latitude"])
        p = Point(lon, lat)
        area = next((nm for nm, poly in areas if poly.contains(p)), None)
        if area: n_area += 1
        ref, dist = nearest_highway(p, hwys) if hwys else (None, None)
        if ref is not None: n_hwy += 1
        x, y = merc(lon, lat)
        kw = r["max_power_kw"]
        out_pts.append({
            "id": s(r["point_id"]),
            "n": s(r["location_name"], "Unnamed site"),
            "ad": s(r["location_address"], ""),
            "op": s(r["operator"], "Unknown"),
            "src": s(r["source"]), "auth": s(r["authority"]), "arch": s(r["archetype"]),
            # null means "not recorded" (21 OSM rows), never "no connectors" -- DuckDB hands that back
            # as NaN and the GeoJSON path as None, so both have to be caught here.
            "c": num(r["totalnbofconnectors"], int),
            "kw": num(kw, float),
            "ct": s(r["connectortype"], ""),
            "url": s(r["source_url"]),
            "area": area, "hwy": ref, "hwyd": dist,
            "x": round(x, 1), "y": round(y, 1), "lon": lon, "lat": lat,
        })

    bx0, by0 = merc(LO0, LA0)
    bx1, by1 = merc(LO1, LA1)
    payload = {
        "bounds": [round(bx0, 1), round(by0, 1), round(bx1, 1), round(by1, 1)],
        "points": out_pts,
        "areas": sorted({p["area"] for p in out_pts if p["area"]}),
        "highways": sorted(hwys),
        "basemap": basemap(),
        "meta": {
            "total": len(out_pts),
            "connectors": int(sum(p["c"] for p in out_pts if p["c"] is not None)),
            "connectors_unrecorded": sum(1 for p in out_pts if p["c"] is None),
            "register": sum(1 for p in out_pts if p["auth"] == "register"),
            "community": sum(1 for p in out_pts if p["auth"] == "community"),
            "dewa_published": 2223,
            "dewa_published_note": "DEWA to WAM, 23 June 2026: \"Dubai has 2,223 EV charging stations\"",
            "dewa_published_date": "2026-06-23",
            "dewa_published_unit": "stations",
            "dewa_published_source": "https://www.wam.ae/en/article/c0vc4u3-dewa’s-green-charger-initiative-supplied-over",
        },
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(payload, f, separators=(",", ":"))
    mb = os.path.getsize(OUT) / 1e6
    print(f"wrote {OUT} ({mb:.2f} MB) · {n_area} points placed in an area · {n_hwy} matched to a highway")
    standalone(payload)


def standalone(payload):
    """One self-contained file: the page with its data inlined, for publishing or emailing.

    public/ev_app.html fetches ev_app_data.json when served from a directory; that fetch cannot work
    from a file:// open or a single-file host, so the same page is emitted with the payload in an
    inline <script type="application/json"> block, which it prefers when present."""
    src = os.path.join(PUB, "ev_app.html")
    if not os.path.exists(src):
        print("  (no ev_app.html yet; skipping standalone)"); return
    html = open(src, encoding="utf-8").read()
    blob = json.dumps(payload, separators=(",", ":")).replace("</", "<\\/")
    tag = '<script id="ev-data" type="application/json">' + blob + "</script>"
    marker = "<script>\n(function(){"
    if marker not in html:
        print("  WARNING: could not find the script marker; standalone not written"); return
    html = html.replace(marker, tag + "\n" + marker, 1)
    dst = os.path.join(PUB, "ev_app_standalone.html")
    with open(dst, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"wrote {dst} ({os.path.getsize(dst)/1e6:.2f} MB, self-contained)")


if __name__ == "__main__":
    main()
