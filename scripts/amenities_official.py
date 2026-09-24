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
Usage: python scripts/amenities_official.py [--push] [--no-google]
       Writing the file is the default; --push also ships it to the live worker and is opt-in since 24 Sep 2026.
       --no-push is still accepted and is now a no-op.
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
# The DHA position repair, guarded the same way in both lanes - see precise_points(). Change these two and
# build_district_cuts.py together or the lanes drift apart again.
PRECISE_GUARD_M = 600        # measured max genuine residual is 588 m
PRECISE_LON_EPS = 2e-6       # longitude never lost precision, so it must agree to six decimals
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


def idstr(v):
    """DuckDB hands a double-typed id back as a float, so "7528994.0" joins to nothing. Third time this has cost a join."""
    if v is None:
        return ""
    t = str(v)
    return t[:-2] if t.endswith(".0") else t


def precise_points():
    """Full-precision DHA positions, from the PROFESSIONAL register (build_dha_points.py, the DDA session, 23 Sep 2026).

    sheryan_facility_detail reduces LATITUDE to two decimals while keeping longitude to six, so 1,319 of our 1,845 health
    facilities sat somewhere on a north-south line. dha_sheryan_professional_detail is the same registry with the precision
    intact: on the 2,379 facility ids present in both, ours is 2dp on 100% and theirs on 0%, and longitude agrees to six
    decimals while latitude gains four. That is the signature of one number at two precisions rather than of two surveys.

    IT IS ROUNDING, NOT TRUNCATION - measured 23 Sep 2026, and it halves the error this function is correcting. Across
    1,551 accepted repairs our latitude equals theirs FLOORED on 851 (54.9%) and ROUNDED on the other 700 (45.1%), with
    ceil and neither at exactly zero. Floor and round agree whenever the third decimal is below 5, so a 55/45 split is
    what rounding alone predicts and truncation cannot produce. The error is therefore +/-0.005 deg, about +/-555 m, not
    0 to -1,110 m: measured residual median 277 m, p90 481 m, MAX 588 m. Anywhere this file, its notes or the question
    bank said "about 1.1 km", halve it. A coarse point is still useless for "within 500 m" and is fine for "in this
    community".

    TWO TESTS, NOT ONE - 24 Sep 2026, Kendall: "align the guards in both lanes". Longitude is the free test distance
    alone never used: only latitude lost precision, so on a genuine repair the longitudes must agree EXACTLY, and a
    moved longitude means the two registers describe DIFFERENT facilities rather than one facility placed better. Every
    row the old 1,150 m guard rejected differs in longitude, and 1,537 of the 1,551 it accepted agree to six decimals.
    The 14 it accepted with a moved longitude sit at 58-630 m and differ by up to 0.0023 deg - close enough to look
    innocent, which is precisely why a distance threshold cannot catch them.

    600 m rather than 1,150: the measured maximum genuine residual is 588 m, so 600 clears every real repair with
    nothing left over for a wrong one. build_district_cuts.py applies the identical pair of tests. THE TWO LANES MUST
    STAY IN STEP - the district count reads the raw lake table and this writes amenities.json, so a guard that differs
    between them places one facility two ways and two screens disagree with no visible cause.

    _dha_precise_points.json still carries guard_metres 1150. That is the producer's value and another session's
    artefact, so this takes the tighter of the two rather than editing it from here.

    The guard is a DISTANCE and a LONGITUDE, never a name. 826 of 827 candidates move the point less than 1.1 km
    (median 289 m, p90 482 m). The one that does not is id 3503718, where our register says Dubai Medical University
    Hospital and theirs says Saudi German Hospital - 28.4 km apart, and applied blindly it moves a hospital across the
    city. A NAME test would also catch it and would discard 417 good rows with it, because the two registers word
    branch names differently ("BR OF DM HEALTHCARE"): names agree on only 49.6% of the repairs.
    """
    p = os.path.join(BOARD, "_dha_precise_points.json")
    try:
        d = json.load(open(p, encoding="utf-8"))
    except Exception:
        return {}, PRECISE_GUARD_M
    return (d.get("points") or {}), min(int(d.get("guard_metres") or PRECISE_GUARD_M), PRECISE_GUARD_M)


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


# Dubai, and only Dubai. A bounding box cannot do this: the Dubai/Sharjah border runs diagonally
# through Al Nahda, so any rectangle that holds Deira also holds Sharjah and the Ajman corniche.
# Kendall found Fairmont Ajman on the map, and there were twelve more like it.
#
# The coordinates alone will not settle it either, and the address alone is worse: Hatta is a Dubai
# exclave whose address reads "Sharjah Kalba Road", and the Al Maha reserve sits on Al Ain Road -
# both genuinely Dubai. What works is the LAST component of the address, which is the emirate:
# "... Al Nakheel, Ajman" is Ajman; "... Sharjah Kalba Road, Dubai" is Dubai.
OTHER_EMIRATE = re.compile(
    r"\b(ajman|sharjah|umm al quwain|ras al khaimah|fujairah|abu dhabi|al ain)\b", re.I)


# Dubai's northern extent, measured rather than drawn: of 2,416 points in this very file that come
# from Dubai government registers - KHDA schools, DHA clinics, RTA metro, DM parks, DEWA chargers -
# not one sits above 25.30. DEWA's own charger network stops at 25.2976, at Al Mamzar, because that
# is where the emirate stops. A community-contributed point north of that is in Sharjah or Ajman,
# and an unnamed one with no address gives us nothing else to judge it by.
DUBAI_MAX_LAT = 25.31


def not_dubai(name, address, lat=None, src=None):
    """True when this point belongs to another emirate."""
    if lat is not None and lat > DUBAI_MAX_LAT and src != "DEWA":
        return True
    tail = [x.strip() for x in str(address or "").split(",") if x.strip()]
    if tail and re.fullmatch(r"dubai|dubai emirate|uae|united arab emirates", tail[-1], re.I):
        return False                      # the address says which emirate, and it says Dubai
    if tail and OTHER_EMIRATE.search(tail[-1]):
        return True
    return bool(OTHER_EMIRATE.search(str(name or "")))


def in_district(lon, lat, D):
    for d in D:
        b = d["bbox"]
        if b[0] <= lon <= b[2] and b[1] <= lat <= b[3]: return d["slug"]
    return None


def main():
    # PUSHING IS OPT-IN, 24 Sep 2026. It used to be the default, with --no-push to suppress it, and on 24 Sep a
    # queued rebuild in another session ran this bare and would have shipped to the live worker over the head of
    # the session that is the sole deployer. It was caught by someone reading the flags, which is not a control.
    # Nothing automated calls this script - checked across .py, .sh, .md, .json and .yml - so inverting the
    # default breaks no caller, and the failure mode changes from "ships by accident" to "someone re-runs it".
    # --no-push is still accepted and now does nothing, so anyone with it in their notes is unaffected.
    do_push = "--push" in sys.argv and "--no-push" not in sys.argv
    use_google = "--no-google" not in sys.argv
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
    PRECISE, PRECISE_GUARD = precise_points()
    rejected_far = [0]
    rejected_lon = [0]
    repaired = [0]
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
        # the same facility, positioned properly. Tried before snap(): an exact point from the registry beats a guess made
        # by matching a name to an Overture place, and where there is no coarse point at all this is the only one we get.
        pp = PRECISE.get(idstr(r.get("id")) or idstr(r.get("facilityid")))
        if pp and 24.6 <= pp[0] <= 25.6 and 54.8 <= pp[1] <= 56.2:
            # Two tests, and the longitude one is the sharper. Only latitude lost precision, so a repair that also
            # moves the longitude is a different facility, however short the hop looks - the 14 this catches sit at
            # 58-630 m, well inside any distance threshold anyone would pick.
            if lat is None:
                ok_lon = ok_far = True
            else:
                ok_lon = abs(lon - pp[1]) < PRECISE_LON_EPS
                ok_far = m2((lon, lat), (pp[1], pp[0])) <= PRECISE_GUARD
            if ok_lon and ok_far:
                lat, lon, ap = pp[0], pp[1], 0
                repaired[0] += 1
            elif not ok_lon:
                rejected_lon[0] += 1
            else:
                rejected_far[0] += 1
        if ap and lat is not None:
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
    print("  health: %d repaired to full precision from the professional register; rejected %d beyond the %d m guard "
          "and %d for a moved longitude (a moved longitude is a different facility, not a better position)"
          % (repaired[0], rejected_far[0], PRECISE_GUARD, rejected_lon[0]))

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
    # community malls and chain supermarkets (Kendall, 15 Sep: "we know there's a Spinneys, we know there's a very small mall there,
    # are those included?" - they were not: the DM register only lists shopping centres of 50k m2 and more, and no supermarket group
    # existed). Source: OpenStreetMap shop=mall / shop=supermarket for Dubai (data/registers/osm_shops_dubai.json, scripts refresh it
    # with Overpass). Malls: named ones not already covered by a DM mall within 300 m, plus unnamed ones named from a public source in
    # data/registers/mall_names_manual.json. Supermarkets: recognised chains only - a buyer asks for the nearest Spinneys, not the
    # nearest corner grocery - so local baqalas mapped as supermarkets are left out and the note says so. Brand names are
    # cross-checked against the DED trade-name register in the truth store (ded = 1 when the brand appears there).
    shops = os.path.join(REG, "osm_shops_dubai.json"); manual = os.path.join(REG, "mall_names_manual.json")
    if os.path.exists(shops):
        CHAINS = {"spinneys": "Spinneys", "carrefour": "Carrefour", "waitrose": "Waitrose", "choithram": "Choithrams", "union coop": "Union Coop",
                  "geant": "Géant", "géant": "Géant", "lulu": "Lulu", "west zone": "West Zone", "viva": "Viva", "grandiose": "Grandiose",
                  "aswaaq": "Aswaaq", "nesto": "Nesto", "al maya": "Al Maya", "zoom": "Zoom", "allday": "Allday", "kibsons": "Kibsons"}
        ded_brands = set()
        try:
            import duckdb
            _c = duckdb.connect(os.path.join(ROOT, "data", "graph", "najma.duckdb"), read_only=True)
            for b in set(CHAINS.values()):
                n = _c.execute("select count(*) from gov_ded__trade_name where trade_name_en ilike ?", [f"%{b}%"]).fetchone()[0] if _c else 0
                if n: ded_brands.add(b)
        except Exception:
            pass
        mnames = json.load(open(manual, encoding="utf-8")).get("items", []) if os.path.exists(manual) else []
        dm_pts = [(i["lon"], i["lat"]) for i in items if i["k"] == "mall"]
        def near_any(lon, lat, pts, m):
            return any(math.hypot((lon - a) * 100800, (lat - b) * 111320) <= m for a, b in pts)
        n_mall = n_sm = 0
        for e in json.load(open(shops, encoding="utf-8")).get("elements", []):
            t = e.get("tags") or {}; c = e.get("center") or {"lat": e.get("lat"), "lon": e.get("lon")}
            if not c.get("lat") or not c.get("lon"): continue
            lon, lat = round(c["lon"], 6), round(c["lat"], 6); nm = (t.get("name:en") or t.get("name") or "").strip()
            if t.get("shop") == "mall":
                if not nm:
                    mm = next((x for x in mnames if math.hypot((lon - x["lon"]) * 100800, (lat - x["lat"]) * 111320) <= 120), None)
                    if not mm: continue
                    nm = mm["name"]
                if near_any(lon, lat, dm_pts, 300): continue
                it = {"k": "mall", "n": nm[:60], "lon": lon, "lat": lat, "src": "osm", "x": "community mall"}
                if t.get("website"): it["web"] = t["website"][:120]
                if t.get("phone"): it["tel"] = t["phone"][:40]
                items.append(it); src_counts["osm"] += 1; n_mall += 1
            elif t.get("shop") == "supermarket":
                import unicodedata
                fold = lambda x: "".join(ch for ch in unicodedata.normalize("NFKD", x) if not unicodedata.combining(ch)).lower()
                low = fold(t.get("brand") or nm); brand = next((v for k, v in CHAINS.items() if fold(k) in low), None)
                if not brand: continue
                # a brand tag on a node whose name is plainly not a shop (OSM had Carrefour on "Damac Hills Skate Park") is a mis-tag
                if nm and fold(brand) not in fold(nm) and re.search(r"park|skate|mosque|masjid|school|clinic|tower|villa", nm, re.I): continue
                if nm and nm == nm.lower(): nm = nm.title()
                label = nm if nm and fold(brand) in fold(nm) else (f"{brand} {nm}".strip() if nm else brand)
                it = {"k": "supermarket", "n": label[:60], "lon": lon, "lat": lat, "src": "osm", "x": brand, "br": brand}
                if brand in ded_brands: it["ded"] = 1
                if t.get("opening_hours"): it["hrs"] = compress_hours(t["opening_hours"]) if "compress_hours" in globals() else t["opening_hours"][:60]
                items.append(it); src_counts["osm"] += 1; n_sm += 1
        print(f"community malls from OpenStreetMap: {n_mall}; chain supermarkets: {n_sm} (DED-listed brands: {sorted(ded_brands)})")
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
    # EV charging (Kendall, 17 Sep 2026). Added HERE, inside the canonical build, rather than
    # appended to the pushed image afterwards: this script rewrites `amenities` wholesale, so an
    # appended layer would survive exactly until the next amenities run. Same lesson as the media
    # register - a build that owns an image must own every layer in it.
    #
    # Three sources, and the map keeps them apart rather than flattening them. DEWA's Green Charger
    # register is the authority; OpenChargeMap and OpenStreetMap are contributed by the public and
    # can be stale or wrong. That distinction goes in `src`, in the data, because a provenance that
    # lives in a conversation is not a provenance.
    try:
        import duckdb
        _con = duckdb.connect(os.path.join(ROOT, "data", "graph", "najma.duckdb"), read_only=True)
        _ev = _con.execute(
            "select source, operator, location_name, location_address, latitude, longitude, "
            "       totalnbofconnectors, connectortype, max_power_kw "
            "  from v_ev_charge_points "
            " where latitude is not null and longitude is not null").fetchall()
        _con.close()
    except Exception as e:
        print("  EV chargers SKIPPED - %s" % str(e)[:90])
        _ev = []

    _SRC = {"DEWA": "dewa", "OpenChargeMap": "ocm", "OpenStreetMap": "osm"}
    _ev_kept = _ev_other = 0
    for _src, _op, _nm, _addr, _lat, _lon, _bays, _conn, _kw in _ev:
        # Keep the layer inside the map's own extent. 57 of the 351 points sit in other emirates,
        # every one of them community-contributed, and a pin 300 km away is not an amenity of a
        # Dubai building.
        if not (24.7 <= _lat <= 25.45 and 54.8 <= _lon <= 56.2):
            continue
        if not_dubai(_nm, _addr, _lat, _src):
            _ev_other += 1
            continue
        _name = (_nm or "").strip()
        if _name.upper() in ("", "NA", "N/A", "NONE", "UNKNOWN"):
            _name = (_addr or "").strip() or ("%s charger" % (_op or "EV"))
        _bits = []
        # Seen rendered on the live map, which is the only place it was visible: the app prefixes a
        # community-sourced row with "community listing, unverified" and then prints this line, so
        # "Tesla (Tesla-only charging)" made the row read "unverified Tesla (Tesla-only charging)".
        # That doubts TESLA rather than the listing, and she reads these to a client standing in
        # front of her. Drop the parenthetical, and drop the connector when it only repeats the
        # operator - 69 rows said "Tesla ... Tesla".
        _opn = re.sub(r"\s*\(.*?\)", "", str(_op or "")).strip()
        if _opn and _opn.lower() not in ("none", "unknown", ""):
            _bits.append(_opn)
        if _bays:
            _bits.append("%d bay%s" % (int(_bays), "" if int(_bays) == 1 else "s"))
        if _kw:
            _bits.append("%g kW" % float(_kw))
        if _conn:
            # "AC Type 2 (Mennekes) , DC CHAdeMO" -> "AC Type 2 \u00b7 DC CHAdeMO"
            _c = " \u00b7 ".join(sorted({re.sub(r"\s*\(.*?\)", "", x).strip()
                                         for x in str(_conn).split(",") if x.strip()}))
            if _c and _c.lower() != _opn.lower():
                _bits.append(_c)
        _rec = {"k": "ev", "n": _name[:60], "lon": round(float(_lon), 5),
                "lat": round(float(_lat), 5), "src": _SRC.get(_src, str(_src).lower())}
        if _bits:
            _rec["x"] = " \u00b7 ".join(_bits)[:80]
        items.append(_rec)
        src_counts[_SRC.get(_src, "ev")] += 1
        _ev_kept += 1
    print("  EV chargers: %d kept of %d (%d in another emirate)" % (_ev_kept, len(_ev), _ev_other))

    for it in items:
        d = in_district(it["lon"], it["lat"], D)
        if d: it["d"] = d
    json.dump(cache, open(REFINE, "w", encoding="utf-8"), ensure_ascii=False, indent=0)
    counts = collections.Counter(i["k"] for i in items); approx = collections.Counter(i["k"] for i in items if i.get("ap"))
    doc = {"generated": time.strftime("%Y-%m-%d %H:%M"), "counts": dict(counts), "approx": dict(approx), "sources": dict(src_counts),
           "note": ("Schools: KHDA register (private) and the Emirates Schools Establishment map (government). Parks and beaches: OpenStreetMap polygons via Overture with access (public / community / hotel / residents). Hospitals and clinics: "
                    "DHA Sheryan licence register, active facilities; positions snapped to a named place where one exists, otherwise "
                    "approximate to about 1 km (the register truncates latitude). Metro and tram: RTA. Parks: Dubai Municipality's major "
                    "parks plus Overture. Beaches and malls: Overture only - no official list is published. "
                    "EV charging: DEWA's Green Charger register is the authority (src dewa); points marked ocm or "
                    "osm are contributed by the public through OpenChargeMap and OpenStreetMap and may be stale "
                    "or wrong."),
           "items": items}
    json.dump(doc, open(os.path.join(BOARD, "amenities.json"), "w", encoding="utf-8"), ensure_ascii=False)
    print(f"items {len(items):,} | {dict(counts)} | approximate {dict(approx)} | sources {dict(src_counts)} | google lookups paid this run {paid} | {os.path.getsize(os.path.join(BOARD,'amenities.json'))//1024} KB")
    if do_push:
        for attempt in range(3):
            try: print("amenities ->", push("amenities", doc, env_token("INGEST_TOKEN")).get("ok"), f"({os.path.getsize(os.path.join(BOARD,'amenities.json'))//1024} KB)"); break
            except Exception as e: print("  push retry", attempt + 1, str(e)[:60])
    else:
        print("  not pushed. data/board/amenities.json is written; pass --push to ship it, and only with the "
              "deploying session's agreement.")


if __name__ == "__main__":
    main()
