"""Sanctuary by Prestige One - a sales brief in the Ellington-brief format (build_client_sheet / build_developer_brief styles).

Sources: Prestige One's Sanctuary Brief (125-page brochure: floor plates, unit plans with suite/balcony areas, payment plan) and its
15 Sep 2026 price list (43 priced units, views) from Najma's availability inbox; the Dubai Land Department register (g_dld__transactions,
lake snapshot 298; DLD project register pulled 19 Sep 2026); KHDA school register; DHA facility register; OpenStreetMap for grocers.
"""
import datetime as dt, io, json, os, re, shutil, sys, collections

sys.path.insert(0, r"C:\Dev\naj-market-pulse\scripts")
import build_client_sheet as S
import build_developer_brief as B

TMP = os.environ["TEMP"]
IMG = os.path.join(TMP, "sb")
GOLD, NAVY, INK, MUTED, RULE = B.GOLD, B.NAVY, B.INK, B.MUTED, B.RULE
CREAM = "#F3EFE6"
today = dt.date.today().strftime("%d %B %Y")
esc = S.esc

MK = json.load(open(os.path.join(TMP, "sanct_market.json"), encoding="utf-8"))
AR = json.load(open(os.path.join(TMP, "sanct_around.json"), encoding="utf-8"))
PLATES = json.load(open(os.path.join(TMP, "sanct_units_map.json"), encoding="utf-8"))
PRICED = json.load(open(os.path.join(TMP, "sanct_priced.json"), encoding="utf-8"))   # (unit, floor, stack, type, rooms, sqft, price, view)

# indoor (suite) and outdoor areas per typology variant, sq ft, from the brochure's unit-plan pages 62-85
TYPOS = {
    "1BR-A": {"label": "1 bedroom · Type A", "suite": (587.7, 604.4), "balc": (65.0, 520.5), "floors": "1-20", "page": "t_1br_a",
              "note": "The workhorse of the building: 57 of the 125 apartments. The same 590 sq ft interior on every floor; what changes is the balcony (65 to 520 sq ft) and the view."},
    "1BR-B": {"label": "1 bedroom · Type B", "suite": (648.3, 657.5), "balc": (483.3, 894.7), "floors": "10-12", "page": "t_1br_b",
              "note": "Three units only, on the terrace floors above the level-9 living deck. A slightly larger interior with a terrace of up to 895 sq ft."},
    "1BR-C": {"label": "1 bedroom · Type C", "suite": (616.1, 616.1), "balc": (222.4, 222.4), "floors": "13-20", "page": "t_1br_c",
              "note": "One per floor from 13 to 20. A mid-size balcony on the upper floors."},
    "2BR-A": {"label": "2 bedroom · Type A", "suite": (865.4, 867.1), "balc": (177.5, 669.8), "floors": "1-20", "page": "t_2br_a",
              "note": "The corner stack facing the park, the sanctuary and the Burj Khalifa, on every floor."},
    "2BR-B": {"label": "2 bedroom · Type B", "suite": (859.1, 885.9), "balc": (375.4, 1675.4), "floors": "1-12", "page": "t_2br_b",
              "note": "Faces the park, the sanctuary and Creek Harbour. Unit 103 on level 1 carries a 1,675 sq ft garden terrace."},
    "2BR-C": {"label": "2 bedroom · Type C", "suite": (917.1, 942.4), "balc": (177.6, 705.4), "floors": "1-8", "page": "t_2br_c",
              "note": "The largest two-bedroom interior (up to 942 sq ft), on the lower floors facing the park and Creek Harbour."},
    "2BR-D": {"label": "2 bedroom · Type D", "suite": (872.6, 897.3), "balc": (296.0, 1361.8), "floors": "10-20", "page": "t_2br_d",
              "note": "On floors 10 to 12 it comes with a terrace of up to 1,362 sq ft: the most outdoor space per dirham in the tower."},
    "3BR-A": {"label": "3 bedroom · Type A", "suite": (1458.7, 1459.4), "balc": (611.1, 628.6), "floors": "13-20", "page": "t_3br_a",
              "note": "Eight units, one per floor from 13 to 20, with a 611 to 629 sq ft balcony facing the park, the sanctuary and Creek Harbour."},
}
STACK_VIEW = {"01": "Park · Sanctuary · Burj Khalifa", "02": "Park · Sanctuary · Burj Khalifa", "03": "Park · Sanctuary · Creek Harbour",
              "04": "Park · Creek Harbour", "05": "Park · Creek Harbour (level 17: community)", "06": "Park · Creek Harbour to level 8, then community · partial Burj Khalifa",
              "07": "Community · partial Burj Khalifa"}
TYPE_COL = {"1BR-A": "#DCE3EA", "1BR-B": "#B9C8D6", "1BR-C": "#8FA7BD", "2BR-A": "#E9DCC3", "2BR-B": "#D9C29A", "2BR-C": "#C8A870", "2BR-D": "#B38D4E", "3BR-A": "#17283F"}


def aed(v, m=False):
    return ("AED %.2fM" % (v / 1e6)) if m else "AED {:,.0f}".format(v)


def med(xs):
    xs = sorted(xs); n = len(xs)
    return (xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2) if xs else None


def img(name, style):
    return S.img_tag(os.path.join(IMG, name + ".jpg"), style, name)


def table(head, rows, widths=None, align=None, first_bold=True, zebra=True, fs=12.5):
    th = "".join('<th style="text-align:%s;padding:9px 10px;font-size:10.5px;letter-spacing:1px;font-weight:600;color:#FFF;%s">%s</th>'
                 % ((align[i] if align else "left"), ("width:%s;" % widths[i]) if widths else "", esc(h)) for i, h in enumerate(head))
    tr = []
    for n, r in enumerate(rows):
        bg = CREAM if (zebra and n % 2 == 0) else "#FFF"
        tds = "".join('<td style="text-align:%s;padding:8px 10px;font-size:%spx;%s">%s</td>'
                      % ((align[i] if align else "left"), fs, "font-weight:600;color:%s;" % NAVY if (i == 0 and first_bold) else "", c)
                      for i, c in enumerate(r))
        tr.append('<tr style="background:%s;border-bottom:1px solid %s;">%s</tr>' % (bg, RULE, tds))
    return '<table><tr style="background:%s;">%s</tr>%s</table>' % (NAVY, th, "".join(tr))


def prov(text):
    return '<div class="prov" style="margin-top:auto;border-top:1px solid %s;padding-top:8px;">%s</div>' % (RULE, text)


def section(title, sub=""):
    return ('<div><div class="h2 serif" style="margin-top:4px;">%s</div>%s</div>'
            % (esc(title), ('<div class="sub" style="margin-top:2px;">%s</div>' % esc(sub)) if sub else ""))


# --------------------------------------------------------------------------- Sanctuary facts
by_rooms = collections.defaultdict(list)
for u in PRICED:
    by_rooms[u[4]].append(u)
units_by_beds = collections.Counter(v["beds"] for v in PLATES.values())
psf_all = [u[6] / u[5] for u in PRICED]
S_PSF = med(psf_all)


def sanct_row(rooms, beds):
    xs = by_rooms[rooms]
    suites = [TYPOS[t]["suite"] for t in TYPOS if t.startswith(str(beds))]
    return (min(s[0] for s in suites), max(s[1] for s in suites), min(u[5] for u in xs), max(u[5] for u in xs),
            min(u[6] for u in xs), max(u[6] for u in xs), med([u[6] for u in xs]), med([u[6] / u[5] for u in xs]), len(xs))


# --------------------------------------------------------------------------- pages
pages = []

# 1 cover
rows = []
for rooms, beds in (("1 B/R", 1), ("2 B/R", 2), ("3 B/R", 3)):
    s0, s1, t0, t1, p0, p1, pm, psf, n = sanct_row(rooms, beds)
    rows.append(['%s bedroom<div style="font-size:11px;color:%s;font-weight:400;">%d apartments · %d priced</div>' % (beds, MUTED, units_by_beds[beds], n),
                 '%s<div style="font-size:11px;color:%s;">indoor</div>' % (("{:,.0f}".format(s0) if s0 == s1 or abs(s1 - s0) < 20 else "{:,.0f}–{:,.0f}".format(s0, s1)) + " sq ft", MUTED),
                 '{:,.0f}–{:,.0f} sq ft<div style="font-size:11px;color:{};">with balcony</div>'.format(t0, t1, MUTED),
                 '<b>%s</b><div style="font-size:11px;color:%s;">to %s</div>' % (aed(p0, True), MUTED, aed(p1, True)),
                 "AED {:,.0f}".format(psf)])
cover = ('<div class="sheet">' + img("cover", "width:794px;height:250px;object-fit:cover;display:block;") +
         '<div style="padding:22px 44px 0 44px;flex:1;display:flex;flex-direction:column;gap:14px;">'
         '<div style="display:flex;justify-content:space-between;align-items:flex-end;"><div class="serif" style="font-size:40px;color:%s;line-height:1;">Sanctuary</div>'
         '<div class="lbl">MEYDAN HORIZON · DUBAI</div></div>'
         '<div class="sub" style="margin-top:-6px;">Prestige One · 125 apartments on the edge of the Ras Al Khor Wildlife Sanctuary</div>'
         '<div style="width:52px;height:3px;background:%s;"></div>'
         '<div style="display:flex;gap:28px;">%s</div>'
         % (NAVY, GOLD, "".join('<div><div class="lbl">%s</div><div style="font-size:14px;">%s</div></div>' % (a, b) for a, b in
                                (("DEVELOPER", "Prestige One"), ("HANDOVER", "Q3 2029"), ("APARTMENTS", "125 · 68 / 49 / 8"), ("BUILDING", "B+G+3P+20+roof"), ("PAYMENT PLAN", "65 / 35")))) +
         section("What it sells for", "Prestige One's own price list, 15 September 2026: 43 of the 125 apartments priced") +
         table(["APARTMENT", "INDOOR SIZE", "TOTAL SIZE", "ASKING FROM", "PER SQ FT"], rows, align=["left", "right", "right", "right", "right"]) +
         '<div class="card" style="flex-direction:row;gap:18px;align-items:center;">'
         '<div style="flex:1;"><div class="lbl">WHY THE SIZES SPREAD SO WIDELY</div><div style="font-size:13px;line-height:1.45;margin-top:4px;">'
         'Every one-bedroom interior is 588 to 657 sq ft. What varies is the balcony: from 65 sq ft on a typical floor to 895 sq ft on the terrace floors (10 to 12). '
         'Sizes on the price list include the balcony, so always compare the <b>indoor</b> figure first.</div></div></div>'
         + prov("<b>Sources</b> · Prestige One: Sanctuary Brief (unit plans with suite and balcony areas, unit mix, handover, 65/35 plan) and price list of 15 Sep 2026 "
                "(43 units). Price per sq ft is asking price divided by total area incl. balcony, the same basis the Land Department records. "
                "Asking prices are the developer's, not registered sales: no Sanctuary apartment sale is registered with DLD yet.") +
         '</div><div style="padding:0 44px 22px 44px;display:flex;justify-content:space-between;font-size:11px;color:%s;"><span>__PAGENO__</span><span>Prepared %s</span></div></div>' % (MUTED, today))
pages.append(cover)

# 2 the case in one page
PT = json.load(open(os.path.join(TMP, "sanct_pitch.json"), encoding="utf-8"))
DIST = json.load(open(os.path.join(TMP, "sanct_dist.json"), encoding="utf-8"))
DRIVE = [("Downtown Dubai", "5 min"), ("Business Bay", "5 min"), ("Dubai Design District", "5 min"), ("DIFC", "10 min"), ("DXB Airport", "15 min"), ("Dubai Marina", "20 min")]
dist_cards = "".join('<div style="flex:1;border:1px solid %s;background:#FFF;padding:7px 8px;"><div class="serif" style="font-size:20px;color:%s;">%.1f km</div>'
                     '<div style="font-size:11px;line-height:1.2;">%s</div></div>' % (RULE, NAVY, d, esc(n)) for n, d in DIST)
drive = " · ".join("%s <b>%s</b>" % (esc(a), b) for a, b in DRIVE)
s1 = sanct_row("1 B/R", 1)
drows = []
for lab in ("Palm Jumeirah", "Downtown Dubai", "Business Bay", "Dubai Marina", "Dubai Creek Harbour", "Meydan Horizon"):
    p = PT[lab]
    drows.append([lab, aed(p["br1"][0], True), "{:,.0f}".format(p["br1"][1]), "AED {:,.0f}".format(p["psf"]), "{:,}".format(p["n"])])
drows.append(['Sanctuary', '<b>from %s</b><div style="font-size:11px;color:%s;">median ask %s</div>' % (aed(s1[4], True), MUTED, aed(s1[6], True)),
              "{:,.0f}–{:,.0f}".format(s1[2], s1[3]), "AED {:,.0f}".format(S_PSF), "asking"])
dt_ = table(["ADDRESS", "1-BED PRICE", "1-BED SQ FT", "PER SQ FT", "SALES, 12 MO"], drows, align=["left", "right", "right", "right", "right"], fs=12)
dt_ = dt_.replace('<tr style="background:%s;border-bottom:1px solid %s;"><td style="text-align:left;padding:8px 10px;font-size:12px;font-weight:600;color:%s;">Sanctuary' % (CREAM if len(drows) % 2 else "#FFF", RULE, NAVY),
                  '<tr style="background:#FFF7E6;border-bottom:1px solid %s;"><td style="text-align:left;padding:8px 10px;font-size:12px;font-weight:600;color:%s;">Sanctuary' % (RULE, NAVY))
block = lambda t, d: ('<div style="border-left:3px solid %s;padding:1px 0 1px 10px;"><div style="font-weight:600;font-size:13.5px;color:%s;">%s</div>'
                      '<div style="font-size:12.5px;line-height:1.45;">%s</div></div>' % (GOLD, NAVY, esc(t), d))
body = ('<div class="serif" style="font-size:19px;color:%s;line-height:1.35;max-width:660px;">Downtown is crowded and dear, and the waterfront is out of reach for most first budgets. '
        'Sanctuary sits between them: minutes from Downtown, Business Bay and the Creek, for a lower entry ticket than either, in a building of 125 homes beside a wildlife reserve.</div>' % NAVY +
        '<div class="lbl">CLOSE TO EVERYTHING · STRAIGHT LINE FROM THE BUILDING</div><div style="display:flex;gap:6px;">%s</div>' % dist_cards +
        '<div style="font-size:12px;color:%s;margin-top:-6px;">Prestige One&#39;s drive times: %s.</div>' % (MUTED, drive) +
        '<div class="lbl">THE TICKET, NEXT TO THE ADDRESSES PEOPLE WANT · TYPICAL 1-BEDROOM</div>' + dt_ +
        '<div style="display:flex;gap:18px;"><div style="flex:1;display:flex;flex-direction:column;gap:9px;">' +
        block("A lower way in", "A Sanctuary one-bedroom starts at %s, below the typical one-bedroom sale in Creek Harbour (%s), Business Bay (%s) and Downtown (%s)."
              % (aed(s1[4], True), aed(PT["Dubai Creek Harbour"]["br1"][0], True), aed(PT["Business Bay"]["br1"][0], True), aed(PT["Downtown Dubai"]["br1"][0], True))) +
        block("Without the crowd", "125 apartments in one tower. On the same Meydan Horizon strip Sobha One registers 3,057 units, AMAAL 8 545 and The Element 401. "
              "A typical Downtown tower holds 174 apartments, Business Bay 182.") +
        '</div><div style="flex:1;display:flex;flex-direction:column;gap:9px;">' +
        block("Nature at the door", "1.2 km from the Ras Al Khor Wildlife Sanctuary and its flamingos, with the Downtown and Creek Harbour skylines as the view from stacks 01 to 03.") +
        block("Be straight about space", "Per sq ft Sanctuary asks more than Creek Harbour and Business Bay (AED %s against %s and %s): the lower ticket comes from a compact interior. "
              "For the most space per dirham, show a Business Bay or Creek Harbour resale; for the address at the lowest ticket, show Sanctuary."
              % ("{:,.0f}".format(S_PSF), "{:,.0f}".format(PT["Dubai Creek Harbour"]["psf"]), "{:,.0f}".format(PT["Business Bay"]["psf"]))) +
        '</div></div>' +
        prov("<b>Prices</b> · DLD register, apartment sales 1 Sep 2025 to 17 Sep 2026: medians per district (Downtown = DLD area Burj Khalifa; Creek Harbour = master project Dubai Creek Harbour; "
             "Meydan Horizon = Ras Al Khor Industrial First). <b>Tower sizes</b> · DLD building register, median apartments per residential tower. "
             "<b>Distances</b> straight-line from Prestige One's map pin; drive times are Prestige One's own, from the Sanctuary Brief."))
pages.append(B.shell("The centre of everything, without the crowd", "SANCTUARY · THE CASE IN ONE PAGE", body, today))

# 2 why Sanctuary: the neighbours
C = MK["comps"]
order = ["The Element at Sobha One", "Sobha One", "AMAAL 8", "Belmore Residences", "Sobha Hartland - The Crest", "Azizi Riviera Reve"]
short = {"The Element at Sobha One": "The Element at Sobha One", "Sobha One": "Sobha One", "AMAAL 8": "AMAAL 8", "Belmore Residences": "Belmore Residences",
         "Sobha Hartland - The Crest": "Sobha Hartland · The Crest", "Azizi Riviera Reve": "Azizi Riviera Reve"}
where = {"The Element at Sobha One": "Meydan Horizon", "Sobha One": "Meydan Horizon", "AMAAL 8": "Meydan Horizon", "Belmore Residences": "Bukadra",
         "Sobha Hartland - The Crest": "Sobha Hartland", "Azizi Riviera Reve": "Meydan One"}
dev = {"The Element at Sobha One": "Sobha", "Sobha One": "Sobha", "AMAAL 8": "Meydan", "Belmore Residences": "Ellington", "Sobha Hartland - The Crest": "Sobha", "Azizi Riviera Reve": "Azizi"}


def built(c):
    r = c.get("register") or {}
    pc = r.get("percent_completed")
    end = (r.get("project_end_date") or r.get("completion_date") or "")[:7]
    s = ("%.0f%% built" % float(pc)) if pc not in (None, "") else "-"
    return s + ('<div style="font-size:11px;color:%s;">due %s</div>' % (MUTED, end) if end else "")


def units(c):
    r = c.get("register") or {}
    return "{:,}".format(int(float(r["no_of_units"]))) if r.get("no_of_units") not in (None, "", 0, "0") and float(r["no_of_units"]) > 0 else "-"


rows = [['Sanctuary<div style="font-size:11px;color:%s;font-weight:400;">Prestige One · Meydan Horizon</div>' % MUTED, "125",
         'launch<div style="font-size:11px;color:%s;">due Q3 2029</div>' % MUTED, "AED {:,.0f}".format(S_PSF) + '<div style="font-size:11px;color:%s;">asking</div>' % MUTED,
         aed(sanct_row("1 B/R", 1)[6], True) + '<div style="font-size:11px;color:%s;">asking median</div>' % MUTED]]
for k in order:
    c = C[k]
    r1 = next((r for r in c["rooms"] if r[0] == "1 B/R"), None)
    rows.append(['%s<div style="font-size:11px;color:%s;font-weight:400;">%s · %s</div>' % (short[k], MUTED, dev[k], where[k]), units(c), built(c),
                 "AED {:,.0f}".format(c["last12_psf"]) + '<div style="font-size:11px;color:%s;">%d sales, 12 mo</div>' % (MUTED, c["last12_sales"]),
                 (aed(r1[3], True) + '<div style="font-size:11px;color:%s;">{:,.0f} sq ft</div>'.format(r1[2]) % MUTED) if r1 else "-"])
tbl = table(["PROJECT", "APARTMENTS", "PROGRESS", "PER SQ FT", "1 BEDROOM"], rows, align=["left", "right", "right", "right", "right"], fs=12.5)
tbl = tbl.replace('<tr style="background:%s;border-bottom' % CREAM, '<tr style="background:#FFF7E6;border-bottom', 1)
win = [
    ("A boutique address", "125 apartments. Sobha One registers 3,057 units and AMAAL 8 545 on the same Meydan Horizon strip: far fewer identical flats competing when an owner resells or rents."),
    ("On the sanctuary's edge", "1.2 km to the Ras Al Khor Wildlife Sanctuary. Stacks 01 to 03 look over the park and the sanctuary to the Burj Khalifa or Creek Harbour, on every floor."),
    ("Every apartment has outdoor space", "Balconies from 65 sq ft, and terrace floors 10 to 12 with up to 1,362 sq ft outside."),
    ("A 65 / 35 plan", "20% to book, 45% across two years, 35% at handover: about a third of the price is still yours until the keys arrive."),
]
ask = [
    ("It costs more per sq ft", "Asking AED {:,.0f} per sq ft against AED {:,.0f} at Sobha One and AED {:,.0f} at The Element over the last 12 months. The reply: ask for the indoor area, the view and the building size, and compare like with like.".format(S_PSF, C["Sobha One"]["last12_psf"], C["The Element at Sobha One"]["last12_psf"])),
    ("Handover is 2029", "The same year as The Element; Belmore is due in 2027 and AMAAL 8 in 2028."),
    ("It is not in the register yet", "No Sanctuary project number or escrow account appears in the Land Department's project register as of 19 Sep 2026. Ask Prestige One for both before a client pays the booking amount."),
]
card = lambda t, d, col: ('<div style="border-left:3px solid %s;padding:2px 0 2px 10px;"><div style="font-weight:600;font-size:13px;color:%s;">%s</div>'
                          '<div style="font-size:12px;line-height:1.4;">%s</div></div>' % (col, NAVY, esc(t), esc(d)))
body = ('<div class="sub" style="max-width:640px;">Six projects a Meydan buyer will also be shown, against Sanctuary. Neighbours are the Land Department\'s registered sales and project register; Sanctuary is Prestige One\'s asking price.</div>'
        + tbl +
        '<div style="display:flex;gap:18px;">'
        '<div style="flex:1;display:flex;flex-direction:column;gap:9px;"><div class="lbl">WHERE SANCTUARY WINS</div>%s</div>'
        '<div style="flex:1;display:flex;flex-direction:column;gap:9px;"><div class="lbl">WHAT A CLIENT WILL ASK</div>%s</div></div>'
        % ("".join(card(a, b, GOLD) for a, b in win), "".join(card(a, b, "#A4462F") for a, b in ask))
        + prov("<b>Neighbours</b> · DLD register, apartment sales 1 Sep 2025 to 17 Sep 2026 (per sq ft) and 2025-26 (1-bedroom median and size, total area). "
               "Apartments, progress and due date from the DLD project register (19 Sep 2026); Azizi Riviera Reve shows 53% built against a registered end date of Feb 2025. "
               "Symphony (Town Square) is left out: it is 15 km away and not a Meydan alternative."))
pages.append(B.shell("Why Sanctuary", "SANCTUARY AGAINST ITS NEIGHBOURS", body, today))

# 2b Ellington, the main competitor
ELL = ["Belmore Residences", "The Highgrove", "Riverton House", "Eaton Square", "The Highbury", "Kensington Waters"]
ell_where = {"Belmore Residences": "Bukadra", "The Highgrove": "Bukadra", "Riverton House": "Bukadra", "Eaton Square": "Bukadra",
             "The Highbury": "Sobha Hartland", "Kensington Waters": "Sobha Hartland · completed"}
rows = [rows_s for rows_s in [['Sanctuary<div style="font-size:11px;color:%s;font-weight:400;">Prestige One · Meydan Horizon</div>' % MUTED, "125",
         'launch<div style="font-size:11px;color:%s;">due Q3 2029</div>' % MUTED, "AED {:,.0f}".format(S_PSF) + '<div style="font-size:11px;color:%s;">asking</div>' % MUTED,
         aed(sanct_row("1 B/R", 1)[6], True) + '<div style="font-size:11px;color:%s;">asking median</div>' % MUTED]]]
for k in ELL:
    c = C[k]
    r1 = next((r for r in c["rooms"] if r[0] == "1 B/R"), None)
    note = "%d sales, 12 mo" % c["last12_sales"] + (" · small sample" if c["last12_sales"] < 30 else "")
    rows.append(['%s<div style="font-size:11px;color:%s;font-weight:400;">Ellington · %s</div>' % (k, MUTED, ell_where[k]), units(c), built(c),
                 "AED {:,.0f}".format(c["last12_psf"]) + '<div style="font-size:11px;color:%s;">%s</div>' % (MUTED, note),
                 (aed(r1[3], True) + '<div style="font-size:11px;color:%s;">{:,.0f} sq ft</div>'.format(r1[2]) % MUTED) if r1 else "-"])
tbl = table(["ELLINGTON PROJECT", "APARTMENTS", "PROGRESS", "PER SQ FT", "1 BEDROOM"], rows, align=["left", "right", "right", "right", "right"], fs=12)
tbl = tbl.replace('<tr style="background:%s;border-bottom' % CREAM, '<tr style="background:#FFF7E6;border-bottom', 1)
s1, s2 = sanct_row("1 B/R", 1), sanct_row("2 B/R", 2)
hg, rv, bm = C["The Highgrove"], C["Riverton House"], C["Belmore Residences"]
r_ = lambda c, rm: next((r for r in c["rooms"] if r[0] == rm), None)
h2h = []
for rm, s in (("1 B/R", s1), ("2 B/R", s2)):
    h2h.append(["Sanctuary", rm.replace(" B/R", "-bed"), "{:,.0f}–{:,.0f}".format(s[2], s[3]), aed(s[6], True), "AED {:,.0f}".format(s[7])])
    for nm, c in (("The Highgrove", hg), ("Riverton House", rv), ("Belmore Residences", bm)):
        r = r_(c, rm)
        if r: h2h.append([nm, rm.replace(" B/R", "-bed"), "{:,.0f}".format(r[2]), aed(r[3], True), "AED {:,.0f}".format(r[4])])
h2h_t = table(["PROJECT", "SIZE", "SQ FT", "PRICE", "PER SQ FT"], h2h, align=["left", "left", "right", "right", "right"], fs=11.5)
ew = [
    ("Five times smaller than The Highgrove", "125 apartments against 296 at The Highgrove, and Ellington has launched four towers in Bukadra in twelve months: 500 registered sales that will compete on resale and rent."),
    ("At or below Ellington's latest price", "Riverton House (Jul 2026 launch) sells at AED {:,.0f} per sq ft; Sanctuary asks AED {:,.0f} overall, level on the 1-bed and lower on the 2-bed. Eaton Square: AED {:,.0f}."
     .format(rv["last12_psf"], S_PSF, C["Eaton Square"]["last12_psf"])),
    ("The reserve as the view", "Sanctuary is 1.2 km from the Ras Al Khor Wildlife Sanctuary, and stacks 01 to 03 are priced for the park, reserve and Downtown or Creek Harbour skyline on every floor."),
]
ea = [
    ("\"Ellington is the brand I know\"", "True: design-led, with a delivered record. Kensington Waters (Sobha Hartland) is 100% built and resells at AED {:,.0f} per sq ft. Sanctuary is Prestige One's first project on this strip; lean on the plot, the plan and the view."
     .format(C["Kensington Waters"]["last12_psf"])),
    ("\"The Highgrove and Belmore are cheaper per sq ft\"", "They are: AED {:,.0f} and AED {:,.0f} against Sanctuary's {:,.0f}. Their one-bedrooms are larger in total area; compare indoor area, balcony and view, and the lower Sanctuary entry ticket from AED 1.86M."
     .format(hg["last12_psf"], bm["last12_psf"], S_PSF)),
    ("\"Ellington hands over sooner\"", "Riverton House is due end 2027, Belmore 2027 and The Highgrove end 2028, all 0% built. Sanctuary is due Q3 2029: a longer wait, but 35% is paid only at handover."),
]
body = ('<div class="sub" style="max-width:660px;">Ellington is the competitor a Meydan buyer is most likely to be shown. It has four launches in neighbouring Bukadra '
        'and a delivered track record in Sobha Hartland. Land Department registered sales for Ellington; Prestige One asking price for Sanctuary.</div>'
        + tbl +
        '<div class="lbl" style="margin-top:2px;">HEAD TO HEAD · MEDIAN REGISTERED SALE, 2025-26 · SANCTUARY ASKING</div>' + h2h_t +
        '<div style="display:flex;gap:18px;">'
        '<div style="flex:1;display:flex;flex-direction:column;gap:8px;"><div class="lbl">WHERE SANCTUARY WINS</div>%s</div>'
        '<div style="flex:1;display:flex;flex-direction:column;gap:8px;"><div class="lbl">WHAT AN ELLINGTON BUYER WILL SAY</div>%s</div></div>'
        % ("".join(card(a, b, GOLD) for a, b in ew), "".join(card(a, b, "#A4462F") for a, b in ea))
        + prov("<b>Ellington</b> · DLD register, apartment sales 1 Sep 2025 to 17 Sep 2026 (per sq ft) and 2025-26 (by bedroom, total area incl. balcony). "
               "Apartments, progress and due dates from the DLD project register (19 Sep 2026); Riverton House and Eaton Square have no unit count registered yet. "
               "Eaton Square has only 17 sales: treat its price as indicative."))
pages.append(B.shell("Ellington, next door", "SANCTUARY AGAINST ITS MAIN COMPETITOR", body.replace("padding:8px 10px", "padding:4px 9px").replace("padding:9px 10px", "padding:6px 9px"), today))

# 3 by bedroom
body = '<div class="sub">What each apartment size costs, next door. Neighbours: median registered sale, 2025-26. Sanctuary: median asking price.</div>'
for rooms, beds in (("1 B/R", 1), ("2 B/R", 2), ("3 B/R", 3)):
    s = sanct_row(rooms, beds)
    rws = [["Sanctuary", "{:,.0f}–{:,.0f}".format(s[2], s[3]), aed(s[6], True), "AED {:,.0f}".format(s[7]), "asking"]]
    for k in order:
        r = next((x for x in C[k]["rooms"] if x[0] == rooms), None)
        if r: rws.append([short[k], "{:,.0f}".format(r[2]), aed(r[3], True), "AED {:,.0f}".format(r[4]), "{:,} sales".format(r[1])])
    rws.sort(key=lambda r: 0 if r[0] == "Sanctuary" else float(r[2].split()[1].rstrip("M")))
    t = table(["%d BEDROOM" % beds, "SIZE SQ FT", "PRICE", "PER SQ FT", "BASIS"], rws, align=["left", "right", "right", "right", "right"], fs=12)
    body += '<div class="lbl" style="margin-top:4px;">%d BEDROOM</div>' % beds + t
body += prov("Sizes are total area including balcony, as registered. Sanctuary's one-bedroom <b>indoor</b> area is 588 to 657 sq ft; its range here is wide because of the balconies. "
             "Sources: DLD register (g_dld__transactions, snapshot 298); Prestige One price list 15 Sep 2026.")
pages.append(B.shell("Room by room", "WHAT THE NEIGHBOURS SELL FOR", body, today))

# 4 market & neighbourhood
sub = MK["sub_monthly"]
lc = B.line_chart([("Meydan Horizon", NAVY, [(m, v) for m, n, v in sub])], fmt=lambda v: "{:,.0f}".format(v))
bc = B.bar_chart([(dt.date(int(m[:4]), int(m[5:]), 1).strftime("%b"), n) for m, n, v in sub], h=120)
khda = [s for s in AR["khda"] if s[0] <= 5.0 and "JABAL ALI" not in (s[4] or "").upper()]
curr = collections.Counter()
for s in khda:
    c_ = (s[2] or "").lower()
    curr["British" if "uk" in c_ else "IB" if "baccalaureate" in c_ or "/ib" in c_ else "American" if "american" in c_ or "us" in c_ else "French" if "french" in c_ else "Other"] += 1
dha = AR["dha"]
hosp = [x for x in dha if "hospital (" in (x[2] or "").lower() or "general hospital" in (x[2] or "").lower() or "specialty hospital" in (x[2] or "").lower()]
clin3 = [x for x in dha if x[0] <= 3 and any(k in (x[2] or "").lower() for k in ("clinic", "polyclinic", "center", "centre"))]
ph3 = [x for x in dha if x[0] <= 3 and "pharm" in (x[2] or "").lower()]
osm = AR["osm"]
groc = [x for x in osm if x[1] == "supermarket"]
spin = next((x for x in groc if "spinneys" in (x[2] + x[3]).lower()), None)
metro = MK["around"]["metro"]
cards1 = "".join([
    B.icard("park", "1.2 km", "Ras Al Khor Wildlife Sanctuary", "nature reserve, straight line"),
    B.icard("metro", "%.1f km" % metro[0][0], metro[0][1]["n"], "nearest today · Meydan Horizon metro planned"),
    B.icard("hospital", "%.1f km" % hosp[1][0] if len(hosp) > 1 else "-", hosp[1][1] if len(hosp) > 1 else "", "general hospital"),
    B.icard("cart", "%.1f km" % spin[0] if spin else "-", "Spinneys", "nearest major grocer"),
])
cards2 = "".join([
    B.icard("school", str(len(khda)), "KHDA schools within 5 km", " · ".join("%d %s" % (v, k) for k, v in curr.most_common(4))),
    B.icard("hospital", str(len(clin3)), "clinics within 3 km", "DHA register"),
    B.icard("hospital", str(len(ph3)), "pharmacies within 3 km", "DHA register"),
    B.icard("cart", str(sum(1 for x in groc if x[0] <= 3)), "groceries within 3 km", "OpenStreetMap"),
])
top_sch = "; ".join("<b>%s</b> (%s · %s, %.1f km)" % (esc(s[1].split(" L.L.C")[0].split(" - ")[0].split(" FZ")[0]), esc(s[3] or "not rated"), esc((s[2] or "").split(" - ")[0]), s[0])
                   for s in sorted(khda, key=lambda s: ({"outstanding": 0, "very good": 1, "good": 2}.get((s[3] or "").lower(), 9), s[0]))[:4])
body = (B.stat and "" ) + ('<div style="display:flex;gap:10px;">%s%s%s</div>' % (
        B.stat("Meydan Horizon, per sq ft", "AED {:,.0f}".format(med([v for m, n, v in sub])), "median of monthly medians, Sep 2025 – Sep 2026"),
        B.stat("Sanctuary asks", "AED {:,.0f}".format(S_PSF), "median of its 43 priced units"),
        B.stat("Registered sales", "{:,}".format(sum(n for m, n, v in sub)), "apartments in the sub-area, 12 months")) +
        '<div class="lbl">PRICE PER SQ FT, MONTH BY MONTH · MEYDAN HORIZON (DLD AREA RAS AL KHOR INDUSTRIAL FIRST)</div>' + lc +
        '<div class="lbl">SALES PER MONTH</div>' + bc +
        '<div class="lbl">GETTING AROUND</div><div style="display:flex;gap:8px;">%s</div>' % cards1 +
        '<div class="lbl">SCHOOLS, HEALTH AND GROCERIES</div><div style="display:flex;gap:8px;">%s</div>' % cards2 +
        '<div style="font-size:12px;line-height:1.45;">Top-rated nearby: %s.</div>' % top_sch +
        prov("<b>Prices</b> · DLD register, off-plan apartment sales in Sanctuary's DLD area (Sobha One, The Element, AMAAL 8). "
             "<b>Distances</b> are straight-line from Prestige One's own map pin (25.1841 N, 55.3329 E), never walking times. "
             "Schools and ratings: KHDA register. Hospitals, clinics, pharmacies: DHA facility register (active). Groceries: OpenStreetMap. "
             "Metro: RTA. The Meydan Horizon metro line is planned, not built."))
pages.append(B.shell("Sanctuary", "MARKET & NEIGHBOURHOOD", body, today))

# 5 the land and the register
body = ('<div class="sub" style="max-width:640px;">What the Land Department register already knows about the Sanctuary plot, before a single apartment is sold.</div>'
        '<div style="display:flex;gap:10px;">%s%s%s</div>' % (
            B.stat("Plot bought, Mar 2019", "AED 59.2M", "2,690 m² of land, registered sale"),
            B.stat("Plot sold, Aug 2025", "AED 101M", "+71% in six years"),
            B.stat("Land per apartment", "AED 808k", "AED 101M across 125 apartments")) +
        '<div style="font-size:13.5px;line-height:1.5;">The plot changed hands for AED 101 million in August 2025 and was granted onward in September 2025, the usual step before a project company launches. '
        'No apartment in Sanctuary is registered yet, and Sanctuary has no project number or escrow account in the DLD project register as of 19 September 2026.</div>'
        '<div class="card" style="gap:6px;"><div class="lbl">BEFORE A CLIENT PAYS THE BOOKING AMOUNT</div>'
        '<div style="font-size:13px;line-height:1.5;">Ask Prestige One for the DLD project number and the escrow account (bank and account name). Oqood registration of an off-plan sale needs both. '
        'Every neighbour in this brief already shows them: The Element at Sobha One, Sobha One, AMAAL 8 and Belmore all have registered projects with named escrow agents.</div></div>'
        '<div class="card" style="gap:6px;"><div class="lbl">PRESTIGE ONE, IN THE REGISTER</div><div style="font-size:13px;line-height:1.5;">'
        '12 Prestige One projects are registered with DLD. Recent launches sold at AED 1,390 to 3,630 per sq ft in their first year: The Boulevard (Wadi Al Safa 5, 368 sales), Parkway (Bukadra, 225), '
        'Berkeley Square (197), Coastal Haven (Palm Deira, 61). Vista (Al Hebiah Fourth) is 75% built and The Residence (Al Barsha South Fourth) 60%.</div></div>' +
        img("sanctuary_map", "width:706px;height:auto;display:block;border:1px solid %s;" % RULE) +
        '<div style="font-size:11px;color:%s;">Prestige One\'s site plan: Sanctuary between the Ras Al Khor Wildlife Sanctuary and Meydan Horizon.</div>' % MUTED +
        prov("DLD register: plot transactions (project 'Sanctuary by Prestige One', Ras Al Khor Industrial First) and project register pulled 19 Sep 2026. "
             "Prestige One first-year prices: DLD registered sales per project, first 12 months."))
pages.append(B.shell("The land and the register", "SANCTUARY · DUE DILIGENCE", body, today))

# 6 typology guide
rows = []
for t, d in TYPOS.items():
    n = sum(1 for v in PLATES.values() if v["type"] == t)
    pr = [u for u in PRICED if u[3] == t]
    rng = ("%s – %s" % (aed(min(u[6] for u in pr), True), aed(max(u[6] for u in pr), True)) if len(pr) > 1 else aed(pr[0][6], True)) if pr else "not on list"
    views = sorted({STACK_VIEW[v["unit"][-2:]] for v in PLATES.values() if v["type"] == t})
    rows.append([d["label"] + '<div style="font-size:11px;color:%s;font-weight:400;">%d units · floors %s</div>' % (MUTED, n, d["floors"]),
                 "{:,.0f}".format(d["suite"][0]) + ("" if d["suite"][1] - d["suite"][0] < 5 else "–{:,.0f}".format(d["suite"][1])),
                 "{:,.0f}–{:,.0f}".format(*d["balc"]) if d["balc"][0] != d["balc"][1] else "{:,.0f}".format(d["balc"][0]),
                 rng + '<div style="font-size:11px;color:%s;">%d priced</div>' % (MUTED, len(pr)),
                 '<span style="font-size:11px;">%s</span>' % esc(" / ".join(views[:2]))])
qa = [
    ("Which is the biggest one-bedroom?", "By <b>indoor</b> space, Type B (648–658 sq ft, units 1006, 1106, 1206); by total, 1006 at 1,517 sq ft with an 895 sq ft terrace, priced at AED 2.20M: the lowest per sq ft in the building (AED 1,451)."),
    ("Which one-bedroom has the best view?", "Stack 02 (units x02): park, sanctuary and the Burj Khalifa. Higher is better: 302 at AED 2.11M, 1102 at AED 2.29M, 1702 at AED 2.42M."),
    ("The cheapest way in?", "205, a 1-bed Type A of 654 sq ft facing the park and Creek Harbour, at AED 1.859M, the brochure's starting price."),
    ("The best two-bedroom?", "For views, Type A (stack 01: park, sanctuary, Burj Khalifa). For indoor space, Type C (up to 942 sq ft, floors 1–8). For outdoor space, Type D on floors 10–12: 1005 and 1105 at 2,181–2,196 sq ft for AED 3.50–3.52M."),
    ("The three-bedroom?", "Eight units, floors 13–20, 1,459 sq ft inside plus a 611–629 sq ft balcony over the park and sanctuary. 1703 is priced at AED 5.28M."),
]
body = ('<div class="sub">All eight apartment types. Areas in sq ft from Prestige One\'s unit plans; prices from its 15 Sep 2026 list.</div>'
        + table(["TYPE", "INDOOR", "BALCONY", "ASKING", "VIEWS"], rows, widths=["27%", "11%", "14%", "22%", "26%"], align=["left", "right", "right", "right", "left"], fs=12) +
        '<div class="lbl" style="margin-top:4px;">WHAT CLIENTS ASK</div>' +
        "".join('<div style="border-left:3px solid %s;padding:1px 0 1px 10px;"><div style="font-weight:600;font-size:13px;color:%s;">%s</div><div style="font-size:12.2px;line-height:1.4;">%s</div></div>' % (GOLD, NAVY, esc(q), a) for q, a in qa) +
        prov("Indoor = suite area; balcony = balcony and terrace area, both from the unit-plan pages of the Sanctuary Brief. Unit types per floor from its floor plates. "
             "Views per stack from the price list. Unpriced units are not on the 15 Sep list; ask Prestige One for current availability."))
pages.append(B.shell("Every apartment type", "SANCTUARY · TYPOLOGIES", body, today))

# 7 stacking plan
floors = sorted({v["floor"] for v in PLATES.values()}, reverse=True)
stacks = ["01", "02", "03", "04", "05", "06", "07"]
priced_set = {u[0] for u in PRICED}
def stack_head(s):
    v = STACK_VIEW[s].split(" (")[0].replace(" to level 8, then community · partial Burj Khalifa", "")
    return ('<th style="padding:6px 4px;font-size:10px;color:#FFF;background:%s;">STACK %s<div style="font-weight:400;font-size:9px;opacity:.85;">%s</div></th>'
            % (NAVY, s, esc(v)))


grid = ['<tr><th style="padding:6px;font-size:10px;color:#FFF;background:%s;">FLOOR</th>%s</tr>' % (NAVY, "".join(stack_head(s) for s in stacks))]
for f in floors:
    cells = []
    for s in stacks:
        u = "%d%s" % (f, s)
        v = PLATES.get(u)
        if not v:
            cells.append('<td style="background:#FFF;border:1px solid %s;"></td>' % RULE); continue
        col = TYPE_COL[v["type"]]
        fg = "#FFF" if v["type"] in ("3BR-A", "2BR-D") else INK
        dot = "●" if u in priced_set else ""
        cells.append('<td style="background:%s;color:%s;border:1px solid #FFF;text-align:center;padding:4px 2px;font-size:10.5px;"><b>%s</b> %s<div style="font-size:9.5px;">%s</div></td>'
                     % (col, fg, u, dot, v["type"]))
    grid.append('<tr><td style="text-align:center;font-weight:600;font-size:11px;color:%s;background:%s;border:1px solid #FFF;">%d</td>%s</tr>' % (NAVY, CREAM, f, "".join(cells)))
legend = "".join('<span style="display:inline-flex;align-items:center;gap:5px;margin-right:12px;font-size:11px;"><i style="display:inline-block;width:14px;height:14px;background:%s;"></i>%s</span>' % (TYPE_COL[t], t) for t in TYPOS)
body = ('<div class="sub">Every apartment, floor by floor. ● = on the 15 Sep price list. Level 9 is the Living Deck amenity floor; level 21 the Sky Garden.</div>'
        '<table style="table-layout:fixed;">%s</table><div>%s</div>' % ("".join(grid), legend) +
        prov("Floor plates of the Sanctuary Brief (pages 32-55). Floors 10 to 12 sit above the level-9 deck and carry the large terraces; floors 13 to 20 add the three-bedroom and 1-bed Type C."))
pages.append(B.shell("The stacking plan", "SANCTUARY · FLOOR BY FLOOR", body, today))

# 8 price list
rws = []
for u in sorted(PRICED, key=lambda u: (u[4], u[6])):
    t = u[3]
    rws.append([u[0], TYPOS[t]["label"].replace(" · ", " "), "{:,.0f}".format(u[5]), aed(u[6]), "{:,.0f}".format(u[6] / u[5]), '<span style="font-size:10.5px;">%s</span>' % esc(u[7].title())])
body = ('<div class="sub">The 43 apartments on Prestige One\'s list of 15 September 2026, cheapest first within each size.</div>'
        + table(["UNIT", "TYPE", "SQ FT", "ASKING", "PER SQ FT", "VIEW"], rws, widths=["9%", "22%", "11%", "17%", "12%", "29%"], align=["left", "left", "right", "right", "right", "left"], fs=10.3)
        + prov("Developer's asking prices; subject to availability and change. Sq ft is total area including balcony."))
pages.append(B.shell("What is on the list", "SANCTUARY · PRICE LIST", body.replace("padding:8px 10px", "padding:3.4px 8px"), today))

# 9-11 floor plates, 12-15 unit plans, 16 interiors
def pic_page(title, eyebrow, items, note):
    b = ""
    for name, cap in items:
        b += img(name, "width:706px;height:auto;display:block;border:1px solid %s;" % RULE) + '<div style="font-size:11.5px;color:%s;margin:-6px 0 4px;">%s</div>' % (MUTED, esc(cap))
    return B.shell(title, eyebrow, b + prov(note), today)


N_IMG = ("Plans and images are published by Prestige One in the Sanctuary Brief and reproduced for a buyer considering the building. "
         "All drawings are approximate and not to scale; the developer reserves the right to change them.")
pages.append(pic_page("Floors 1 to 8", "SANCTUARY · LAYOUTS", [("plate_01_08", "Typical floor, levels 1 to 8: six apartments (three 1-bed, three 2-bed)."), ("living_deck", "Level 9: the Living Deck amenity floor.")], N_IMG))
pages.append(pic_page("Floors 10 to 20", "SANCTUARY · LAYOUTS", [("plate_10_12", "Levels 10 to 12: seven apartments, the terrace floors."), ("plate_13_20", "Levels 13 to 20: seven apartments including the 3-bed and 1-bed Type C.")], N_IMG))
tp = list(TYPOS.items())
for i in range(0, len(tp), 2):
    pages.append(pic_page("Unit plans", "SANCTUARY · LAYOUTS", [(d["page"], "%s: %s" % (d["label"], d["note"])) for t, d in tp[i:i + 2]], N_IMG))
pages.append(pic_page("Interiors and amenities", "SANCTUARY · LAYOUTS AND FINISH", [("int_2br", "Two-bedroom living area (developer render)."), ("sky_deck", "Level 21: Sky Garden with skyline pool.")], N_IMG))

if os.environ.get("SANCT_NO_PDF"):
    raise SystemExit(0)   # the web builder only needs the computed figures
out = "".join('<div class="page">%s</div>' % p.replace("__PAGENO__", "Page %d of %d" % (i, len(pages))) for i, p in enumerate(pages, 1))
hp = os.path.join(TMP, "sanctuary_brief.html"); pp = os.path.join(TMP, "sanctuary_brief.pdf")
io.open(hp, "w", encoding="utf-8").write(S.DOC % ("Sanctuary brief", S.CSS, out))
if os.path.exists(pp): os.remove(pp)
ok = S.to_pdf(hp, pp)
print("pages", len(pages), "pdf", ok, os.path.getsize(pp) if ok else 0)
