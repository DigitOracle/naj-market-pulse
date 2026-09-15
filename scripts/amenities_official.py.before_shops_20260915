"""The amenity layer from the official registers (Kendall, 7 Sep: "do you have a list of every single hospital in Dubai? if you
don't, then this doesn't work").

Overture's crowd-sourced places were never going to be complete. This rebuilds the layer from the registers that are:
  school    KHDA school_search               every private school in Dubai, precise lat/long, inspection rating, curriculum
            ESE  GetSchoolMaps (apigateway.ese.gov.ae)   every government school and kindergarten, Dubai zone, precise lat/long
  hospital  DHA  sheryan_facility_detail     every licensed facility; hospital = licence subcategory says Hospital (not a pharmacy)
  clinic    DHA  sheryan_facility_detail     polyclinics, general / specialty / dental clinics, day surgery, diagnostic centres
  metro     RTA  metro_stations + tram_stations   every station, precise
  park      DM major parks + OpenStreetMap named parks (185)            - no complete official parks list is published
  beach     OpenStreetMap named public beaches, hotel/club beaches removed - DM lists only Jumeira and Al Mamzar
  mall      DM building register (usage 'Shopping Centre', completed, >= 50k m2) via scripts/dm_malls.py; Trakhees-zone malls flagged

DHA caveat, found in the data: the register's x/y columns are swapped AND latitude is truncated to two decimals (~1.1 km).
So the DHA list is complete but its positions are coarse. Each facility is snapped to an Overture place with the same name
within 2.5 km when one exists (`src` = dha+overture); the rest keep the coarse point and carry `ap: 1` (approximate), which the
map shows honestly. Hospitals that cannot be snapped are resolved once through Google Places (cached, never re-paid).

Government schools come from the Emirates Schools Establishment's own map API (found via the archived schools-map page; the
public site itself was unreachable on 7 Sep). Arabic-only feed; English names in data/registers/ese_school_map/names_en.json.

Output data/board/amenities.json  {"counts", "sources", "items": [{k, n, lon, lat, src, ap?, x?, d?}]}  -> KV `amenities`
       data/board/amenities_overture.json  the previous Overture-only layer, kept for reference
Usage: python scripts/amenities_official.py [--no-push] [--no-google]
"""
import csv, glob, json, math, os, re, sys, time, collections, urllib.request
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
from build_avail_index import env_token, push  # noqa: E402
from geocoders import geocode_google  # noqa: E402
REG = os.path.join(ROOT, "data", "registers"); BOARD = os.path.join(ROOT, "data", "board"); RAW = os.path.join(ROOT, "data", "names", "overture_raw")
REFINE = os.path.join(REG, "refine_cache.json")

ACTIVE = {"FAC_ACT", "FAC_ACT_AEX"}
CLINIC_SUB = re.compile(r"polyclinic|general clinic|specialty clinic|dental clinic|day surgery|diagnostic center|medical fitness|fertility|general medical", re.I)
MALL_OK = re.compile(r"mall|souk|souq|cent(re|er)|walk|village|galleria|avenue|plaza|boulevard|pavilion|square|market|outlet|festival|arcade|promenade|\bmega|city|hub|mool|\u0645\u0648\u0644|\u0633\u0646\u062a\u0631|\u0645\u0631\u0643\u0632|\u0627\u0644\u0642\u0631\u064a\u0629|\u0633\u0648\u0642", re.I)
MALL_NOISE = re.compile(r"store\b|stores\b|trading|garments|salon|pharmacy|brands for less|splash|carrefour|coffee|cafe|restaurant|clinic|hotel|tower\b|residence|apartment|office|parking|\bllc\b|\bco\b|gift|toys|furniture|mattress|wellness|jewel|perfume|textile|electronics|mobile|optic|bakery|grocery|supermarket|hypermarket|\bmart\b", re.I)
PARK_NOISE = re.compile(r"coaster|play\b|bricks|trampoline|arcade|bounce|jump|\bvr\b|gaming|kidz|kids|cinema|club|gym|zone|soft play|indoor", re.I)
STOP = {"llc", "l.l.c", "l.l.c.", "br", "branch", "of", "the", "fz", "fz-llc", "fzco", "dubai", "center", "centre", "clinic", "clinics",
        "medical", "polyclinic", "pharmacy", "hospital", "hospitals", "healthcare", "health", "care", "and", "&", "co", "ltd", "limited",
        "dmcc", "jlt", "marina", "school", "international", "private", "academy", "for", "a", "an", "specialty", "speciality", "group", "sole", "proprietorship"}


def compress_hours(week):
    """['Monday: 10:00 AM - 12:00 AM', ...] -> 'Mon-Thu 10:00-00:00 · Fri-Sun 10:00-01:00' (same-hours days collapsed, 24 h clock)."""
    import re as _re
    def to24(t):
        m = _re.match(r"(\d{1,2}):(\d{2})\s*([AP]M)", t.strip(), _re.I)
        if not m: return t.strip()
        h, mi, ap = int(m.group(1)), m.group(2), m.group(3).upper()
        h = (h % 12) + (12 if ap == "PM" else 0)
        return f"{h:02d}:{mi}"
    days = []
    for w in week:
        d, _, h = w.partition(":")
        h = h.strip().replace(" ", " ").replace(" ", " ")
        if "Closed" in h: span = "closed"
        elif "Open 24" in h: span = "24 h"
        else:
            parts = [p.strip() for p in _re.split(r"\s*[–—-]\s*", h) if p.strip()]
            span = "-".join(to24(x) for x in parts[:2]) if len(parts) >= 2 else h
        days.append((d[:3], span))
    out, i = [], 0
    while i < len(days):
        j = i
        while j + 1 < len(days) and days[j + 1][1] == days[i][1]: j += 1
        out.append((days[i][0] if i == j else days[i][0] + "-" + days[j][0]) + " " + days[i][1]); i = j + 1
    return " · ".join(out)[:90]


def rows(name):
    out = []
    for f in sorted(glob.glob(os.path.join(REG, name, "*.csv"))):
        with open(f, encoding="utf-8-sig", errors="replace", newline="") as fh:
            out += list(csv.DictReader(fh))
    return out


def num(v):
    try: return float(str(v).strip())
    except Exception: return None


def fix_deg(v, lo, hi):
    """KHDA sometimes drops the decimal point ('25104140' for 25.104140)."""
    x = num(v)
    if x is None or x == 0: return None
    if lo <= x <= hi: return x
    s = str(int(abs(x)))
    if len(s) > 2:
        y = float(s[:2] + "." + s[2:]) * (1 if x > 0 else -1)
        if lo <= y <= hi: return y
    return None


def toks(name):
    t = re.sub(r"[^\w\s]", " ", (name or "").lower()).split()
    return {w for w in t if len(w) >= 3 and w not in STOP and not w.isdigit()}


def m2(a, b):
    t = math.pi / 180; dx = (b[0] - a[0]) * t * math.cos((a[1] + b[1]) * 0.5 * t); dy = (b[1] - a[1]) * t
    return math.sqrt(dx * dx + dy * dy) * 6371000


def overture_index():
    """Every Overture place with a health-ish name or category, for snapping DHA's coarse points."""
    pts = []
    for f in glob.glob(os.path.join(RAW, "*_place.geojson")):
        try: F = json.load(open(f, encoding="utf-8"))["features"]
        except Exception: continue
        for ft in F:
            pr = ft.get("properties") or {}; g = ft.get("geometry") or {}
            if g.get("type") != "Point": continue
            nm = ((pr.get("names") or {}).get("primary") or "").strip()
            cat = ((pr.get("categories") or {}).get("primary") or "")
            if not nm: continue
            if not (re.search(r"hospital|clinic|medical|pharmac|dental|polyclinic|health|surgery|diagnostic", nm + " " + cat, re.I)): continue
            pts.append((nm, toks(nm), g["coordinates"][0], g["coordinates"][1]))
    # dedupe by rounded position + name
    seen = set(); out = []
    for p in pts:
        k = (p[0].lower(), round(p[2], 4), round(p[3], 4))
        if k in seen: continue
        seen.add(k); out.append(p)
    return out


def snap(name, lon, lat, idx):
    T = toks(name)
    if not T: return None
    best = None
    for nm, tk, x, y in idx:
        sh = T & tk
        if not sh: continue
        d = m2((lon, lat), (x, y))
        if d > 2500: continue
        score = (len(sh) / max(1, len(T | tk)), -d)
        if best is None or score > best[0]: best = (score, x, y, nm)
    if best and best[0][0] >= 0.34: return best[1], best[2], best[3]
    return None


def in_district(lon, lat, D):
    for d in D:
        b = d["bbox"]
        if b[0] <= lon <= b[2] and b[1] <= lat <= b[3]: return d["slug"]
    return None


def main():
    do_push = "--no-push" not in sys.argv; use_google = "--no-google" not in sys.argv
    D = json.load(open(os.path.join(BOARD, "districts_geo.json"), encoding="utf-8"))["districts"]
    cache = json.load(open(REFINE, encoding="utf-8")) if os.path.exists(REFINE) else {}
    gkey = os.environ.get("GOOGLE_KEY") if use_google else None
    items = []; src_counts = collections.Counter(); paid = 0

    # ---- schools: KHDA -------------------------------------------------------------------------------------------------------
    for r in rows("school_search"):
        nm = (r.get("name_eng") or "").strip()
        if not nm: continue
        lat = fix_deg(r.get("lat"), 24.6, 25.6); lon = fix_deg(r.get("long"), 54.8, 56.2)
        src = "khda"
        if lat is None or lon is None:
            ck = "school:" + nm
            if ck not in cache and gkey:
                try: cache[ck] = geocode_google(gkey, nm, r.get("areaen") or ""); paid += 1
                except Exception: cache[ck] = None
            g = cache.get(ck)
            if not g: continue
            lon, lat, src = g["lon"], g["lat"], "khda+google"
        x = " · ".join(v for v in [(r.get("overallperformanceen") or "").replace("Not inspected yet", "not yet inspected"), (r.get("curriculumen") or "").split(" - ")[0][:28]] if v)
        it = {"k": "school", "n": nm[:70], "lon": round(lon, 6), "lat": round(lat, 6), "src": src, "x": x[:60]}
        for fld, key in (("telephone", "tel"), ("email", "em"), ("web_address", "web"), ("address", "ad"), ("inspectionreportpdflinken", "rep")):
            v = (r.get(fld) or "").strip()
            if v and v.lower() not in ("null", "none", "n/a", "-"): it[key] = v[:120]
        items.append(it); src_counts[src] += 1

    # ---- government schools: ESE school map (apigateway.ese.gov.ae GetSchoolMaps) -----------------------------------------------
    # the feed is Arabic-only; English names are hand-transliterated in names_en.json and the Arabic name rides along
    ese_dir = os.path.join(REG, "ese_school_map"); ese_src = os.path.join(ese_dir, "GetSchoolMaps_ar.json"); ese_en = os.path.join(ese_dir, "names_en.json")
    if os.path.exists(ese_src):
        EN = json.load(open(ese_en, encoding="utf-8")) if os.path.exists(ese_en) else {}
        for r in json.load(open(ese_src, encoding="utf-8")):
            if (r.get("educationZone") or "").strip() != "دبي": continue        # Dubai zone
            lat = num(r.get("latitude")); lon = num(r.get("longitude"))
            if not (lat and lon and 24.6 <= lat <= 25.6 and 54.8 <= lon <= 56.4): continue
            en = EN.get(str(r.get("id"))) or {}
            nm = en.get("n") or (r.get("schoolName") or "").strip()
            items.append({"k": "school", "n": nm[:70], "ar": (r.get("schoolName") or "").strip()[:70], "lon": round(lon, 6), "lat": round(lat, 6),
                          "src": "ese", "x": (en.get("x") or "government")[:60]})
            src_counts["ese"] += 1

    # ---- health: DHA Sheryan ---------------------------------------------------------------------------------------------------
    idx = overture_index()
    print(f"overture snapping index: {len(idx):,} health places")
    seen_h = set()
    for r in rows("sheryan_facility_detail"):
        if (r.get("status") or "") not in ACTIVE: continue
        sub = (r.get("facilitysubcategorynameenglish") or ""); nm = (r.get("facilitynameenglish") or "").strip()
        if not nm: continue
        if re.search(r"hospital", sub, re.I) and not re.search(r"pharmacy", sub, re.I): k = "hospital"
        elif CLINIC_SUB.search(sub): k = "clinic"
        else: continue
        # the register's columns are swapped: xcoordinate holds latitude (2 dp), ycoordinate holds longitude (full precision)
        lat = num(r.get("xcoordinate")); lon = num(r.get("ycoordinate"))
        if lat is not None and lon is not None and lon < lat: lat, lon = lon, lat
        if not (lat and lon and 24.6 <= lat <= 25.6 and 54.8 <= lon <= 56.2): lat = lon = None
        src = "dha"; ap = 1
        if lat is not None:
            s = snap(nm, lon, lat, idx)
            if s: lon, lat, src, ap = s[0], s[1], "dha+overture", 0
        if (ap or lat is None) and k == "hospital":
            ck = "hospital:" + nm
            if ck not in cache and gkey:
                try: cache[ck] = geocode_google(gkey, nm, r.get("areaenglish") or ""); paid += 1
                except Exception: cache[ck] = None
            g = cache.get(ck)
            if g and (lat is None or m2((lon, lat), (g["lon"], g["lat"])) < 3000):
                lon, lat, src, ap = g["lon"], g["lat"], "dha+google", 0
        if lat is None: continue
        key = (k, re.sub(r"\W+", "", nm.lower())[:40], round(lon, 3), round(lat, 2))
        if key in seen_h: continue
        seen_h.add(key)
        it = {"k": k, "n": nm[:70], "lon": round(lon, 6), "lat": round(lat, 6), "src": src, "x": sub[:48]}
        if ap: it["ap"] = 1
        for fld, key in (("telephone1", "tel"), ("email", "em"), ("website", "web")):
            v = (r.get(fld) or "").strip()
            if v and v.lower() not in ("null", "none", "n/a", "-"): it[key] = v[:120]
        _ad = ", ".join(v for v in ((r.get("addresslineone") or "").strip(), (r.get("addresslinetwoenglish") or "").strip(), (r.get("areaenglish") or "").strip()) if v)
        if _ad: it["ad"] = _ad[:120]
        items.append(it); src_counts[src] += 1

    # ---- metro + tram: RTA -------------------------------------------------------------------------------------------------------
    for name, line_default in (("metro_stations", ""), ("tram_stations", "Tram")):
        for r in rows(name):
            if (r.get("station_closing_date") or "").strip(): continue
            nm = (r.get("location_name_english") or "").strip(); lat = num(r.get("station_location_latitude")); lon = num(r.get("station_location_longitude"))
            if not (nm and lat and lon): continue
            line = (r.get("line_name") or line_default).replace(" Metro line", " line")
            items.append({"k": "metro", "n": nm[:70], "lon": round(lon, 6), "lat": round(lat, 6), "src": "rta", "x": line,
                          "tel": "800 9090", "web": "https://www.rta.ae", "ad": ("Dubai Tram" if "Tram" in line else "Dubai Metro") + " · " + line + " · zone " + (r.get("zone_id") or "?").replace(".00", ""), "dir": 1}); src_counts["rta"] += 1

    # ---- parks (DM major parks as one point each) + Overture parks / beaches / malls ------------------------------------------------
    parks = collections.defaultdict(list)
    for r in rows("dubai_parks_and_beaches_x_and_y_coordinates"):
        lat = num(r.get("coordinate_x")); lon = num(r.get("coordinate_y"))
        if lat and lon and lon < lat: lat, lon = lon, lat
        if lat and lon and (r.get("park_name") or "").strip(): parks[r["park_name"].strip()].append((lon, lat))
    dm_names = set()
    for nm, pts in parks.items():
        lon = sum(p[0] for p in pts) / len(pts); lat = sum(p[1] for p in pts) / len(pts)
        items.append({"k": "park", "n": nm[:70], "lon": round(lon, 6), "lat": round(lat, 6), "src": "dm"}); src_counts["dm"] += 1
        dm_names.add(re.sub(r"\W+", "", nm.lower()))
    ov = os.path.join(BOARD, "amenities_overture.json")
    if not os.path.exists(ov) and os.path.exists(os.path.join(BOARD, "amenities.json")):
        os.replace(os.path.join(BOARD, "amenities.json"), ov)              # keep the Overture-only layer once, for reference
    # malls from the authority: Dubai Municipality shopping-centre buildings >= 50k m2 (scripts/dm_malls.py), plus the flagged Trakhees gap
    dmm = os.path.join(REG, "dm_malls.json")
    if os.path.exists(dmm):
        for m in json.load(open(dmm, encoding="utf-8")).get("items", []):
            if not (m.get("lon") and m.get("lat") and m.get("name")): continue
            size = (f"{m['built_m2']/1e6:.2f}M m2" if m.get("built_m2") and m["built_m2"] >= 1e6 else (f"{round(m['built_m2']/1000)}k m2" if m.get("built_m2") else ""))
            it = {"k": "mall", "n": m["name"][:60], "lon": m["lon"], "lat": m["lat"], "src": m["src"], "x": (f"{m['tier']} · {size}" if size else m["tier"])[:60]}
            for f in ("tel", "web", "ad"):
                if m.get(f): it[f] = str(m[f])[:120]
            if m.get("hrs"): it["hrs"] = compress_hours(m["hrs"])
            items.append(it)
            src_counts[m["src"]] += 1
    # parks and beaches WITH ACCESS (8 Sep 2026): scripts/parks_register.py and scripts/beaches_register.py build them from Overture
    # land_use / land (= OpenStreetMap polygons) and classify access - public, community (residents' estate park), hotel, residents
    # (Palm fronds), unknown. No authority publishes either list; DM 463074 covers three parks' facilities. Labels say whose it is.
    PLAB = {"public": "public park", "community": "community park (residents)", "reserve": "nature reserve", "unknown": "park"}
    BLAB = {"public": "public beach", "hotel": "hotel beach (guests / day pass)", "residents": "residents' beach", "unknown": "beach"}
    pj = os.path.join(BOARD, "parks.json")
    if os.path.exists(pj):
        for it in json.load(open(pj, encoding="utf-8")).get("items", []):
            k = re.sub(r"[^a-z0-9]+", "", it["n"].lower())
            if k in dm_names: continue
            rec = {"k": "park", "n": it["n"][:60], "lon": it["lon"], "lat": it["lat"], "src": "osm", "acc": it["acc"], "x": PLAB.get(it["acc"], "park")}
            if it.get("area_ha"): rec["ha"] = it["area_ha"]
            items.append(rec); src_counts["osm"] += 1
    bj = os.path.join(BOARD, "beaches.json")
    if os.path.exists(bj):
        for it in json.load(open(bj, encoding="utf-8")).get("items", []):
            if it["acc"] == "unknown" and (it.get("area_ha") or 0) < 2: continue          # small unnamed sand is not a beach a buyer can use
            rec = {"k": "beach", "n": it["n"][:60], "lon": it["lon"], "lat": it["lat"], "src": "osm", "acc": it["acc"], "x": BLAB.get(it["acc"], "beach")}
            if it.get("area_ha"): rec["ha"] = it["area_ha"]
            items.append(rec); src_counts["osm"] += 1
    for it in items:
        d = in_district(it["lon"], it["lat"], D)
        if d: it["d"] = d
    json.dump(cache, open(REFINE, "w", encoding="utf-8"), ensure_ascii=False, indent=0)
    counts = collections.Counter(i["k"] for i in items); approx = collections.Counter(i["k"] for i in items if i.get("ap"))
    doc = {"generated": time.strftime("%Y-%m-%d %H:%M"), "counts": dict(counts), "approx": dict(approx), "sources": dict(src_counts),
           "note": ("Schools: KHDA register (private) and the Emirates Schools Establishment map (government). Parks and beaches: OpenStreetMap polygons via Overture with access (public / community / hotel / residents). Hospitals and clinics: "
                    "DHA Sheryan licence register, active facilities; positions snapped to a named place where one exists, otherwise "
                    "approximate to about 1 km (the register truncates latitude). Metro and tram: RTA. Parks: Dubai Municipality's major "
                    "parks plus Overture. Beaches and malls: Overture only - no official list is published."),
           "items": items}
    json.dump(doc, open(os.path.join(BOARD, "amenities.json"), "w", encoding="utf-8"), ensure_ascii=False)
    print(f"items {len(items):,} | {dict(counts)} | approximate {dict(approx)} | sources {dict(src_counts)} | google lookups paid this run {paid} | {os.path.getsize(os.path.join(BOARD,'amenities.json'))//1024} KB")
    if do_push:
        for attempt in range(3):
            try: print("amenities ->", push("amenities", doc, env_token("INGEST_TOKEN")).get("ok"), f"({os.path.getsize(os.path.join(BOARD,'amenities.json'))//1024} KB)"); break
            except Exception as e: print("  push retry", attempt + 1, str(e)[:60])


if __name__ == "__main__":
    main()
