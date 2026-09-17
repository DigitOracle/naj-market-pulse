"""The client sheet: the first thing the data spine produces that a buyer physically receives.

Everything upstream of this - the Land Department sales export, the Ejari rent contracts, the units
register, the media register, the floor-plan library - has only ever been readable inside the app by
Naj. This turns one building record into two or three A4 pages she can send on WhatsApp, email or
WeChat without retyping anything, and without a client ever being handed a link into Azimuth.

Two views of one record. Her view keeps everything: partial bindings, confidence flags, the thin
medians. The client view is a deliberate subset, and every number on it names where it came from -
that provenance block is the difference between this and a portal printout.

Pages
  1  the property, the numbers (sale, rent, gross yield by bedroom), where it is
  2  layouts and finish - floor plans and the developer's renders
  3  what is in the building - the unit mix, and live availability where we hold it

Availability, honestly: for the seven developers whose broker groups we read (Arada, Beyond,
Fakhruddin, Imtiaz, Palma, Prestige One, Select) page 3 can list real units for sale with prices.
For a ready resale building like Bellevue Towers nobody publishes a live list, so page 3 shows what
the units register says the building actually holds - 223 one-beds on levels 1-22, and so on - which
answers the same client question ("what else is there?") without inventing a listing.

The bar. A sheet is only offered when the building clears --min-sales recorded sales AND has at
least one picture. A sheet with good numbers and no pictures reads as a spreadsheet and she will not
send it; better to offer nothing. `--list-ready` shows which buildings pass.

Usage
  python scripts/build_client_sheet.py --building "Bellevue Towers"
  python scripts/build_client_sheet.py --pack "Bellevue Towers" "The EDGE" --pack-name business_bay_2br
  python scripts/build_client_sheet.py --list-ready [--district burjkhalifa]
  python scripts/build_client_sheet.py --walk "Bellevue Towers" --at 25.1972,55.2744
"""
import argparse, datetime as dt, glob, html, json, math, os, re, subprocess, sys, urllib.parse, urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
DLD = os.path.join(ROOT, "data", "dld")
BOARD = os.path.join(ROOT, "data", "board")
SHEETS = os.path.join(ROOT, "data", "sheets")
ASSETS = os.path.join(SHEETS, "_assets")       # <slug>/hero.jpg, plan_1br.jpg, ...
FACTS = os.path.join(SHEETS, "_facts")         # <slug>.json - curated from the developer's brochure
AVAIL = os.path.join(ROOT, "data", "avail")

CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
SQM_TO_SQFT = 10.7639
UA = {"User-Agent": "DigitAlchemy-najma/1.0 (contact@digitalabbot.io)", "Accept": "application/json"}

# The picture roles a sheet can use, in the order page 2 wants them.
# Specific roles are only ever set by a person who looked at the picture. The wiring script assigns
# neutral interior_1..3 instead, because nothing automatic can tell a bedroom from a living room.
ROLES = ["hero", "plan_1br", "plan_2br", "plan_3br", "bedroom", "kitchen", "bath", "living", "amenity",
         "interior_1", "interior_2", "interior_3"]


def slugify(s):
    return re.sub(r"[^a-z0-9]+", "_", str(s or "").lower()).strip("_")[:50]


def money(n):
    return "{:,}".format(int(round(n)))


def esc(s):
    return html.escape(str(s), quote=True)


# --------------------------------------------------------------------------- data


def districts():
    for p in sorted(glob.glob(os.path.join(DLD, "tx_buildings_*.json"))):
        yield os.path.basename(p)[len("tx_buildings_"):-len(".json")]


def find_building(name, district=None):
    """Locate a building across the per-district Land Department extracts.

    Returns every matching row - a two-tower development registers as two buildings (Bellevue
    Towers-1 and -2) and the caller decides whether to merge them or take the deepest one."""
    want = slugify(name)
    hits = []
    for d in ([district] if district else districts()):
        p = os.path.join(DLD, "tx_buildings_%s.json" % d)
        if not os.path.exists(p):
            continue
        for b in json.load(open(p, encoding="utf-8")).get("buildings", []):
            if want in slugify(b.get("project")) or want in slugify(b.get("building")):
                hits.append(dict(b, _district=d))
    return hits


def rent_for(project, district):
    p = os.path.join(DLD, "rent_projects_%s.json" % district)
    if not os.path.exists(p):
        return None
    want = slugify(project)
    for r in json.load(open(p, encoding="utf-8")).get("projects", []):
        if slugify(r.get("project")) == want:
            return r
    return None


def unitmix_for(name, district):
    p = os.path.join(BOARD, "unitmix_%s.json" % district)
    if not os.path.exists(p):
        return None
    want = slugify(name)
    for _id, b in json.load(open(p, encoding="utf-8")).get("buildings_by_id", {}).items():
        if slugify(b.get("name")) == want:
            return b
    return None


def live_units(name):
    """Units actually for sale, from the developer broker-group feed. Only some developers post
    these; a building outside that set gets the units register instead, clearly labelled."""
    want = slugify(name)
    out, seen_file = [], None
    for p in sorted(glob.glob(os.path.join(AVAIL, "*.json"))):
        base = os.path.basename(p)
        if base.startswith("_") or base in ("group_links.json", "listener_health.json"):
            continue
        try:
            d = json.load(open(p, encoding="utf-8"))
        except Exception:
            continue
        for row in (d.get("units") or d.get("rows") or []):
            if want and want in slugify(row.get("project") or row.get("tower") or ""):
                out.append(row)
                seen_file = base
    return out, seen_file


def facts_for(slug):
    p = os.path.join(FACTS, "%s.json" % slug)
    return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else {}


def assets_for(slug):
    d = os.path.join(ASSETS, slug)
    got = {}
    if os.path.isdir(d):
        for role in ROLES:
            for ext in (".jpg", ".jpeg", ".png"):
                p = os.path.join(d, role + ext)
                if os.path.exists(p):
                    got[role] = p
                    break
    return got


MEDIANS = os.path.join(SHEETS, "_medians.json")


def build_medians():
    """True project-level medians, straight from the raw Land Department export.

    A development registers as one building per tower, and tx_buildings.json holds a median per
    tower. Pooling those by a count-weighted mean is NOT the median of the combined set - for
    Bellevue it put the one-bed at 836 sq ft against a true 853 - and a sheet that says "median"
    has to mean it. So this computes the real thing once, per project per room type, and the sheet
    reads the cache. It also makes the sale side cover both towers, which is what the Ejari rent
    side already did: before this, page 1 paired one tower's prices with two towers' rents."""
    import duckdb
    files = [f for f in sorted(glob.glob(os.path.join(ROOT, "data", "raw_downloads", "transactions_*.csv")))
             if "(" not in f]
    if not files:
        print("no raw transaction export found - cannot build true medians")
        return None
    con = duckdb.connect()
    src = " UNION ALL ".join("select * from read_csv_auto('%s', sample_size=50000, all_varchar=true)"
                             % f.replace("\\", "/") for f in files)
    con.execute("create table tx as select * from (%s)" % src)
    rows = con.execute("""
        select coalesce(nullif(project_name_en,''),'') as project,
               coalesce(nullif(rooms_en,''),'n/a') as rooms,
               count(*) as n,
               median(try_cast(actual_worth as double)) as med_aed,
               median(try_cast(procedure_area as double)) as med_sqm,
               max(try_cast(instance_date as date)) as lastd,
               min(try_cast(instance_date as date)) as firstd
        from tx
        where trans_group_en = 'Sales' and property_type_en = 'Unit'
          and coalesce(nullif(project_name_en,''),'') <> ''
        group by 1, 2
    """).fetchall()
    out = {}
    for project, rooms, n, aed, sqm, lastd, firstd in rows:
        if not aed or not sqm:
            continue
        out.setdefault(slugify(project), {"project": project, "types": {}})["types"][rooms] = {
            "n": n, "median_aed": aed, "median_sqm": sqm,
            "last": str(lastd), "first": str(firstd)}

    # Recent sales, per project. A median tells a buyer what the building is worth; the last handful
    # of actual sales tells them the market is live and what people really paid this year. Both, or
    # the page reads like a valuation rather than an opportunity.
    recent = con.execute("""
        select project, rooms, sqm, aed, d from (
          select coalesce(nullif(project_name_en,''),'') as project,
                 coalesce(nullif(rooms_en,''),'n/a') as rooms,
                 try_cast(procedure_area as double) as sqm,
                 try_cast(actual_worth as double) as aed,
                 try_cast(instance_date as date) as d,
                 row_number() over (partition by coalesce(nullif(project_name_en,''),'')
                                    order by try_cast(instance_date as date) desc) as rn
          from tx
          where trans_group_en = 'Sales' and property_type_en = 'Unit'
            and coalesce(nullif(project_name_en,''),'') <> ''
            and try_cast(actual_worth as double) is not null
            and try_cast(procedure_area as double) > 0
        ) where rn <= 30
    """).fetchall()

    # The register carries more than open-market sales: share transfers, gifts between relatives and
    # partial assignments all land in the same table. Bellevue's most recent six included a "sale" of
    # a 617 sq ft one-bed for AED 17,700 - 1.6% of the going rate. A median absorbs that; a list of
    # six does not, and one absurd line on a client sheet discredits every honest number beside it.
    # So a recent sale must price within a plausible band of its own type's median rate per sq m.
    LO, HI = 0.35, 2.5
    for project, rooms, sqm, aed, d in recent:
        s = out.get(slugify(project))
        if s is None or not sqm or not aed:
            continue
        t = s["types"].get(rooms)
        if t and t.get("median_sqm"):
            ref = t["median_aed"] / t["median_sqm"]
            if ref > 0 and not (LO <= (aed / sqm) / ref <= HI):
                s["dropped"] = s.get("dropped", 0) + 1
                continue
        s.setdefault("recent", []).append({"rooms": rooms, "sqm": sqm, "aed": aed, "date": str(d)})
    for s in out.values():
        s["recent"] = sorted(s.get("recent", []), key=lambda r: r["date"], reverse=True)[:6]
    dropped = sum(s.get("dropped", 0) for s in out.values())
    print("  %d recent-sale rows dropped as off-market (share transfers, partial assignments)" % dropped)
    os.makedirs(SHEETS, exist_ok=True)
    json.dump({"generated": dt.date.today().isoformat(),
               "source": "Dubai Land Department transactions export, %s" % ", ".join(os.path.basename(f) for f in files),
               "projects": out}, open(MEDIANS, "w", encoding="utf-8"), ensure_ascii=False)
    print("true medians cached for %d projects -> %s" % (len(out), os.path.relpath(MEDIANS, ROOT)))
    return out


_MED_CACHE = None


def load_medians():
    """Cached: --list-ready walks thousands of buildings and this file holds 2,440 projects."""
    global _MED_CACHE
    if _MED_CACHE is None:
        _MED_CACHE = (json.load(open(MEDIANS, encoding="utf-8")).get("projects", {})
                      if os.path.exists(MEDIANS) else {})
    return _MED_CACHE


def merge_types(rows, project):
    """Prefer the true pooled median; fall back to the per-tower extract when no cache exists."""
    cache = load_medians().get(slugify(project))
    if cache:
        return ({t: dict(v, exact=True) for t, v in cache["types"].items()
                 if t not in ("NA", "n/a", "null", None)}, True)

    pooled = {}
    for b in rows:
        for t, v in (b.get("by_rooms") or {}).items():
            if t in ("NA", "null", None) or not v.get("median_aed"):
                continue
            p = pooled.setdefault(t, {"n": 0, "aed": 0.0, "sqm": 0.0, "last": ""})
            p["n"] += v.get("n", 0)
            p["aed"] += (v.get("median_aed") or 0) * v.get("n", 0)
            p["sqm"] += (v.get("median_sqm") or 0) * v.get("n", 0)
            p["last"] = max(p["last"], v.get("last") or "")
    for t, p in pooled.items():
        if p["n"]:
            p["median_aed"] = p["aed"] / p["n"]
            p["median_sqm"] = p["sqm"] / p["n"]
            p["exact"] = False
    return pooled, False


def pretty(name):
    """DLD writes project names in caps. A client sheet should not shout."""
    s = str(name or "").strip()
    if s and s == s.upper():
        s = " ".join(w.capitalize() if not w.isdigit() else w for w in s.split())
    return s


# What counts as a home. The register mixes shops, offices, stores and even a GYM into the same
# by-rooms breakdown as apartments, and a sheet headed "by apartment type" must not list them: Bay
# Square's live sheet carried a "Shop" row at a 17.4% yield under a column headed APARTMENT, which a
# client would read as an apartment yield. A building's commercial floorspace is not what she is
# selling, and where it is ALL a building has, there is no client sheet to build.
RESIDENTIAL = {"Studio", "PENTHOUSE", "Single Room"} | {"%d B/R" % n for n in range(1, 10)}
NON_RESIDENTIAL = {"Shop", "Office", "Store", "GYM"}

TYPE_ORDER = {"Studio": 0, "1 B/R": 1, "2 B/R": 2, "3 B/R": 3, "4 B/R": 4, "5 B/R": 5,
              "6 B/R": 6, "7 B/R": 7, "8 B/R": 8, "9 B/R": 9, "PENTHOUSE": 10}
TYPE_LABEL = dict({"%d B/R" % n: "%d bedroom" % n for n in range(1, 10)},
                  **{"Studio": "Studio", "PENTHOUSE": "Penthouse", "Single Room": "Single room"})


MIN_TYPE_SALES = 4   # below this a "median" is one person's deal, not the market


def build_record(name, district=None, min_sales=20):
    rows = find_building(name, district)
    if not rows:
        return None, "no Land Department record for %r" % name
    d = rows[0]["_district"]
    project = rows[0].get("project") or name
    slug = slugify(project)

    pooled, exact = merge_types(rows, project)
    if not pooled:
        # Every transaction in this building is recorded against an unclassified room type, so
        # there is nothing to quote. Real: plot sales, hotel keys, and a tail of registrations
        # where rooms_en is blank.
        return None, "no transactions with a recorded apartment type for %r" % name
    commercial = {t: v for t, v in pooled.items() if t in NON_RESIDENTIAL}
    pooled = {t: v for t, v in pooled.items() if t in RESIDENTIAL}
    if not pooled:
        sold = ", ".join("%s (%d sales)" % (t, v.get("n", 0)) for t, v in
                         sorted(commercial.items(), key=lambda x: -x[1].get("n", 0)))
        return None, ("%r is not residential - every recorded sale is %s. A client fact sheet prices "
                      "homes; there is nothing here to price." % (name, sold or "non-residential"))

    # the headline count must be HOMES sold, not every transaction in a mixed-use block - Bay Square
    # reads 2,148 sales of which 1,426 are offices and shops
    sales_total = (sum(v.get("n", 0) for v in pooled.values()) if exact
                   else sum(r.get("sales", 0) for r in rows))
    rent = rent_for(project, d)
    mix = unitmix_for(project, d)
    fx = facts_for(slug)
    imgs = assets_for(slug)
    prov_p = os.path.join(ASSETS, slug, "_provenance.json")
    if os.path.exists(prov_p):
        try:
            pv = json.load(open(prov_p, encoding="utf-8"))
            fx = dict({"developer": pv.get("developer")} if pv.get("developer") else {}, **fx)
        except Exception:
            pass
    units, units_src = live_units(project)


    types = []
    for t in sorted(pooled, key=lambda x: TYPE_ORDER.get(x, 99)):
        p = pooled[t]
        rb = ((rent or {}).get("by_type") or {}).get(t) or {}
        median_rent = rb.get("median_annual")
        row = {
            "key": t,
            "label": TYPE_LABEL.get(t, t),
            "sales": p["n"],
            "median_aed": p["median_aed"],
            "median_sqm": p["median_sqm"],
            "median_sqft": p["median_sqm"] * SQM_TO_SQFT,
            "last": p["last"],
            "rent": median_rent,
            "rent_n": rb.get("n"),
            "yield": (median_rent / p["median_aed"] * 100) if (median_rent and p["median_aed"]) else None,
        }
        if mix:
            for m in (mix.get("rows") or []):
                if slugify(m.get("type")) == slugify(row["label"]):
                    row["units_in_building"] = m.get("units")
                    row["levels"] = m.get("levels")
        types.append(row)

    # Types too thin to quote. Treppan's three-bed median rested on a single sale - printing that
    # beside "median of every transaction on record" invites a client to treat one person's deal as
    # the going rate. They stay on page 3, which says what the building holds, not what it costs.
    thin = [t for t in types if t["sales"] < MIN_TYPE_SALES]
    types = [t for t in types if t["sales"] >= MIN_TYPE_SALES]

    rec = {
        "name": pretty(project), "slug": slug, "district": d, "medians_exact": exact,
        "master": rows[0].get("master"), "area": rows[0].get("area"),
        "buildings": [r.get("building") for r in rows],
        "sales_total": sales_total,
        "first": (min(v["first"] for v in pooled.values()) if exact
                  else min(r.get("first", "") for r in rows)),
        "last": (max(v["last"] for v in pooled.values()) if exact
                 else max(r.get("last", "") for r in rows)),
        "types": types, "thin_types": thin,
        "commercial": {t: v.get("n", 0) for t, v in commercial.items()},
        "rent_window": (rent or {}).get("window"),
        "rent_total": (rent or {}).get("n"),
        "mix": mix, "facts": fx, "images": imgs,
        "recent": (load_medians().get(slug) or {}).get("recent", []),
        "live_units": units, "live_units_source": units_src,
        "metro": rows[0].get("metro"), "mall": rows[0].get("mall"),
    }

    why = []
    if sales_total < min_sales:
        why.append("only %d recorded sales (bar is %d)" % (sales_total, min_sales))
    if not imgs:
        why.append("no pictures held")
    rec["ready"] = not why
    rec["not_ready_because"] = why
    return rec, None


# --------------------------------------------------------------------------- walk times


def walk_times(lat, lon):
    """Real pedestrian routes, never straight-line-times-a-fudge-factor. Stations come from the RTA
    register we hold; the route comes from a public OSRM foot router."""
    reg = os.path.join(ROOT, "data", "registers", "metro_stations")
    files = glob.glob(os.path.join(reg, "*.json"))
    stations = []
    for f in files:
        if os.path.basename(f).startswith("_"):
            continue
        for s in json.load(open(f, encoding="utf-8")):
            if s.get("station_closing_date"):
                continue
            a, b = s.get("station_location_latitude"), s.get("station_location_longitude")
            if a and b:
                stations.append((s["location_name_english"], float(a), float(b)))

    def hav(p, q):
        R = 6371000.0
        p1, p2 = math.radians(p[0]), math.radians(q[0])
        dp, dl = p2 - p1, math.radians(q[1] - p[1])
        h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
        return 2 * R * math.asin(math.sqrt(h))

    stations.sort(key=lambda s: hav((lat, lon), (s[1], s[2])))
    out = []
    for nm, a, b in stations[:2]:
        try:
            u = ("https://routing.openstreetmap.de/routed-foot/route/v1/foot/"
                 "%f,%f;%f,%f?overview=false" % (lon, lat, b, a))
            r = json.loads(urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=60).read())
            if r.get("code") == "Ok":
                rt = r["routes"][0]
                out.append({"name": nm, "walk_min": int(round(rt["duration"] / 60)),
                            "walk_m": int(round(rt["distance"]))})
        except Exception as e:
            print("  walk route failed for %s: %s" % (nm, e))
    return out


# --------------------------------------------------------------------------- render

CSS = """
  html, body { margin: 0; padding: 0; background: #6B6F76; }
  .sheet { font-family: "IBM Plex Sans", "Segoe UI", Arial, sans-serif; font-variant-numeric: tabular-nums;
           width: 794px; height: 1123px; background: #FBFAF7; color: #22262B;
           display: flex; flex-direction: column; overflow: hidden; }
  .serif { font-family: Newsreader, Georgia, "Times New Roman", serif; }
  .page { margin: 22px auto; box-shadow: 0 6px 26px rgba(0,0,0,0.34); width: 794px; height: 1123px; }
  .lbl { font-size: 11px; font-weight: 600; color: #A8814A; letter-spacing: 1.1px; }
  .h2 { font-size: 25px; font-weight: 400; color: #17283F; }
  .sub { font-size: 14px; color: #626B78; }
  .card { border: 1px solid #E6E1D8; background: #FFFFFF; padding: 13px;
          display: flex; flex-direction: column; gap: 8px; }
  .prov { font-size: 11.5px; line-height: 1.34; color: #626B78; }
  table { border-collapse: collapse; width: 100%; }
  @media print {
    @page { size: A4; margin: 0; }
    html, body { background: #FFFFFF; }
    .page { margin: 0; box-shadow: none; page-break-after: always; break-after: page; }
    .page:last-child { page-break-after: auto; break-after: auto; }
  }
"""

ICONS = {
    "metro": '<rect x="5" y="3" width="14" height="14" rx="3.5"></rect><line x1="5" y1="11" x2="19" y2="11"></line>'
             '<circle cx="9" cy="14.2" r="0.9" fill="#A8814A" stroke="none"></circle>'
             '<circle cx="15" cy="14.2" r="0.9" fill="#A8814A" stroke="none"></circle>'
             '<line x1="8.5" y1="17" x2="6.5" y2="21"></line><line x1="15.5" y1="17" x2="17.5" y2="21"></line>',
    "shop": '<path d="M5.6 7.8h12.8l-1.1 12.4H6.7L5.6 7.8z"></path>'
            '<path d="M9.2 7.8V6.2a2.8 2.8 0 0 1 5.6 0v1.6"></path>',
    "walk": '<circle cx="13.6" cy="4.4" r="1.7"></circle>'
            '<path d="M12.9 20.5l1.5-5.4-3.1-2.6 0.9-4.2 3.2 2.9 2.6 0.8"></path>'
            '<path d="M11.2 12.5l-1.6 3.1-2.9 1.4"></path>',
    "road": '<path d="M8.4 3.5L5.2 20.5"></path><path d="M15.6 3.5l3.2 17"></path>'
            '<path d="M12 5.2v2.6"></path><path d="M12 10.7v2.6"></path><path d="M12 16.2v2.6"></path>',
    "building": '<path d="M5 21V6l7-3 7 3v15"></path><path d="M9 9h2M13 9h2M9 13h2M13 13h2M9 17h2M13 17h2"></path>',
}


def icon(kind, size=22):
    return ('<svg width="%d" height="%d" viewBox="0 0 24 24" fill="none" stroke="#A8814A" stroke-width="1.6" '
            'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">%s</svg>' % (size, size, ICONS[kind]))


def img_tag(path, style, alt=""):
    import base64, mimetypes
    mt = mimetypes.guess_type(path)[0] or "image/jpeg"
    b64 = base64.b64encode(open(path, "rb").read()).decode()
    return '<img src="data:%s;base64,%s" alt="%s" style="%s">' % (mt, b64, esc(alt), style)


def fx_hero_focus(rec):
    return rec["facts"].get("hero_focus", "center 38%")


def page1(rec, today):
    im = rec["images"]
    hero = (img_tag(im["hero"], "width:794px;height:248px;object-fit:cover;display:block;"
                    "object-position:%s;" % fx_hero_focus(rec), rec["name"])
            if "hero" in im else '<div style="width:794px;height:248px;background:#E2E0DC;"></div>')
    fx = rec["facts"]

    facts = [("DEVELOPER", fx.get("developer", "\u2014")), ("COMPLETED", fx.get("completed", "\u2014")),
             ("APARTMENTS", fx.get("apartments") or ((str(rec["mix"]["total_units"]) + " units") if rec["mix"] else "\u2014")),
             ("HEIGHT", fx.get("height") or ((str(rec["mix"]["floors"]) + " floors") if rec["mix"] else "\u2014"))]
    fact_html = "".join(
        '<div style="display:flex;flex-direction:column;gap:5px;"><div class="lbl">%s</div>'
        '<div style="font-size:16px;">%s</div></div>' % (esc(k), esc(v)) for k, v in facts)

    rows = ""
    for i, t in enumerate(rec["types"]):
        band = "background:#F1EEE8;" if i % 2 == 0 else ""
        ev = ("%d sale%s" % (t["sales"], "" if t["sales"] == 1 else "s")
              + (" &middot; %d lease%s" % (t["rent_n"], "" if t["rent_n"] == 1 else "s")
                 if t.get("rent_n") else ""))
        rent = "AED " + money(t["rent"]) if t.get("rent") else "&mdash;"
        yld = ("%.1f%%" % t["yield"]) if t.get("yield") else "&mdash;"
        rows += (
            '<div style="display:grid;grid-template-columns:1.45fr 1fr 1.25fr 1.15fr 0.75fr;gap:10px;'
            'padding:14px;align-items:center;%s">'
            '<div style="display:flex;flex-direction:column;gap:3px;">'
            '<div style="font-size:18px;font-weight:600;color:#17283F;">%s</div>'
            '<div style="font-size:11.5px;color:#626B78;">%s</div></div>'
            '<div style="text-align:right;"><div style="font-size:17px;">%s sq ft</div>'
            '<div style="font-size:11.5px;color:#626B78;">%.1f sq m</div></div>'
            '<div style="font-size:19px;font-weight:500;text-align:right;">AED %s</div>'
            '<div style="font-size:19px;font-weight:500;text-align:right;">%s</div>'
            '<div class="serif" style="font-size:26px;color:#A8814A;text-align:right;line-height:1;">%s</div>'
            '</div>' % (band, esc(t["label"]), ev, money(t["median_sqft"]), t["median_sqm"],
                        money(t["median_aed"]), rent, yld))

    cards = ""
    for c in (fx.get("location_cards") or []):
        lines = "".join('<div style="font-size:14px;color:#17283F;line-height:1.3;">%s</div>' % esc(x)
                        for x in c.get("lines", []))
        cards += ('<div class="card">%s<div class="lbl" style="font-size:10.5px;">%s</div>'
                  '<div style="display:flex;flex-direction:column;gap:2px;">%s</div></div>'
                  % (icon(c.get("icon", "building")), esc(c.get("label", "")), lines))
    loc = ('<div style="display:flex;flex-direction:column;gap:13px;">'
           '<div class="serif" style="font-size:20px;color:#17283F;">Where it is</div>'
           '<div style="display:grid;grid-template-columns:repeat(%d,minmax(0,1fr));gap:12px;">%s</div></div>'
           % (min(4, max(1, len(fx.get("location_cards") or [1]))), cards)) if cards else ""

    prov = "".join('<div>%s</div>' % p for p in [
        '<span style="font-weight:600;color:#22262B;">Sale prices</span> &mdash; Dubai Land Department transaction '
        'records for %s%s, %d registered sales, %s to %s.'
        % (esc(rec["name"]),
           " (%s)" % esc(" and ".join(pretty(b) for b in rec["buildings"])) if len(rec["buildings"]) > 1 else "",
           rec["sales_total"], rec["first"], rec["last"]),
        '<span style="font-weight:600;color:#22262B;">Rents</span> &mdash; Ejari registered tenancy contracts%s. '
        'Gross yield is median rent divided by median sale price, before service charge.'
        % (", %s" % rec["rent_window"] if rec.get("rent_window") else ""),
    ] + ([fx["location_note"]] if fx.get("location_note") else []) + [
        'All figures are medians of recorded transactions &mdash; a guide to the market, not a valuation, an asking '
        'price or an offer.'
    ] + ([("This building is mostly commercial: the register also records %s, which are not shown "
           "here because this sheet prices homes." % ", ".join(
               "%d %s sales" % (n, t.lower()) for t, n in
               sorted(rec["commercial"].items(), key=lambda x: -x[1])))]
          if sum(rec.get("commercial", {}).values()) > sum(t["sales"] for t in rec["types"]) else [])
      + ([("%s %s recorded too few sales to quote a median and %s left off this table; page 3 shows "
           "what the building holds." % (
               ", ".join(t["label"] for t in rec["thin_types"]),
               "has" if len(rec["thin_types"]) == 1 else "have",
               "is" if len(rec["thin_types"]) == 1 else "are"))]
          if rec.get("thin_types") else [])
      + list(fx.get("caveats") or []))

    return """
<div class="sheet">
  <div style="width:794px;height:248px;overflow:hidden;flex-shrink:0;">%s</div>
  <div style="flex:1;display:flex;flex-direction:column;padding:28px 50px 0 50px;gap:18px;">
    <div style="display:flex;flex-direction:column;gap:7px;">
      <div style="display:flex;justify-content:space-between;align-items:baseline;gap:20px;">
        <div class="serif" style="font-size:43px;color:#17283F;letter-spacing:-0.4px;line-height:1;">%s</div>
        <div style="font-size:12px;font-weight:600;color:#626B78;letter-spacing:1.6px;white-space:nowrap;">%s</div>
      </div>
      <div style="font-size:16px;color:#626B78;">%s</div>
      <div style="width:68px;height:3px;background:#A8814A;margin-top:5px;"></div>
    </div>
    <div style="display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:18px;">%s</div>
    <div style="display:flex;flex-direction:column;gap:12px;">
      <div style="display:flex;flex-direction:column;gap:3px;">
        <div class="serif h2">What it sells and rents for</div>
        <div class="sub">The median of every transaction on record, by apartment type</div>
      </div>
      <div style="display:grid;grid-template-columns:1.45fr 1fr 1.25fr 1.15fr 0.75fr;background:#17283F;
                  color:#FBFAF7;padding:10px 14px;gap:10px;">
        <div style="font-size:11px;font-weight:600;letter-spacing:1px;">APARTMENT</div>
        <div style="font-size:11px;font-weight:600;letter-spacing:1px;text-align:right;">TYPICAL SIZE</div>
        <div style="font-size:11px;font-weight:600;letter-spacing:1px;text-align:right;">MEDIAN SALE</div>
        <div style="font-size:11px;font-weight:600;letter-spacing:1px;text-align:right;">MEDIAN RENT P.A.</div>
        <div style="font-size:11px;font-weight:600;letter-spacing:1px;text-align:right;">YIELD</div>
      </div>
      <div style="display:flex;flex-direction:column;margin-top:-12px;">%s</div>
    </div>
    %s
  </div>
  <div style="padding:0 50px 24px 50px;display:flex;flex-direction:column;gap:9px;">
    <div style="height:1px;background:#DED9D0;"></div>
    <div class="prov" style="display:flex;flex-direction:column;gap:3px;">%s</div>
    <div style="display:flex;justify-content:space-between;font-size:11px;color:#949AA3;padding-top:2px;">
      <div>__PAGENO__</div><div>Prepared %s</div>
    </div>
  </div>
</div>""" % (hero, esc(rec["name"]), esc((rec.get("master") or "").upper()),
             esc(rec["facts"].get("strapline", "")), fact_html, rows, loc, prov, today)


def page2(rec, today):
    im = rec["images"]
    plans = [(k, lbl) for k, lbl in (("plan_1br", "One bedroom"), ("plan_2br", "Two bedroom"),
                                     ("plan_3br", "Three bedroom")) if k in im]
    caps = rec["facts"].get("captions", {})
    interiors = [(k, k.title()) for k in ("bedroom", "living", "kitchen", "bath", "amenity") if k in im]
    if not interiors:
        # Neutral captions: an unverified render is "Interior", never a room we cannot identify.
        interiors = [(k, caps.get(k, "Interior — developer render"))
                     for k in ("interior_1", "interior_2", "interior_3") if k in im]
    if not plans and not interiors:
        return None

    areas = rec["facts"].get("plan_areas", {})
    pl = ""
    if plans:
        cells = ""
        for k, lbl in plans[:2]:
            note = areas.get(k, "")
            cells += ('<div style="display:flex;flex-direction:column;gap:7px;">'
                      '<div style="border:1px solid #DED9D0;background:#FFF;height:232px;overflow:hidden;">%s</div>'
                      '<div style="display:flex;justify-content:space-between;align-items:baseline;">'
                      '<div style="font-size:15px;font-weight:600;color:#17283F;">%s</div>'
                      '<div style="font-size:13px;color:#626B78;">%s</div></div></div>'
                      % (img_tag(im[k], "width:100%;height:232px;object-fit:contain;display:block;", lbl),
                         esc(lbl), esc(note)))
        pl = ('<div style="display:flex;flex-direction:column;gap:12px;">'
              '<div style="display:flex;flex-direction:column;gap:3px;">'
              '<div class="serif" style="font-size:23px;color:#17283F;">Floor plans</div>'
              '<div class="sub">%s</div></div>'
              '<div style="display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px;">%s</div></div>'
              % (esc(rec["facts"].get("plans_note", "The developer's layouts for the most traded types.")), cells))

    it = ""
    if interiors:
        lead, rest = interiors[0], interiors[1:3]
        block = ('<div style="display:flex;flex-direction:column;gap:6px;">%s'
                 '<div style="font-size:12.5px;color:#626B78;">%s</div></div>'
                 % (img_tag(im[lead[0]], "width:100%;height:186px;object-fit:cover;display:block;", lead[1]),
                    esc(caps.get(lead[0], lead[1]))))
        if rest:
            cells = "".join(
                '<div style="display:flex;flex-direction:column;gap:6px;">%s'
                '<div style="font-size:12.5px;color:#626B78;">%s</div></div>'
                % (img_tag(im[k], "width:100%;height:202px;object-fit:cover;display:block;", lbl),
                   esc(caps.get(k, lbl)))
                for k, lbl in rest)
            block += ('<div style="display:grid;grid-template-columns:repeat(%d,minmax(0,1fr));gap:14px;'
                      'margin-top:4px;">%s</div>' % (len(rest), cells))
        it = ('<div style="display:flex;flex-direction:column;gap:12px;">'
              '<div style="display:flex;flex-direction:column;gap:3px;">'
              '<div class="serif" style="font-size:23px;color:#17283F;">Interiors</div>'
              '<div class="sub">The developer\'s renders of the specification.</div></div>%s</div>' % block)

    note = rec["facts"].get("image_note",
        "Images and floor plans are published by the developer and reproduced here for a buyer considering the "
        "building. Interior images are computer renders showing the intended specification \u2014 they are not "
        "photographs of any particular apartment, and the finish of an individual unit may differ.")

    return """
<div class="sheet">
  <div style="padding:44px 50px 0 50px;display:flex;flex-direction:column;gap:10px;">
    <div style="display:flex;justify-content:space-between;align-items:baseline;gap:20px;">
      <div class="serif" style="font-size:27px;color:#17283F;">%s</div>
      <div style="font-size:12px;font-weight:600;color:#626B78;letter-spacing:1.6px;">LAYOUTS AND FINISH</div>
    </div>
    <div style="height:2px;background:#17283F;"></div>
  </div>
  <div style="flex:1;display:flex;flex-direction:column;padding:26px 50px 0 50px;gap:26px;">%s%s</div>
  <div style="padding:14px 50px 26px 50px;display:flex;flex-direction:column;gap:9px;">
    <div style="height:1px;background:#DED9D0;"></div>
    <div class="prov">%s</div>
    <div style="display:flex;justify-content:space-between;font-size:11px;color:#949AA3;padding-top:2px;">
      <div>__PAGENO__</div><div>Prepared %s</div>
    </div>
  </div>
</div>""" % (esc(rec["name"]), pl, it, note, today)


def page3(rec, today):
    """What else is in the building - the client's "show me options" question.

    Live units where a developer publishes them; otherwise the units register, which says what the
    building holds rather than what is for sale. The distinction is stated on the page, not buried."""
    mix, live = rec["mix"], rec["live_units"]
    if not mix and not live:
        return None

    if live:
        head = "Available now"
        sub = "Units currently offered, from the developer's broker release."
        cols = ["UNIT", "TYPE", "SIZE", "PRICE"]
        body = ""
        for i, u in enumerate(live[:14]):
            band = "background:#F1EEE8;" if i % 2 == 0 else ""
            body += ('<div style="display:grid;grid-template-columns:1fr 1.2fr 1fr 1.2fr;gap:10px;padding:11px 14px;'
                     '%s"><div style="font-size:15px;font-weight:600;color:#17283F;">%s</div>'
                     '<div style="font-size:15px;">%s</div><div style="font-size:15px;text-align:right;">%s</div>'
                     '<div style="font-size:15px;font-weight:500;text-align:right;">%s</div></div>'
                     % (band, esc(u.get("unit", "\u2014")), esc(u.get("type", "\u2014")),
                        esc(u.get("size", "\u2014")), esc(u.get("price", "\u2014"))))
        note = ("Availability moves daily. Confirm the unit and the price with the developer before relying on it. "
                "Source: %s." % esc(rec.get("live_units_source") or "developer broker release"))
    else:
        head = "What the building holds"
        sub = "Every apartment in the building by type, from the Dubai Land Department units register."
        cols = ["APARTMENT", "IN THE BUILDING", "LEVELS", "TYPICAL SIZE"]
        body = ""
        for i, t in enumerate(rec["types"]):
            if not t.get("units_in_building"):
                continue
            band = "background:#F1EEE8;" if i % 2 == 0 else ""
            body += ('<div style="display:grid;grid-template-columns:1fr 1.2fr 1fr 1.2fr;gap:10px;padding:13px 14px;'
                     'align-items:center;%s"><div style="font-size:17px;font-weight:600;color:#17283F;">%s</div>'
                     '<div style="font-size:17px;">%s apartments</div>'
                     '<div style="font-size:15px;color:#626B78;">%s</div>'
                     '<div style="font-size:17px;text-align:right;">%s sq ft</div></div>'
                     % (band, esc(t["label"]), money(t["units_in_building"]),
                        esc(re.sub(r"\s*\(.*?\)", "", str(t.get("levels") or "\u2014"))),
                        money(t["median_sqft"])))
        note = ("This is what the building contains, not a list of apartments for sale \u2014 no live list is "
                "published for a completed building. It shows a buyer what exists and on which levels; ask and we "
                "will check what is actually on the market this week.")

    recent = ""
    if rec.get("recent"):
        rows_html = ""
        for i, r in enumerate(rec["recent"][:6]):
            band = "background:#F1EEE8;" if i % 2 == 0 else ""
            lbl = TYPE_LABEL.get(r["rooms"], r["rooms"])
            when = dt.date.fromisoformat(r["date"]).strftime("%b %Y")
            rows_html += ('<div style="display:grid;grid-template-columns:1fr 1.2fr 1fr 1.2fr;gap:10px;'
                          'padding:10px 14px;align-items:center;%s">'
                          '<div style="font-size:14px;color:#626B78;">%s</div>'
                          '<div style="font-size:15px;font-weight:600;color:#17283F;">%s</div>'
                          '<div style="font-size:15px;text-align:right;">%s sq ft</div>'
                          '<div style="font-size:15px;font-weight:500;text-align:right;">AED %s</div></div>'
                          % (band, esc(when), esc(lbl), money((r["sqm"] or 0) * SQM_TO_SQFT), money(r["aed"])))
        recent = ('<div style="display:flex;flex-direction:column;gap:12px;">'
                  '<div style="display:flex;flex-direction:column;gap:3px;">'
                  '<div class="serif h2">What has actually sold</div>'
                  '<div class="sub">The most recent registered sales in this building.</div></div>'
                  '<div style="display:grid;grid-template-columns:1fr 1.2fr 1fr 1.2fr;background:#17283F;'
                  'color:#FBFAF7;padding:10px 14px;gap:10px;">'
                  '<div style="font-size:11px;font-weight:600;letter-spacing:1px;">DATE</div>'
                  '<div style="font-size:11px;font-weight:600;letter-spacing:1px;">APARTMENT</div>'
                  '<div style="font-size:11px;font-weight:600;letter-spacing:1px;text-align:right;">SIZE</div>'
                  '<div style="font-size:11px;font-weight:600;letter-spacing:1px;text-align:right;">PRICE PAID</div>'
                  '</div><div style="display:flex;flex-direction:column;margin-top:-12px;">%s</div></div>' % rows_html)

    extra = ""
    if mix:
        bits = []
        if mix.get("car_parks"):
            bits.append("%s parking spaces" % money(mix["car_parks"]))
        if (mix.get("asset_classes") or {}).get("retail"):
            bits.append("%d retail units at podium level" % mix["asset_classes"]["retail"])
        if mix.get("floors"):
            bits.append("%d floors" % mix["floors"])
        if bits:
            extra = ('<div style="display:flex;gap:26px;align-items:flex-start;">'
                     '<div style="width:3px;align-self:stretch;background:#DED9D0;flex-shrink:0;"></div>'
                     '<div style="display:flex;flex-direction:column;gap:4px;">'
                     '<div class="serif" style="font-size:20px;color:#17283F;">The building itself</div>'
                     '<div style="font-size:15px;line-height:1.45;">%s.</div></div></div>'
                     % esc(", ".join(bits).capitalize()))

    headers = "".join('<div style="font-size:11px;font-weight:600;letter-spacing:1px;%s">%s</div>'
                      % ("text-align:right;" if i >= 2 else "", c) for i, c in enumerate(cols))

    return """
<div class="sheet">
  <div style="padding:44px 50px 0 50px;display:flex;flex-direction:column;gap:10px;">
    <div style="display:flex;justify-content:space-between;align-items:baseline;gap:20px;">
      <div class="serif" style="font-size:27px;color:#17283F;">%s</div>
      <div style="font-size:12px;font-weight:600;color:#626B78;letter-spacing:1.6px;">OPTIONS IN THIS BUILDING</div>
    </div>
    <div style="height:2px;background:#17283F;"></div>
  </div>
  <div style="flex:1;display:flex;flex-direction:column;padding:26px 50px 0 50px;gap:24px;">
    <div style="display:flex;flex-direction:column;gap:12px;">
      <div style="display:flex;flex-direction:column;gap:3px;">
        <div class="serif h2">%s</div><div class="sub">%s</div>
      </div>
      <div style="display:grid;grid-template-columns:1fr 1.2fr 1fr 1.2fr;background:#17283F;color:#FBFAF7;
                  padding:10px 14px;gap:10px;">%s</div>
      <div style="display:flex;flex-direction:column;margin-top:-12px;">%s</div>
    </div>
    %s
    %s
  </div>
  <div style="padding:14px 50px 26px 50px;display:flex;flex-direction:column;gap:9px;">
    <div style="height:1px;background:#DED9D0;"></div>
    <div class="prov">%s</div>
    <div style="display:flex;justify-content:space-between;font-size:11px;color:#949AA3;padding-top:2px;">
      <div>__PAGENO__</div><div>Prepared %s</div>
    </div>
  </div>
</div>""" % (esc(rec["name"]), esc(head), esc(sub), headers, body, recent, extra, note, today)


def pack_cover(records, today, focus=None):
    """The first page of a shortlist, and the only one a buyer reads twice.

    A pack that just staples three fact sheets together makes the client do the comparison. This
    does it for them: one row per building, on the bedroom type they actually asked about."""
    if not focus:
        counts = {}
        for r in records:
            for t in r["types"]:
                counts[t["key"]] = counts.get(t["key"], 0) + t["sales"]
        focus = max(counts, key=counts.get) if counts else "2 B/R"
    label = TYPE_LABEL.get(focus, focus)

    rows = ""
    for i, r in enumerate(records):
        t = next((x for x in r["types"] if x["key"] == focus), None)
        band = "background:#F1EEE8;" if i % 2 == 0 else ""
        thumb = (img_tag(r["images"]["hero"], "width:86px;height:58px;object-fit:cover;display:block;", r["name"])
                 if "hero" in r["images"] else '<div style="width:86px;height:58px;background:#E2E0DC;"></div>')
        if not t:
            rows += ('<div style="display:grid;grid-template-columns:86px 1.42fr 0.85fr 1.45fr 1.05fr 0.62fr;gap:12px;'
                     'padding:12px 14px;align-items:center;%s">%s'
                     '<div style="font-size:17px;font-weight:600;color:#17283F;">%s</div>'
                     '<div style="grid-column:span 4;font-size:13px;color:#626B78;">No %s recorded in this building</div>'
                     '</div>' % (band, thumb, esc(r["name"]), esc(label)))
            continue
        rent = "AED " + money(t["rent"]) if t.get("rent") else "&mdash;"
        yld = ("%.1f%%" % t["yield"]) if t.get("yield") else "&mdash;"
        rows += ('<div style="display:grid;grid-template-columns:86px 1.42fr 0.85fr 1.45fr 1.05fr 0.62fr;gap:12px;'
                 'padding:12px 14px;align-items:center;%s">%s'
                 '<div style="display:flex;flex-direction:column;gap:2px;">'
                 '<div style="font-size:17px;font-weight:600;color:#17283F;line-height:1.2;">%s</div>'
                 '<div style="font-size:11.5px;color:#626B78;">%s &middot; %d sales</div></div>'
                 '<div style="font-size:15px;text-align:right;white-space:nowrap;">%s sq ft</div>'
                 '<div style="font-size:17px;font-weight:500;text-align:right;white-space:nowrap;">AED %s</div>'
                 '<div style="font-size:15px;text-align:right;white-space:nowrap;">%s</div>'
                 '<div class="serif" style="font-size:24px;color:#A8814A;text-align:right;line-height:1;">%s</div>'
                 '</div>' % (band, thumb, esc(r["name"]), esc(pretty(r.get("master") or r.get("area") or "")),
                             t["sales"], money(t["median_sqft"]), money(t["median_aed"]), rent, yld))

    names = ", ".join(r["name"] for r in records)
    return """
<div class="sheet">
  <div style="padding:58px 50px 0 50px;display:flex;flex-direction:column;gap:9px;">
    <div style="font-size:12px;font-weight:600;color:#A8814A;letter-spacing:1.8px;">SHORTLIST</div>
    <div class="serif" style="font-size:40px;color:#17283F;line-height:1.05;">%s</div>
    <div style="width:68px;height:3px;background:#A8814A;margin-top:6px;"></div>
  </div>
  <div style="flex:1;display:flex;flex-direction:column;padding:34px 50px 0 50px;gap:26px;">
    <div style="display:flex;flex-direction:column;gap:12px;">
      <div style="display:flex;flex-direction:column;gap:3px;">
        <div class="serif h2">Side by side &mdash; %s</div>
        <div class="sub">Median of every recorded transaction in each building, for this apartment type.</div>
      </div>
      <div style="display:grid;grid-template-columns:86px 1.42fr 0.85fr 1.45fr 1.05fr 0.62fr;gap:12px;background:#17283F;
                  color:#FBFAF7;padding:10px 14px;">
        <div></div><div style="font-size:11px;font-weight:600;letter-spacing:1px;">BUILDING</div>
        <div style="font-size:11px;font-weight:600;letter-spacing:1px;text-align:right;">SIZE</div>
        <div style="font-size:11px;font-weight:600;letter-spacing:1px;text-align:right;">MEDIAN SALE</div>
        <div style="font-size:11px;font-weight:600;letter-spacing:1px;text-align:right;">RENT P.A.</div>
        <div style="font-size:11px;font-weight:600;letter-spacing:1px;text-align:right;">YIELD</div>
      </div>
      <div style="display:flex;flex-direction:column;margin-top:-12px;">%s</div>
    </div>
    <div style="display:flex;gap:26px;align-items:flex-start;">
      <div style="width:3px;align-self:stretch;background:#DED9D0;flex-shrink:0;"></div>
      <div style="display:flex;flex-direction:column;gap:4px;">
        <div class="serif" style="font-size:20px;color:#17283F;">How to read this</div>
        <div style="font-size:15px;line-height:1.45;">Each building then has its own pages: what it sells and rents
        for across every apartment type, the floor plans and finish, and what is available or held in the building.
        Yield is annual rent divided by purchase price, before service charge.</div>
      </div>
    </div>
  </div>
  <div style="padding:0 50px 26px 50px;display:flex;flex-direction:column;gap:9px;">
    <div style="height:1px;background:#DED9D0;"></div>
    <div class="prov">Sale prices from Dubai Land Department transaction records; rents from Ejari registered tenancy
    contracts. All figures are medians of recorded transactions &mdash; a guide to the market, not a valuation, an
    asking price or an offer.</div>
    <div style="display:flex;justify-content:space-between;font-size:11px;color:#949AA3;padding-top:2px;">
      <div>__PAGENO__</div><div>Prepared %s</div>
    </div>
  </div>
</div>""" % (esc(names), esc(label), rows, today)


DOC = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>%s</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Newsreader:opsz,wght@6..72,300;6..72,400;6..72,500;6..72,600&family=IBM+Plex+Sans:wght@400;500;600&display=swap">
<style>%s</style></head><body>%s</body></html>"""


def render(records, title, focus=None):
    today = dt.date.today().strftime("%d %B %Y")
    pages = []
    if len(records) > 1:
        pages.append(pack_cover(records, today, focus))
    for rec in records:
        for fn in (page1, page2, page3):
            p = fn(rec, today)
            if p:
                pages.append(p)
    total = len(pages)
    out = ""
    for i, p in enumerate(pages, 1):
        out += '<div class="page">%s</div>' % p.replace("__PAGENO__", "Page %d of %d" % (i, total))
    return DOC % (esc(title), CSS, out), total


def to_pdf(html_path, pdf_path):
    if not os.path.exists(CHROME):
        print("  (no Chrome at %s - HTML only)" % CHROME)
        return False
    subprocess.run([CHROME, "--headless", "--disable-gpu", "--no-sandbox", "--no-pdf-header-footer",
                    "--print-to-pdf=" + os.path.abspath(pdf_path),
                    "file:///" + os.path.abspath(html_path).replace("\\", "/")],
                   capture_output=True, timeout=180)
    return os.path.exists(pdf_path)


# --------------------------------------------------------------------------- cli


def picture_kind(rec):
    """WHICH pictures a sheet has, not just whether it has any.

    has_pictures is a yes/no and some buildings sit between. Churchill Towers publishes three
    exterior views and no interiors or layouts at all; reported as a plain "true" she could hand a
    client a sheet expecting to see rooms. A curator who has looked can state it outright in the
    facts file; otherwise it is derived from which roles were filled."""
    fx = rec.get("facts") or {}
    if fx.get("pictures"):
        return str(fx["pictures"])[:40]
    im = rec.get("images") or {}
    plans = any(k.startswith("plan_") for k in im)
    rooms = any(k in im for k in ("bedroom", "kitchen", "bath", "living"))
    inner = any(k.startswith("interior_") for k in im)
    if plans and (rooms or inner):
        return "layouts and interiors"
    if plans:
        return "layouts"
    if rooms or inner:
        return "interiors"
    if "hero" in im:
        return "exterior only"
    return "none"


TIME_CLAIM_RX = re.compile(r"\b\d+\s*(?:min|mins|minute|minutes|hour|hours)\b", re.I)


def check_location_claims(rec):
    """A walking time is the one number on the sheet with nothing behind it.

    Everything else is sourced: prices and rents come from the Land Department and Ejari, sizes from
    the register, pictures and station names from the developer. A walk time comes from a router
    reading a pin, and for Bellevue every routed estimate said 8-13 minutes from a pin that turned
    out to be wrong. The truth was 5, and it was only known because Kendall had walked it.

    That matters more than a wrong picture because there is no correction between a confident wrong
    number and a client acting on it - she reads the sheet aloud. So: a time may appear on a sheet
    only where a person has checked it and said so in `location_verified`. Station NAMES need no such
    proof and scale to every building; times do not scale and should not pretend to.

    Returns a list of problems."""
    fx = rec.get("facts") or {}
    verified = fx.get("location_verified")
    bad = []
    for card in (fx.get("location_cards") or []):
        for line in card.get("lines", []):
            if TIME_CLAIM_RX.search(str(line)) and not verified:
                bad.append("location card says %r but nothing records who checked it - "
                           "set location_verified in the facts file, or drop the time and keep the name"
                           % line)
    return bad


def verify_pdf(pdf_path, rec, expected_pages):
    """"It rendered" and "it rendered right" are different claims.

    The whole document is built from Python strings and handed to Chrome, so a broken string gives
    a green run and a wrong PDF - and the failure that actually bites is not a crash but a valid,
    EMPTY page. So assert a floor: the page count we meant, real text on every page, and pictures
    on the layouts page when we believe we put some there. Returns a list of problems."""
    bad = []
    try:
        import fitz
        d = fitz.open(pdf_path)
    except Exception as e:
        return ["could not reopen the PDF: %s" % e]
    if d.page_count != expected_pages:
        bad.append("expected %d pages, got %d" % (expected_pages, d.page_count))
    for i, page in enumerate(d, 1):
        text = page.get_text().strip()
        if len(text) < 120:
            bad.append("page %d carries almost no text (%d chars) - probably rendered empty" % (i, len(text)))
        if rec["name"].split()[0].lower() not in text.lower():
            bad.append("page %d does not name the building" % i)
    im = rec.get("images") or {}
    if d.page_count >= 2 and (im.get("plan_1br") or im.get("plan_2br")):
        if not d[1].get_images():
            bad.append("page 2 should carry floor plans but holds no images")
    d.close()
    return bad


def push_sheet(rec, pdf_path, pages):
    """Send a built sheet to the worker so Naj can open and forward it from the app.

    INGEST_TOKEN, not READ_KEY: a separate secret that the owner-key rotation does not touch, so the
    pipeline keeps working through it. The PDF goes up as the raw body - base64 would cost a third
    of the size for nothing, and these are 250-600 KB.
    """
    import urllib.error
    sys.path.insert(0, HERE)
    from build_avail_index import WORKER, env_token
    tok = env_token("INGEST_TOKEN")
    if not tok:
        print("  push skipped: no INGEST_TOKEN")
        return False
    q = urllib.parse.urlencode({"slug": rec["slug"], "name": rec["name"], "pages": pages,
                                "pics": "1" if rec["images"] else "0",
                                "pics_kind": picture_kind(rec)})
    body = open(pdf_path, "rb").read()
    req = urllib.request.Request(WORKER + "/ingest_sheet?" + q, data=body, method="POST",
                                 headers={"X-Azimuth-Ingest": tok, "Content-Type": "application/pdf",
                                          "User-Agent": "najma-market-pulse/1.0"})
    try:
        r = urllib.request.urlopen(req, timeout=900)
        print("  pushed: %s" % r.read().decode("utf-8", "replace")[:160])
        return True
    except urllib.error.HTTPError as e:
        print("  push failed HTTP %s: %s" % (e.code, e.read().decode("utf-8", "replace")[:160]))
    except Exception as e:
        print("  push failed: %s" % e)
    return False


def push_hold(slug, name, reason):
    """Tell the worker WHY a building has no sheet, so the app greys the button and says which.
    "No pictures yet" and "only two registered sales" are different problems and she will ask."""
    sys.path.insert(0, HERE)
    from build_avail_index import WORKER, env_token
    tok = env_token("INGEST_TOKEN")
    if not tok:
        return False
    q = urllib.parse.urlencode({"slug": slug, "name": name, "hold": reason})
    req = urllib.request.Request(WORKER + "/ingest_sheet?" + q, data=b"", method="POST",
                                 headers={"X-Azimuth-Ingest": tok, "User-Agent": "najma-market-pulse/1.0"})
    try:
        urllib.request.urlopen(req, timeout=120)
        return True
    except Exception:
        return False


def write(records, name, title, focus=None):
    os.makedirs(SHEETS, exist_ok=True)
    doc, n = render(records, title, focus)
    hp = os.path.join(SHEETS, "%s.html" % name)
    open(hp, "w", encoding="utf-8").write(doc)
    pp = os.path.join(SHEETS, "%s.pdf" % name)
    ok = to_pdf(hp, pp)
    size = os.path.getsize(pp) / 1024 if ok else 0
    print("  %s  -  %d pages, %s" % (name, n, "%.0f KB PDF" % size if ok else "HTML only"))
    return hp, (pp if ok else None), n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--building")
    ap.add_argument("--pack", nargs="+")
    ap.add_argument("--pack-name", default=None)
    ap.add_argument("--type", default=None,
                    help="bedroom type the client asked for, e.g. \"2 B/R\" - sets the comparison page")
    ap.add_argument("--district")
    ap.add_argument("--list-ready", action="store_true")
    ap.add_argument("--medians", action="store_true",
                    help="rebuild the true project-level median cache from the raw Land Department export")
    ap.add_argument("--walk")
    ap.add_argument("--at", help="lat,lon for --walk")
    ap.add_argument("--min-sales", type=int, default=20)
    ap.add_argument("--force", action="store_true", help="build even if the building misses the bar")
    ap.add_argument("--push", action="store_true", help="send the built sheet up to the worker for the app")
    a = ap.parse_args()

    if a.medians:
        build_medians()
        if not (a.building or a.pack):
            return 0

    if a.walk:
        if not a.at:
            print("--walk needs --at lat,lon"); return 2
        lat, lon = [float(x) for x in a.at.split(",")]
        print("Walking routes from %.6f, %.6f:" % (lat, lon))
        for w in walk_times(lat, lon):
            print("  %-42s %5d m  %2d min" % (w["name"], w["walk_m"], w["walk_min"]))
        return 0

    if a.list_ready:
        ready, held = [], []
        seen = set()
        for d in ([a.district] if a.district else districts()):
            p = os.path.join(DLD, "tx_buildings_%s.json" % d)
            if not os.path.exists(p):
                continue
            for b in json.load(open(p, encoding="utf-8")).get("buildings", []):
                nm = b.get("project")
                if not nm or slugify(nm) in seen:
                    continue
                seen.add(slugify(nm))
                rec, err = build_record(nm, d, a.min_sales)
                if not rec:
                    continue
                (ready if rec["ready"] else held).append((nm, d, rec))
        pics_only = [x for x in held if x[2]["not_ready_because"] == ["no pictures held"]]
        thin = [x for x in held if x not in pics_only]
        print("READY (%d) - has the numbers AND the pictures:" % len(ready))
        for nm, d, r in sorted(ready, key=lambda x: -x[2]["sales_total"]):
            print("  %-42s %-22s %5d sales  %d pictures" % (nm[:42], d, r["sales_total"], len(r["images"])))

        print()
        print("WAITING ON PICTURES ONLY (%d) - these clear the sales bar; a brochure pass is the"
              % len(pics_only))
        print("only thing between them and a sheet. This is the work queue, deepest first:")
        for nm, d, r in sorted(pics_only, key=lambda x: -x[2]["sales_total"])[:25]:
            print("  %-42s %-22s %5d sales" % (nm[:42], d, r["sales_total"]))
        if len(pics_only) > 25:
            print("  ... and %d more" % (len(pics_only) - 25))

        print()
        print("TOO THIN TO QUOTE (%d) - under %d recorded sales, pictures would not help."
              % (len(thin), a.min_sales))
        return 0

    names = a.pack or ([a.building] if a.building else [])
    if not names:
        print("give --building NAME, --pack NAME NAME, --list-ready or --walk"); return 2

    records = []
    for nm in names:
        rec, err = build_record(nm, a.district, a.min_sales)
        if err:
            print("  %s: %s" % (nm, err)); continue
        if not rec["ready"] and not a.force:
            why = "; ".join(rec["not_ready_because"])
            print("  %s: held - %s" % (nm, why))
            if a.push:
                push_hold(rec["slug"], rec["name"], why)
            print("    (use --force to build anyway)")
            continue
        records.append(rec)
    if not records:
        return 1

    if a.pack and len(records) > 1:
        nm = a.pack_name or "pack_" + "_".join(slugify(r["name"])[:14] for r in records)
        print("Shortlist pack:")
        _h, _p, _n = write(records, nm, "Shortlist \u2014 " + ", ".join(r["name"] for r in records), a.type)
        if a.push and _p:
            push_sheet({"slug": nm, "name": "Shortlist", "images": {"hero": 1}}, _p, _n)
    else:
        for r in records:
            _lc = check_location_claims(r)
            for b in _lc:
                print("  CHECK FAILED: %s" % b)
            if _lc:
                print("  not built - fix the facts file first")
                continue
            print("Client sheet:")
            _h, _p, _n = write([r], r["slug"], "%s \u2014 fact sheet" % r["name"])
            if _p:
                _bad = verify_pdf(_p, r, _n)
                for b in _bad:
                    print("  CHECK FAILED: %s" % b)
                if _bad:
                    print("  not pushed - fix the sheet first")
                    continue
                print("  checked: %d pages, %s" % (_n, picture_kind(r)))
            if a.push and _p:
                push_sheet(r, _p, _n)
    return 0


if __name__ == "__main__":
    sys.exit(main())
