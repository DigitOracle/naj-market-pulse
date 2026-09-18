"""A developer brief: the client fact sheets for a developer's buildings, plus what only we can show.

Kendall, 18 Sep 2026, before Naj met Ellington: the plain pack "isn't showing anything other people do
not already know". Every agent in Dubai can quote a median price. This adds what they can't:

  * a developer cover - the developer's 2026 in numbers, and its buildings ranked by sales;
  * per building, a MARKET & NEIGHBOURHOOD page - price per sq ft month by month against its own
    district, sales per month, off-plan share, and what sits around it: metro, schools with their
    KHDA rating, hospital, mall, supermarket, park or beach, EV chargers.

Rules carried over from the sheets, because a developer's own team is the hardest audience:
  * distances are STRAIGHT-LINE and say so - never walking minutes (Bellevue: every routed estimate
    said 8-13 min, the truth was 5);
  * a building with no mapped position gets no neighbourhood, not a guessed one;
  * everything is the Land Department register or a government register, and says which.

The existing sheet pages are reused unchanged from build_client_sheet.py.

Usage: python scripts/build_developer_brief.py --developer Ellington --buildings "ELTIERA VIEWS" ... [--push]
"""
import argparse, datetime as dt, io, json, math, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
import build_client_sheet as S  # noqa: E402

GOLD, NAVY, INK, MUTED, RULE = "#A8814A", "#17283F", "#22262B", "#626B78", "#E6E1D8"
SQM = 10.7639


def db():
    import duckdb
    return duckdb.connect(os.path.join(ROOT, "naj.duckdb"), read_only=True)


PSF = "TRY_CAST(TRANS_VALUE AS DOUBLE) / NULLIF(TRY_CAST(ACTUAL_AREA AS DOUBLE) * %s, 0)" % SQM
SALE = "PROCEDURE_EN LIKE 'Sell%' AND PROP_TYPE_EN = 'Unit'"


def monthly(con, where, args):
    return con.execute(
        "select substr(INSTANCE_DATE,1,7) m, count(*) n, median(%s) psf from transactions "
        "where %s and %s group by 1 order by 1" % (PSF, SALE, where), args).fetchall()


def building_stats(con, project):
    p = project.upper().strip()
    row = con.execute(
        "select AREA_EN, count(*), median(%s), sum(TRY_CAST(TRANS_VALUE AS DOUBLE)), "
        "avg(case when IS_OFFPLAN_EN ilike 'off%%' then 1.0 else 0 end), "
        "mode(NEAREST_METRO_EN), mode(NEAREST_MALL_EN), mode(NEAREST_LANDMARK_EN), "
        "min(INSTANCE_DATE), max(INSTANCE_DATE) "
        "from transactions where upper(trim(PROJECT_EN)) = ? and %s group by 1 order by 2 desc limit 1"
        % (PSF, SALE), [p]).fetchone()
    if not row:
        return None
    area = row[0]
    # The district WITHOUT this building. Eltiera Views is 617 sales of its own district, so "the
    # district" was largely the building itself and "-1% against its district" compared it with
    # itself. A comparison has to be against something else.
    dist = con.execute("select median(%s), count(*) from transactions where AREA_EN = ? "
                       "and upper(trim(PROJECT_EN)) <> ? and %s" % (PSF, SALE), [area, p]).fetchone()
    return {"area": area, "n": row[1], "psf": row[2], "value": row[3], "offplan": row[4],
            "dld_metro": row[5], "dld_mall": row[6], "dld_landmark": row[7], "first": row[8][:10],
            "last": row[9][:10], "area_psf": dist[0], "area_n": dist[1],
            "m_bld": monthly(con, "upper(trim(PROJECT_EN)) = ?", [p]),
            "m_area": monthly(con, "AREA_EN = ? and upper(trim(PROJECT_EN)) <> ?", [area, p])}


# --------------------------------------------------------------------------- neighbourhood

def position(project):
    """lon/lat from the twin anchors, or None. Never geocoded - a guessed pin is worse than none."""
    import glob
    k = S.slugify(project)
    for f in glob.glob(os.path.join(ROOT, "data", "names", "anchors_*.json")):
        try:
            for a in json.load(io.open(f, encoding="utf-8")).get("anchors", []):
                if S.slugify(a.get("dev_project") or "") == k and a.get("lat") and a.get("lon"):
                    return float(a["lat"]), float(a["lon"])
        except Exception:
            continue
    return None


def km(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(h))


RATING = ["outstanding", "very good", "good", "acceptable", "weak", "very weak"]

# Curriculum groups, from the KHDA register's own curriculum field.
CURRICULA = [("British", ("uk",)), ("American", ("american", "us/")), ("IB", ("international baccalaureate", "/ib")),
             ("Indian", ("indian",))]
# Grocers by brand, as the register names them. Grouped by what a buyer asks for, and the brands are
# printed on the card so nobody has to trust the grouping.
GROCERS = [("Spinneys & Waitrose", ("spinneys", "waitrose")), ("Carrefour", ("carrefour", "geant", "géant")),
           ("Lulu, Nesto, Al Maya, West Zone", ("lulu", "nesto", "al maya", "west zone"))]

SVG = {
    "metro": '<rect x="5" y="3" width="14" height="14" rx="3.5"/><line x1="5" y1="11" x2="19" y2="11"/>'
             '<line x1="8.5" y1="17" x2="6.5" y2="21"/><line x1="15.5" y1="17" x2="17.5" y2="21"/>',
    "school": '<path d="M2 9l10-4 10 4-10 4z"/><path d="M6 11v4c0 1.6 2.7 3 6 3s6-1.4 6-3v-4"/>',
    "cart": '<path d="M3 4h2l2.4 11h11.2L21 8H7"/><circle cx="9" cy="19" r="1.5"/><circle cx="17" cy="19" r="1.5"/>',
    "hospital": '<rect x="4" y="3" width="16" height="18" rx="1.5"/><path d="M12 7v6M9 10h6"/>',
    "mall": '<path d="M5 8h14l-1 12H6z"/><path d="M9 8V6a3 3 0 0 1 6 0v2"/>',
    "park": '<path d="M12 3l5 7h-3l4 5H6l4-5H7z"/><path d="M12 15v6"/>',
    "beach": '<circle cx="17" cy="7" r="2.5"/><path d="M2 15c2-1.5 4-1.5 6 0s4 1.5 6 0 4-1.5 6 0"/>',
    "ev": '<rect x="4" y="3" width="9" height="18" rx="1.5"/><path d="M9 12l-2 3h3l-2 3"/><path d="M17 8v6a2 2 0 0 0 4 0V9l-2-3"/>',
    "walk": '<circle cx="13.6" cy="4.4" r="1.7"/><path d="M12.9 20.5l1.5-5.4-3.1-2.6 0.9-4.2 3.2 2.9 2.6 0.8"/>',
}


def ico(kind, size=20):
    return ('<svg width="%d" height="%d" viewBox="0 0 24 24" fill="none" stroke="%s" stroke-width="1.7" '
            'stroke-linecap="round" stroke-linejoin="round">%s</svg>' % (size, size, GOLD, SVG[kind]))


def icard(kind, big, label, note=""):
    return ('<div style="flex:1;border:1px solid %s;background:#FFF;padding:8px 9px;display:flex;gap:8px;'
            'align-items:flex-start;min-width:0;">%s<div style="min-width:0;"><div class="serif" '
            'style="font-size:19px;color:%s;line-height:1.05;">%s</div><div style="font-size:11px;color:%s;'
            'line-height:1.25;">%s</div>%s</div></div>'
            % (RULE, ico(kind), NAVY, big, INK, S.esc(label),
               ('<div style="font-size:10px;color:%s;line-height:1.2;">%s</div>' % (MUTED, S.esc(note))) if note else ""))


def around(pos):
    items = json.load(io.open(os.path.join(ROOT, "data", "board", "amenities.json"), encoding="utf-8"))["items"]
    near = [(km(pos, (i["lat"], i["lon"])), i) for i in items if i.get("lat") and i.get("lon")]

    def nearest(kind, n=1, within=None):
        xs = sorted(((d, i) for d, i in near if i["k"] == kind and (within is None or d <= within)),
                    key=lambda di: di[0])
        return xs[:n]

    schools = [(d, i) for d, i in near if i["k"] == "school" and d <= 3.0]

    def srank(di):
        x = (di[1].get("x") or "").lower()
        r = next((n for n, w in enumerate(RATING) if x.startswith(w)), len(RATING))
        return (r, di[0])
    def curr(i):
        return (i.get("x") or "").split("·")[-1].strip().lower()
    by_curr = [(lab, sum(1 for d, i in schools if any(k in curr(i) for k in keys))) for lab, keys in CURRICULA]
    groc = [(lab, sum(1 for d, i in near if i["k"] == "supermarket" and d <= 3.0
                      and any(k in (i.get("br") or i.get("x") or i["n"]).lower() for k in keys)))
            for lab, keys in GROCERS]
    return {"by_curr": by_curr, "groc": groc,
            "metro": nearest("metro", 2), "schools": sorted(schools, key=srank)[:5],
            "n_schools": len(schools), "hospital": nearest("hospital"), "mall": nearest("mall"),
            "supermarket": nearest("supermarket"), "park": nearest("park"),
            "beach": nearest("beach", within=5.0), "ev": len([1 for d, i in near if i["k"] == "ev" and d <= 1.5])}


# --------------------------------------------------------------------------- charts (inline SVG)

def line_chart(series, w=690, h=190, fmt=lambda v: "{:,.0f}".format(v)):
    """series: [(label, colour, [(month, value), ...]), ...] sharing one x axis of months."""
    months = sorted({m for _, _, pts in series for m, v in pts if v})
    vals = [v for _, _, pts in series for m, v in pts if v]
    if len(months) < 2 or not vals:
        return ""
    lo, hi = min(vals), max(vals)
    pad = (hi - lo) * 0.15 or hi * 0.1
    lo, hi = max(0, lo - pad), hi + pad
    L, R, T, B = 56, 12, 14, 28
    X = lambda i: L + i * (w - L - R) / (len(months) - 1)
    Y = lambda v: T + (hi - v) * (h - T - B) / (hi - lo)
    g = []
    for t in range(4):
        v = lo + (hi - lo) * t / 3
        g.append('<line x1="%d" x2="%d" y1="%.1f" y2="%.1f" stroke="%s"/>'
                 '<text x="%d" y="%.1f" font-size="10" fill="%s" text-anchor="end">%s</text>'
                 % (L, w - R, Y(v), Y(v), RULE, L - 6, Y(v) + 3, MUTED, fmt(v)))
    for i, m in enumerate(months):
        g.append('<text x="%.1f" y="%d" font-size="10" fill="%s" text-anchor="middle">%s</text>'
                 % (X(i), h - 9, MUTED, dt.date(int(m[:4]), int(m[5:]), 1).strftime("%b")))
    for label, col, pts in series:
        d = {m: v for m, v in pts if v}
        xy = [(X(i), Y(d[m])) for i, m in enumerate(months) if m in d]
        g.append('<polyline fill="none" stroke="%s" stroke-width="2.4" points="%s"/>'
                 % (col, " ".join("%.1f,%.1f" % p for p in xy)))
        g.extend('<circle cx="%.1f" cy="%.1f" r="2.8" fill="%s"/>' % (x, y, col) for x, y in xy)
    return '<svg width="%d" height="%d" role="img">%s</svg>' % (w, h, "".join(g))


def bar_chart(pts, w=690, h=150, colour=NAVY):
    """pts: [(label, value), ...] vertical bars, value printed on top."""
    if not pts:
        return ""
    top = max(v for _, v in pts) or 1
    L, B, T = 8, 24, 16
    bw = (w - 2 * L) / len(pts)
    g = []
    for i, (lab, v) in enumerate(pts):
        bh = (h - B - T) * v / top
        x = L + i * bw
        g.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" fill="%s"/>'
                 '<text x="%.1f" y="%.1f" font-size="10" fill="%s" text-anchor="middle">%d</text>'
                 '<text x="%.1f" y="%d" font-size="10" fill="%s" text-anchor="middle">%s</text>'
                 % (x + bw * 0.18, h - B - bh, bw * 0.64, bh, colour, x + bw / 2, h - B - bh - 4, INK, v,
                    x + bw / 2, h - 8, MUTED, S.esc(lab)))
    return '<svg width="%d" height="%d" role="img">%s</svg>' % (w, h, "".join(g))


DONUT = ["#17283F", "#A8814A", "#5B7A99", "#C9B08A", "#7A8B6F", "#8E6C8A", "#B5B9C0", "#D8CFC0", "#4E3B2A", "#9FB7C9"]
# DLD district -> DEWA community, where the names differ. Silicon Oasis is part of the Nadd Hessa
# community in DEWA's register, and the page says so rather than presenting it as Silicon Oasis.
DEWA_COMMUNITY = {"SILICON OASIS": "NADD HESSA"}


def resident_mix(area):
    """District resident mix from DEWA's customer register (data/internal/community_resident_mix.json).

    That file is marked 'Kendall and Naj only'. Kendall chose, on 18 Sep 2026 before the Ellington
    meeting, to show it in a developer brief. It is shown at DISTRICT level only, labelled as what it
    measures - the nationality of electricity ACCOUNT HOLDERS, not every resident and not buyers - and
    never for a single building."""
    p = os.path.join(ROOT, "data", "internal", "community_resident_mix.json")
    try:
        d = json.load(io.open(p, encoding="utf-8"))
    except Exception:
        return None
    want = DEWA_COMMUNITY.get(str(area).upper().strip(), str(area).upper().strip())
    return next((c for c in d.get("communities", []) if c.get("name", "").upper() == want), None)


def donut(regions, size=132):
    w = 22
    r = size / 2 - w / 2 - 1
    cx = cy = size / 2
    tot = sum(x["pct"] for x in regions) or 1
    a0, g = -math.pi / 2, []
    for n, x in enumerate(regions):
        a1 = a0 + 2 * math.pi * x["pct"] / tot
        large = 1 if a1 - a0 > math.pi else 0
        g.append('<path d="M%.2f %.2f A%.2f %.2f 0 %d 1 %.2f %.2f" fill="none" stroke="%s" stroke-width="%d"/>'
                 % (cx + r * math.cos(a0), cy + r * math.sin(a0), r, r, large,
                    cx + r * math.cos(a1 - 0.012), cy + r * math.sin(a1 - 0.012), DONUT[n % len(DONUT)], w))
        a0 = a1
    return '<svg width="%d" height="%d" role="img">%s</svg>' % (size, size, "".join(g))


def hbar_chart(pts, w=690, row=26, colour=NAVY, fmt=lambda v: "{:,}".format(v)):
    if not pts:
        return ""
    top = max(v for _, v in pts) or 1
    lw = 210
    g = []
    for i, (lab, v) in enumerate(pts):
        y = i * row
        g.append('<text x="0" y="%d" font-size="12" fill="%s">%s</text>'
                 '<rect x="%d" y="%d" width="%.1f" height="%d" fill="%s"/>'
                 '<text x="%.1f" y="%d" font-size="11" fill="%s">%s</text>'
                 % (y + 16, INK, S.esc(lab), lw, y + 5, (w - lw - 70) * v / top, row - 10, colour,
                    lw + (w - lw - 70) * v / top + 6, y + 16, MUTED, fmt(v)))
    return '<svg width="%d" height="%d" role="img">%s</svg>' % (w, row * len(pts), "".join(g))


# --------------------------------------------------------------------------- pages

def shell(title, eyebrow, body, today):
    return ("""<div class="sheet"><div style="padding:34px 44px 0 44px;flex:1;display:flex;flex-direction:column;gap:14px;">
<div><div class="lbl">%s</div><div class="serif" style="font-size:32px;color:%s;line-height:1.1;margin-top:4px;">%s</div>
<div style="width:52px;height:3px;background:%s;margin-top:10px;"></div></div>%s</div>
<div style="padding:0 44px 22px 44px;display:flex;justify-content:space-between;font-size:11px;color:%s;">
<span>__PAGENO__</span><span>Prepared %s</span></div></div>"""
            % (S.esc(eyebrow), NAVY, S.esc(title), GOLD, body, MUTED, today))


def stat(label, value, note=""):
    return ('<div class="card" style="flex:1;gap:3px;"><div class="lbl">%s</div>'
            '<div class="serif" style="font-size:24px;color:%s;">%s</div>'
            '<div style="font-size:11px;color:%s;">%s</div></div>' % (S.esc(label), NAVY, value, MUTED, S.esc(note)))


def developer_cover(dev, stats, ranked, today):
    tot_n = sum(s["n"] for s in stats.values())
    tot_v = sum(s["value"] or 0 for s in stats.values())
    # The 2026 register we hold is the OFF-PLAN register: 79,517 off-plan sales against 747 ready ones
    # corpus-wide, because resales of completed homes are not in it. So "100% sold off-plan" would
    # describe our dataset, not the developer - and it was about to be printed for the developer's own
    # team. Every figure here is labelled as off-plan registrations instead.
    wpsf = sorted(s["psf"] for s in stats.values() for _ in range(min(s["n"], 1)) if s["psf"])
    body = ('<div class="sub" style="max-width:620px;">What the Dubai Land Department register shows for %s in 2026: '
            'off-plan sales registered January to %s, and the four buildings in this brief.</div>'
            % (S.esc(dev), S.esc(dt.date.today().strftime("%B"))))
    body += '<div style="display:flex;gap:10px;">%s%s%s</div>' % (
        stat("Off-plan sales, 2026", "{:,}".format(tot_n), "registered, across %d buildings" % len(ranked)),
        stat("Value registered", "AED %.2f bn" % (tot_v / 1e9), "sum of those sale prices"),
        stat("Typical price per sq ft", "AED {:,.0f}".format(wpsf[len(wpsf) // 2]) if wpsf else "-",
             "middle of its buildings' medians"))
    body += ('<div class="h2 serif" style="margin-top:6px;">Its buildings, by 2026 sales</div>'
             '<div class="sub" style="margin-top:-8px;">Off-plan sales registered per building, this year.</div>')
    body += hbar_chart([(n, v) for n, v in ranked[:12]])
    body += ('<div class="prov" style="margin-top:auto;border-top:1px solid %s;padding-top:8px;">'
             '<b>Source</b> - Dubai Land Department transaction register, off-plan sales of units, 1 Jan to %s. '
             'Buildings are matched by their registered project name. This brief does not include rents, '
             'which Ejari does not yet show for these projects.</div>' % (RULE, stats and max(s["last"] for s in stats.values())))
    return shell(dev, "DEVELOPER BRIEF", body, today)


def ready_vs_offplan(area):
    """2026 district sales per sq ft, ready (Existing Properties) vs off-plan, from the full DLD register
    (najma.duckdb g_dld__transactions, PROD pull 18 Sep 2026). None if either side has under 20 sales."""
    import duckdb
    a = DEWA_COMMUNITY.get(str(area).upper().strip(), str(area).upper().strip())
    try:
        c = duckdb.connect(os.path.join(ROOT, "data", "graph", "najma.duckdb"), read_only=True)
        rows = dict((r[0], (r[1], r[2])) for r in c.execute(
            "select reg_type_en, count(*), median(meter_sale_price)/10.7639 from g_dld__transactions "
            "where trans_group_en='Sales' and year(instance_date)=2026 and upper(area_name_en)=? "
            "and meter_sale_price > 0 group by 1", [a]).fetchall())
        c.close()
    except Exception as e:
        print("  ready/off-plan unavailable: %s" % e)
        return None
    r, o = rows.get("Existing Properties"), rows.get("Off-Plan Properties")
    if not r or not o or r[0] < 20 or o[0] < 20:
        return None
    return {"ready": r[1], "ready_n": r[0], "off": o[1], "off_n": o[0], "area": a}


def market_page(rec, st, pos, today):
    name = rec["name"]
    prem = (st["psf"] / st["area_psf"] - 1) * 100 if st["psf"] and st["area_psf"] else None
    body = '<div style="display:flex;gap:10px;">%s%s%s%s</div>' % (
        stat("Price per sq ft, 2026", "AED {:,.0f}".format(st["psf"]), "median of %d off-plan sales" % st["n"]),
        stat("Against its district", ("%+d%%" % round(prem)) if prem is not None else "-",
             "vs the rest of %s, AED {:,.0f}".format(st["area_psf"] or 0) % S.pretty(st["area"])),
        stat("Selling at", "%.0f a month" % (st["n"] / max(1, len(st["m_bld"]))),
             "average, since its first 2026 sale on %s" % st["first"]),
        (lambda rv: stat("Ready vs off-plan", "%+d%%" % round((rv["off"] / rv["ready"] - 1) * 100),
                         "{} 2026: ready AED {:,.0f} ({:,} sales), off-plan AED {:,.0f} ({:,})".format(
                             S.pretty(rv["area"]), rv["ready"], rv["ready_n"], rv["off"], rv["off_n"])) if rv else "")(ready_vs_offplan(st["area"])))
    body += ('<div><div class="lbl" style="margin-bottom:4px;">PRICE PER SQ FT, MONTH BY MONTH</div>'
             '<div style="font-size:11px;color:%s;margin-bottom:2px;">'
             '<span style="color:%s;">&#9632;</span> %s &nbsp; <span style="color:%s;">&#9632;</span> rest of %s</div>%s</div>'
             % (MUTED, NAVY, S.esc(name), GOLD, S.esc(S.pretty(st["area"])),
                line_chart([(name, NAVY, [(m, p) for m, n, p in st["m_bld"] if n >= 3]),
                            ("district", GOLD, [(m, p) for m, n, p in st["m_area"]])], h=110)))
    body += ('<div><div class="lbl" style="margin-bottom:4px;">SALES PER MONTH</div>%s</div>'
             % bar_chart([(dt.date(int(m[:4]), int(m[5:]), 1).strftime("%b"), n) for m, n, p in st["m_bld"]], h=70))
    if pos:
        a = around(pos)
        walks = []
        try:
            walks = S.walk_times(pos[0], pos[1])
        except Exception as e:
            print("  walk routing unavailable: %s" % e)
        near_km = lambda xs: ("%.1f km" % xs[0][0]) if xs else "none nearby"
        near_nm = lambda xs: xs[0][1]["n"][:34] if xs else ""
        row = lambda cards: '<div style="display:flex;gap:7px;">%s</div>' % "".join(cards)
        # Metro: a ROUTED walking distance where the router answers, straight-line otherwise, and each
        # card says which. Never minutes - a walking time needs someone who has walked it.
        # A routed walk over 2 km is not a walk (Hillgate routed 27 km to Creek): fall back to straight line.
        mcards = [icard("walk", "%d m" % w["walk_m"], w["name"][:32], "walking route") for w in walks[:2] if w["walk_m"] <= 2000]
        if not mcards:
            mcards = [icard("metro", "%.1f km" % d, i["n"][:32], "straight line") for d, i in a["metro"]]
        body += '<div><div class="lbl" style="margin-bottom:4px;">GETTING AROUND</div>%s</div>' % row(
            mcards + [icard("mall", near_km(a["mall"]), near_nm(a["mall"]) or "Mall", "nearest mall"),
                      icard("hospital", near_km(a["hospital"]), near_nm(a["hospital"]) or "Hospital", "nearest hospital")])
        body += ('<div><div class="lbl" style="margin-bottom:4px;">SCHOOLS WITHIN 3 KM &middot; %d IN ALL</div>%s</div>'
                 % (a["n_schools"], row([icard("school", str(n), lab + " curriculum") for lab, n in a["by_curr"]])))
        body += '<div><div class="lbl" style="margin-bottom:4px;">GROCERIES WITHIN 3 KM</div>%s</div>' % row(
            [icard("cart", str(n), lab) for lab, n in a["groc"]] +
            [icard("park", near_km(a["park"]), "Nearest park")])
        top = [(d, i) for d, i in a["schools"] if (i.get("x") or "").lower().startswith(("outstanding", "very good"))][:3]
        if top:
            body += ('<div style="font-size:11.5px;color:%s;">Top-rated nearby: %s</div>'
                     % (MUTED, " &middot; ".join("<b style='color:%s'>%s</b> (%s, %.1f km)"
                                                 % (INK, S.esc(i["n"][:38]), S.esc(i.get("x") or ""), d) for d, i in top)))
        extra = [icard("beach", near_km(a["beach"]), "Nearest beach", "within 5 km") if a["beach"] else "",
                 icard("ev", str(a["ev"]), "EV charging points", "within 1.5 km")]
    else:
        extra = []
    # Who lives in the district: DEWA account holders by nationality. District-wide, never this building or its buyers.
    rm = resident_mix(st["area"])
    if rm:
        comm = rm["name"]
        leg = "".join('<div style="display:flex;gap:6px;align-items:baseline;font-size:11px;margin:1px 0;">'
                      '<span style="color:%s;font-size:12px;">&#9632;</span><b style="color:%s;min-width:30px;">%d%%</b>'
                      '<span style="color:%s;">%s <span style="color:%s;">%s</span></span></div>'
                      % (DONUT[i % len(DONUT)], INK, round(r["pct"]), INK, S.esc(r["name"]), MUTED,
                         S.esc(", ".join(c for c, p in (r.get("countries") or [])[:3])))
                      for i, r in enumerate(rm["regions"]))
        alias = "" if comm.upper() == str(st["area"]).upper() else " %s is part of the %s community." % (
            S.esc(S.pretty(st["area"])), S.esc(S.pretty(comm)))
        body += ('<div><div class="lbl" style="margin-bottom:4px;">WHO LIVES IN %s</div>'
                 '<div style="display:flex;gap:12px;align-items:center;">%s<div style="flex:1;">%s'
                 '<div style="font-size:9.5px;color:%s;margin-top:3px;">DEWA electricity account holders by nationality, '
                 'district-wide (%s accounts) - not this building, not its buyers.%s</div></div>%s</div></div>'
                 % (S.esc(S.pretty(comm).upper()), donut(rm["regions"], size=108), leg, MUTED,
                    "{:,}".format(rm.get("accounts") or 0), alias,
                    '<div style="display:flex;flex-direction:column;gap:6px;width:170px;">%s</div>' % "".join(extra)))
    elif extra:
        body += '<div style="display:flex;gap:7px;">%s</div>' % "".join(extra)
    if pos:
        loc_note = ("Walks routed on OpenStreetMap paths, not timed; other distances straight-line. "
                    "KHDA, RTA, DHA, DEWA, OpenChargeMap.")
    else:
        real = lambda v: v if v and any(c.isalpha() for c in str(v)) else None
        facts = [("nearest metro", real(st["dld_metro"])), ("nearest mall", real(st["dld_mall"]))]
        facts = [(k, v) for k, v in facts if v]
        said = (" The Land Department records its " + " and its ".join("%s as <b>%s</b>" % (k, S.esc(v)) for k, v in facts)
                + ".") if facts else ""
        body += ('<div class="card"><div class="lbl">AROUND THE BUILDING</div><div class="sub">This building is not '
                 'yet placed on our map, so we show no distances rather than guess them.%s</div></div>' % said)
        loc_note = "Nearest metro and mall as recorded by the Land Department on this building's sales."
    body += ('<div class="prov" style="margin-top:auto;border-top:1px solid %s;padding-top:8px;"><b>Prices</b> - Dubai Land '
             'Department register, off-plan sales of units, %s to %s; months with fewer than three sales are left off the '
             'building line. %s</div>' % (RULE, st["first"], st["last"], loc_note))
    return shell(name, "MARKET & NEIGHBOURHOOD", body, today)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--developer", required=True)
    ap.add_argument("--buildings", nargs="+", required=True)
    ap.add_argument("--name", default=None)
    ap.add_argument("--push", action="store_true")
    a = ap.parse_args()
    today = dt.date.today().strftime("%d %B %Y")
    con = db()

    # the developer's whole 2026, from its own card list
    bd = json.load(io.open(os.path.join(ROOT, "data", "board", "board_devs.json"), encoding="utf-8"))
    names = [p["name"] for d in bd["developers"] if d["name"].lower().startswith(a.developer.lower())
             for p in d.get("properties") or []]
    ranked = []
    for n in names:
        c = con.execute("select count(*) from transactions where upper(trim(PROJECT_EN)) = ? and %s" % SALE,
                        [n.upper().strip()]).fetchone()[0]
        if c:
            ranked.append((n, c))
    ranked.sort(key=lambda x: -x[1])
    all_stats = {n: building_stats(con, n) for n, _ in ranked}
    all_stats = {k: v for k, v in all_stats.items() if v}

    pages = [developer_cover(a.developer, all_stats, ranked, today)]
    for b in a.buildings:
        rec, why = S.build_record(b)
        if rec is None:
            print("  skip %s: %s" % (b, why)); continue
        st = building_stats(con, rec["project"] if rec.get("project") else b) or building_stats(con, b)
        at = {}
        for key, fn in (("p1", S.page1), ("p2", S.page2), ("p3", S.page3)):
            p = fn(rec, today)
            if p:
                pages.append(p); at[key] = len(pages)
                if key == "p1" and st:
                    pages.append(market_page(rec, st, position(rec.get("project") or b), today))
        if "p1" in at:
            pages[at["p1"] - 1] = pages[at["p1"] - 1].replace("__HOLDINGSPAGE__", str(at.get("p3", "") + 1 if at.get("p3") else ""))
        print("  %-18s %s" % (b, "market page + %d sheet pages" % len(at) if st else "sheet pages only"))
    out = "".join('<div class="page">%s</div>' % p.replace("__PAGENO__", "Page %d of %d" % (i, len(pages)))
                  for i, p in enumerate(pages, 1))
    name = a.name or "%s_brief" % S.slugify(a.developer)
    hp = os.path.join(S.SHEETS, name + ".html")
    io.open(hp, "w", encoding="utf-8").write(S.DOC % (S.esc(a.developer + " brief"), S.CSS, out))
    pp = os.path.join(S.SHEETS, name + ".pdf")
    ok = S.to_pdf(hp, pp)
    print("%s - %d pages, %s" % (name, len(pages), "%.0f KB" % (os.path.getsize(pp) / 1024) if ok else "HTML only"))
    if ok and a.push:
        S.push_sheet({"slug": name, "name": a.developer + " brief", "images": {"hero": 1}}, pp, len(pages))


if __name__ == "__main__":
    main()
