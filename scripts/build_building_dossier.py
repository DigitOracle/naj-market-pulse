"""The building dossier: everything the building page holds about one building, as a PDF that can be sent to one person.

Kendall, 21 Sep 2026, looking at Prive by DAMAC: "should I be able to pull a PDF from that, like we have the other PDF ... a
more comprehensive PDF that we can capture everything about the building, and send to an individual as well."

The three-page client sheet (build_client_sheet.py) answers "is this the right home?" - price, plans, what else is in the
building. This answers "what IS this building?", which is everything the roll-out has built: the stack floor by floor, the
plate, the flats on a floor, what it sells and lets for, what has sold, the plot and its zoning, the permit, construction from
the project register, and what is around it. It follows the same contract the page does (docs/BUILDING_PAGE_TEMPLATE.md): a
section with no data is left out, never filled in, and every figure names the register it came from.

Two deliberate omissions:
  * who lives here          in the app it is area context with disclosure floors. In a document sent to one buyer it would
                            read as a reason to choose an area, which is exactly what it must never be. It stays in the app.
  * unit-level availability the sheet rail already does live availability for the seven developers whose groups we read; this
                            is the building, not the listing.

  python scripts/build_building_dossier.py --district businessbay --id 170
  python scripts/build_building_dossier.py --district businessbay --id 170 --push
  python scripts/build_building_dossier.py --district businessbay --top 5        the five with the most floors
"""
import argparse, datetime as dt, html, json, math, os, sys, urllib.parse, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
BOARD = os.path.join(ROOT, "data", "board")
OUT = os.path.join(ROOT, "dist_dossier")
sys.path.insert(0, HERE)

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

GOLD, NAVY, INK, MUTED, RULE = "#A8814A", "#17283F", "#22262B", "#626B78", "#E6E1D8"
SQM = 10.7639
TYPE_NAME = {"studio": "Studio", "1": "1 bedroom", "2": "2 bedroom", "3": "3 bedroom", "4": "4 bedroom",
             "office": "Office", "retail": "Retail", "other": "Other"}
CELL = {"studio": "#8FA6A0", "1": "#C5A56A", "2": "#B08A4E", "3": "#8C6B3A", "4": "#6E5230",
        "office": "#7E8C99", "retail": "#A0785E", "other": "#9AA3A0"}
E = lambda s: html.escape(str(s if s is not None else ""))


def fmt(n):
    try:
        return "{:,}".format(int(round(float(n))))
    except (TypeError, ValueError):
        return ""


def aed(n):
    if not n:
        return ""
    n = float(n)
    return "AED %.1fM" % (n / 1e6) if n >= 1e6 else "AED " + fmt(n)


def rd(name):
    p = os.path.join(BOARD, name)
    return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else None


def district_name(slug):
    """What people call the district, not the slug and not the Land Department's area name: a client reads "Dubai Marina", not
    "dubaimarina" and not "Marsa Dubai". The twin's rail is the authority; it is cached so a build works offline."""
    cache = os.path.join(BOARD, "_rail_names.json")
    names = {}
    if os.path.exists(cache):
        try:
            names = json.load(open(cache, encoding="utf-8"))
        except ValueError:
            names = {}
    if slug not in names:
        try:
            import re as _re
            import demo_capture as dc
            from build_avail_index import WORKER
            h = urllib.request.urlopen(urllib.request.Request(
                WORKER + "/skyline/businessbay?key=" + dc.key(), headers={"User-Agent": "najma-market-pulse/1.0"}),
                timeout=60).read().decode("utf-8", "replace")
            m = _re.search(r"var RAIL=(\[.*?\]),CUR=", h, _re.S)
            if m:
                names.update({x["s"]: x["n"] for x in json.loads(m.group(1)) if x.get("n")})
                json.dump(names, open(cache, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        except Exception:
            pass
    return names.get(slug) or slug.replace("_", " ").title()


# --------------------------------------------------------------------------------------------------------------------------
def gather(district, bid):
    """The same files the building page reads, in one record. If the two registers do not both hold it, there is no dossier."""
    stack = rd("stack_%s.json" % district) or {}
    umx = rd("unitmix_%s.json" % district) or {}
    r = (stack.get("buildings_by_id") or {}).get(str(bid))
    u = (umx.get("buildings_by_id") or {}).get(str(bid))
    if not r or not u:
        return None
    units = rd("units_%s.json" % district) or {}
    plates = rd("plates_%s.json" % district) or {}
    anchors = None
    ap = os.path.join(ROOT, "data", "names", "anchors_%s.json" % district)
    if os.path.exists(ap):
        anchors = next((x for x in (json.load(open(ap, encoding="utf-8")).get("anchors") or [])
                        if str(x.get("i")) == str(bid)), None)
    return {"d": district, "id": str(bid), "r": r, "u": u, "stack": stack,
            "flats": (units.get("buildings_by_id") or {}).get(str(bid)),
            "plate": (plates.get("buildings") or {}).get(str(bid)), "plate_note": plates.get("note"),
            "amen": stack.get("district_amenities"), "land_ctx": stack.get("district_land"), "a": anchors or {},
            "district_name": district_name(district)}


# --------------------------------------------------------------------------------------------------------------------------
def plate_svg(G, level):
    """The floor plate, drawn the way the page draws it: the surveyed outline, the homes at the register's sizes (or, where a
    model was handed over, exactly where the model puts them), the cores, and north."""
    b = G["plate"]
    if not b or not b.get("floors"):
        return None, None
    ix = b["floors"].get(str(level))
    if ix is None or not (b.get("plates") or [])[ix:]:
        return None, None
    p = b["plates"][ix]
    if p.get("skip") or not p.get("cells"):
        return None, None
    o = b["outline"]
    xs, ys = o[0::2], o[1::2]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    pad = max(3.0, (x1 - x0) * 0.03)
    W = 980.0
    k = W / (x1 - x0 + 2 * pad)
    H = (y1 - y0 + 2 * pad) * k
    T = lambda a: " ".join("%.1f,%.1f" % ((a[i] - x0 + pad) * k, (y1 - a[i + 1] + pad) * k) for i in range(0, len(a), 2))
    lab = (b.get("labels") or {}).get(str(level)) or {}
    out = ['<svg viewBox="0 0 %d %d" xmlns="http://www.w3.org/2000/svg" class=plate>' % (W, H)]
    out.append('<polygon points="%s" fill="#F4F1EA" stroke="%s" stroke-width="2"/>' % (T(o), NAVY))
    for c in p["cells"]:
        t = lab.get(str(c[2])) or {"studio": "S", "1": "1", "2": "2", "3": "3", "4": "4"}.get(c[0], "")
        out.append('<polygon points="%s" fill="%s" stroke="#FFFFFF" stroke-width="1.6"/>' % (T(c[1]), CELL.get(c[0], CELL["other"])))
        a = c[1]
        cx = sum(a[0::2]) / (len(a) / 2.0)
        cy = sum(a[1::2]) / (len(a) / 2.0)
        w = (max(a[0::2]) - min(a[0::2])) * k
        h = (max(a[1::2]) - min(a[1::2])) * k
        if t and min(w, h) > 11 and max(w, h) > 20:
            out.append('<text x="%.1f" y="%.1f" font-size="%.1f" font-weight="600" text-anchor="middle" fill="#1A1A1A">%s</text>'
                       % ((cx - x0 + pad) * k, (y1 - cy + pad) * k + 4, min(13, max(7.5, k * 1.6)), E(t)))
    for bl in (p.get("blocks") or []):
        out.append('<polygon points="%s" fill="%s"/>' % (T(bl[1]), "#5B6662" if bl[0] == "lift" else "#9A95D6"))
    out.append('<g transform="translate(%d,40) rotate(%.1f)"><circle r="16" fill="none" stroke="%s"/>'
               '<path d="M0,-11 L4.5,6 L0,2.5 L-4.5,6 Z" fill="%s"/><text y="-20" font-size="10" text-anchor="middle" fill="%s">N</text></g>'
               % (W - 42, -float(b.get("north") or 0), GOLD, GOLD, GOLD))
    out.append("</svg>")
    return "".join(out), p


def says_plate(p, note):
    if p.get("basis") == "revit":
        return ("<b>The built layout.</b> The unit numbers, types and sizes are the developer's Revit model of this building, "
                "and each flat is drawn where the model puts it. " + E(note or ""))
    src = {"units": "The unit numbers, types and sizes are the Land Department units register's, one row per unit; they are "
                    "laid round the facade in unit-number order.",
           "municipality": "How many homes this floor carries is the Municipality's count for the floor, shared between the "
                           "types the Land Department register puts on it.",
           "register": "How many homes of each type this floor carries is the Land Department register's units for the type, "
                       "spread evenly over the floors the register gives it."}.get(p.get("basis"), "")
    return ("<b>Indicative layout.</b> The outline is this building's surveyed footprint and the sizes of the homes against "
            "each other are the register's. " + src + " Where each home sits, and where the lifts and stairs are, is not "
            "published for this building.")


# --------------------------------------------------------------------------------------------------------------------------
def sections(G):
    """Each returns (heading, html) or None. A section with nothing behind it is not printed - never filled in."""
    r, u, out = G["r"], G["u"], []
    dld, dm, sales = u.get("dld") or {}, u.get("dm") or {}, u.get("dld_sales") or {}

    def row(k, v):
        return '<div class=row><span>%s</span><b>%s</b></div>' % (E(k), E(v)) if v not in (None, "", 0) else ""

    # the building
    facts = []
    if u.get("developer"):
        facts.append(("Developer", u["developer"]))
    elif dld.get("project"):
        facts.append(("Registered as", dld["project"]))
    if dm.get("floors_label"):
        facts.append(("Stack", " ".join(str(dm["floors_label"]).split())))
    if u.get("total_units") or dld.get("units_registered"):
        facts.append(("Homes registered", fmt(u.get("total_units") or dld.get("units_registered"))))
    if dm.get("height_m"):
        facts.append(("Height", "%d m" % round(dm["height_m"])))
    if dm.get("completed") or dm.get("construction_year"):
        facts.append(("Completed", str(dm.get("completed") or dm.get("construction_year"))[:10]))
    elif dm.get("permitted"):
        facts.append(("Permit", str(dm["permitted"])[:10] + (" · " + dm["dm_status"] if dm.get("dm_status") else "")))
    if u.get("car_parks") or dm.get("indoor_parking"):
        facts.append(("Parking", fmt(u.get("car_parks") or dm.get("indoor_parking")) + " bays"))
    if u.get("elevators") or dm.get("lifts"):
        facts.append(("Lifts", str(u.get("elevators") or dm.get("lifts"))))
    if r.get("area_sqm"):
        facts.append(("Registered floor area", fmt(r["area_sqm"]) + " m²"))
    if r.get("makani", {}) and (r.get("makani") or {}).get("makani"):
        facts.append(("Makani", str(r["makani"]["makani"])))
    if G["a"].get("lat"):
        facts.append(("Position", "%.4f N  %.4f E" % (G["a"]["lat"], G["a"]["lon"])))
    if facts:
        out.append(("The building", "".join(row(k, v) for k, v in facts)))

    # the stack
    fl = r.get("floors") or []
    if fl:
        groups, cur = [], None
        for f in fl:
            lab = {"homes": "homes", "office": "offices", "retail": "retail", "hotel": "hotel", "villa": "villas",
                   "services": "services and parking", "civic": "civic"}.get(f.get("u"), f.get("u"))
            if cur and cur[0] == lab:
                cur[2] = f.get("l")
                cur[3] += f.get("k") or 0
            else:
                cur = [lab, f.get("l"), f.get("l"), f.get("k") or 0]
                groups.append(cur)
        body = "".join('<div class=row><span>%s</span><b>%s</b></div>'
                       % (E("Level %s" % g[1] if g[1] == g[2] else "Levels %s–%s" % (g[1], g[2])),
                          E(g[0] + (" · %d homes" % g[3] if g[3] else "")))
                       for g in groups)
        note = ""
        if r.get("fits") is False:
            note = ('<div class=src>The register describes more levels than this footprint can hold, so the model reads it as '
                    'a podium and the floors are not cut into it.</div>')
        out.append(("The stack · %d levels%s" % (len(fl), " + %d below ground" % r["basements"] if r.get("basements") else ""),
                    body + note))

    # what it sells for
    ts = [t for t in (r.get("types") or []) if t.get("units")]
    if any(t.get("aed") for t in ts):
        rows = ['<table><tr><th>Home</th><th>Launched</th><th>Sold</th><th>Median</th><th>Per sq ft</th></tr>']
        sold = sales.get("sold_by_type") or {}
        for t in ts:
            psf = ""
            if t.get("aed") and t.get("sqm"):
                psf = "AED " + fmt(t["aed"] / (t["sqm"] * SQM))
            rows.append("<tr><td>%s</td><td>%s</td><td>%s</td><td>%s%s</td><td>%s</td></tr>"
                        % (E(t.get("t")), fmt(t["units"]), fmt(sold.get(t.get("t")) or 0) or "—",
                           aed(t.get("aed")) or "—", " est." if t.get("est") else "", psf or "—"))
        rows.append("</table>")
        out.append(("What it sells for", "".join(rows) +
                    '<div class=src>Land Department units register and its recorded sales for this building. "est." marks a '
                    'median carried from the type across the scheme where this building has too few of its own.</div>'))

    # what has sold here
    s = r.get("sales")
    if s:
        body = (row("Registered sales", fmt(s.get("n"))) + row("Median per sq ft", "AED " + fmt(s["psf"]) if s.get("psf") else "")
                + row("Off-plan share", "%d%%" % s["offplan_pct"] if s.get("offplan_pct") is not None else "")
                + row("First and last", "%s to %s" % (s.get("first"), s.get("last"))))
        rec = s.get("recent") or []
        if rec:
            body += '<table><tr><th>Date</th><th>Home</th><th>Size</th><th>Price</th><th></th></tr>'
            for x in rec:
                body += "<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>" % (
                    E(x.get("date")), E(x.get("rooms")), (fmt(x.get("sqft")) + " sq ft") if x.get("sqft") else "—",
                    aed(x.get("price")) or "—", "off-plan" if x.get("offplan") else "resale")
            body += "</table>"
        out.append(("What has sold here", body +
                    '<div class=src>Land Department transaction register, bound to the name <b>%s</b>. The register carries no '
                    'property id on a sale, so these are sales registered against that name.</div>' % E(s.get("name"))))

    # what it lets for
    rent = r.get("rent")
    if rent and rent.get("by_type"):
        body = '<table><tr><th>Home</th><th>Contracts</th><th>Median rent</th><th>New / renewed</th></tr>'
        for t, v in sorted(rent["by_type"].items()):
            body += "<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>" % (
                E(t), fmt(v.get("n")), "AED " + fmt(v.get("aed")),
                "%s / %s" % (fmt(v.get("new")) or 0, fmt(v.get("renew")) or 0))
        body += "</table>"
        out.append(("What it lets for", body +
                    '<div class=src>Ejari contracts registered against the scheme <b>%s</b> (%s contracts). Ejari registers at '
                    'scheme level, never per tower.</div>' % (E(rent.get("scheme")), fmt(rent.get("n")))))

    # construction
    p = r.get("project")
    if p:
        body = (row("Status", p.get("status")) + row("Built", "%d%%" % round(p["pct"]) if p.get("pct") is not None else "")
                + row("Started", p.get("start")) + row("Due", p.get("end")) + row("Escrow agent", p.get("escrow"))
                + row("Homes in the project", fmt(p.get("units"))) + row("Master development", p.get("master")))
        stale = (p.get("pct") or 0) < 100 and (p.get("end") or "") and p["end"] < dt.date.today().isoformat()
        out.append(("Construction · the register", body +
                    '<div class=src>Land Department project register, joined to this building by property id. An escrow agent '
                    'is named for every live launch; a finished scheme no longer needs one. Percent complete and the due date '
                    "are the developer's own reporting to the register, not a survey: across Dubai, 329 live schemes still "
                    'carry a due date that has gone by.%s</div>'
                    % (" <b>This is one of them: the register has it still building against a date that has passed.</b>"
                       if stale else "")))

    # the plot
    land = r.get("land")
    if land:
        body = (row("Land number", land.get("land")) + row("Zoned", land.get("zoned")) + row("Registered use", land.get("use"))
                + row("Plot area", fmt(land["area_sqm"]) + " m²" if land.get("area_sqm") else "")
                + row("Tenure", "Freehold" if land.get("freehold") else "Leasehold / other")
                + row("Registered scheme", land.get("project")))
        plot = r.get("plot") or {}
        if plot.get("n", 0) > 1:
            body += row("On this plot", "%d buildings" % plot["n"] + (" · this is the tallest" if plot.get("tallest") else ""))
        out.append(("The plot", body + '<div class=src>Land Department land registry.</div>'))

    # the permit
    perm = r.get("permit")
    if perm and perm.get("no"):
        out.append(("The building permit", row("Type", perm.get("type")) + row("Number", perm.get("no"))
                    + row("Status", perm.get("status"))
                    + row("Permits on this plot", fmt(perm.get("permits_on_plot")))
                    + '<div class=src>Dubai Municipality building permits, by parcel: the permit is the plot\'s, not solely '
                      'this building\'s.</div>'))

    # around it
    around = []
    if sales.get("metro"):
        around.append(("Nearest metro", sales["metro"]))
    if sales.get("mall"):
        around.append(("Nearest mall", sales["mall"]))
    if sales.get("landmark"):
        around.append(("Nearest landmark", sales["landmark"]))
    schools = ((G["amen"] or {}).get("schools") or [])[:6]
    body = "".join(row(k, v) for k, v in around)
    if schools:
        body += '<table><tr><th>School</th><th>Curriculum</th><th>Rating</th></tr>'
        for s2 in schools:
            body += "<tr><td>%s</td><td>%s</td><td>%s</td></tr>" % (E(s2.get("name")), E(s2.get("curriculum") or "—"),
                                                                    E(s2.get("rating") or "—"))
        body += "</table>"
    if body:
        out.append(("Around it", body +
                    '<div class=src>Landmarks are the Land Department\'s own nearest-to fields. Schools are KHDA, within %s km '
                    'of the centre of %s with their inspection rating - district context, not a distance from this door.'
                    '</div>' % (E((G["amen"] or {}).get("radius_km") or 5), E(G["district_name"]))))

    # what it sees over
    of = r.get("open_from")
    if of:
        DIRN = ["North", "North-east", "East", "South-east", "South", "South-west", "West", "North-west"]
        body = "".join(row(DIRN[i], "open from level %s" % v if v else "blocked")
                       for i, v in enumerate(of) if i < len(DIRN))
        if body:
            out.append(("What it sees over", body +
                        '<div class=src>Measured in the twin against every modelled neighbour within %d m: the level at which '
                        'that side clears what stands in front of it.</div>' % (r.get("open_radius") or 700)))
    return out


# --------------------------------------------------------------------------------------------------------------------------
def build_html(G):
    r, u = G["r"], G["u"]
    dld = u.get("dld") or {}
    name = r.get("name") or "building"
    dev = u.get("developer") or ""
    when = dt.date.today().strftime("%d %B %Y")
    asof = (G["stack"].get("sources") or [""])[0]
    secs = sections(G)

    # the plate for the busiest residential floor, and its flats
    lvl = None
    best = -1
    for f in (r.get("floors") or []):
        if (f.get("k") or 0) > best:
            best, lvl = f.get("k") or 0, f.get("l")
    svg, p = plate_svg(G, lvl) if lvl is not None else (None, None)
    flats = ((G["flats"] or {}).get("floors") or {}).get(str(lvl)) if G["flats"] else None

    plate_block = ""
    if svg:
        rows = ""
        if flats:
            rows = '<table><tr><th>Home</th><th>Type</th><th>Size</th><th>Balcony</th></tr>' + "".join(
                "<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>"
                % (E(x.get("u")), E(x.get("t")), (fmt(x.get("sqft")) + " sq ft") if x.get("sqft") else "—",
                   (fmt(x.get("bal")) + " sq ft") if x.get("bal") else "—") for x in flats[:24]) + "</table>"
            if len(flats) > 24:
                rows += '<div class=src>%d more homes on this floor.</div>' % (len(flats) - 24)
        plate_block = ('<h2>Level %s</h2><div class=two><div>%s</div><div>%s</div></div><div class=src>%s</div>'
                       % (E(lvl), svg, rows, says_plate(p, G["plate_note"])))

    head = "".join('<div class=sec><h2>%s</h2>%s</div>' % (E(h), b) for h, b in secs)
    return """<!doctype html><meta charset=utf-8><title>%(name)s</title><style>
@page{size:A4;margin:14mm 13mm 15mm}
*{box-sizing:border-box}
body{margin:0;font:11px/1.5 "Segoe UI",Helvetica,Arial,sans-serif;color:%(ink)s}
h1{font:600 26px/1.15 Georgia,serif;color:%(navy)s;margin:0 0 2px}
h2{font:600 12px/1.2 "Segoe UI",sans-serif;letter-spacing:.14em;text-transform:uppercase;color:%(gold)s;margin:0 0 7px;
   padding-bottom:4px;border-bottom:1px solid %(rule)s}
.sub{color:%(muted)s;font-size:12px;margin-bottom:14px}
.sec{margin:0 0 15px;break-inside:avoid}
.row{display:flex;justify-content:space-between;gap:12px;padding:3px 0;border-bottom:1px dotted %(rule)s}
.row span{color:%(muted)s}.row b{font-weight:600;text-align:right}
table{width:100%%;border-collapse:collapse;margin:5px 0}
th{font:600 9px/1.4 "Segoe UI";letter-spacing:.09em;text-transform:uppercase;color:%(muted)s;text-align:left;
   border-bottom:1px solid %(rule)s;padding:3px 5px 3px 0}
td{padding:3px 5px 3px 0;border-bottom:1px dotted %(rule)s}
.src{color:%(muted)s;font-size:9px;line-height:1.45;margin-top:5px}
.two{display:grid;grid-template-columns:1.05fr 1fr;gap:14px;align-items:start}
.plate{width:100%%;height:auto}
.cols{column-count:2;column-gap:16px}
.hd{display:flex;justify-content:space-between;align-items:flex-end;border-bottom:2px solid %(navy)s;padding-bottom:8px;margin-bottom:14px}
.ft{margin-top:16px;padding-top:7px;border-top:1px solid %(rule)s;color:%(muted)s;font-size:9px}
.brk{break-before:page}
</style>
<div class=hd><div><h1>%(name)s</h1><div class=sub>%(dev)s%(district)s</div></div>
<div style="text-align:right;color:%(muted)s;font-size:9px">DIGITALCHEMY · AZIMUTH<br>%(when)s</div></div>
<div class=cols>%(head)s</div>
<div class="sec brk">%(plate)s</div>
<div class=ft>Every figure above names the register it came from. The registers: the Dubai Land Department (units, sales,
rents through Ejari, projects, land), Dubai Municipality (the floor register, permits, Makani) and KHDA (schools).
Register data as at %(asof)s. Prepared for one named recipient; it is not a listing and not an offer.<br>
contact@digitalabbot.io · +971 56 227 6093</div>
""" % {"name": E(name), "dev": E(dev + " · " if dev else ""), "district": E(G["district_name"]), "when": E(when),
       "head": head, "plate": plate_block, "asof": E(asof or when), "ink": INK, "navy": NAVY, "gold": GOLD,
       "muted": MUTED, "rule": RULE}


def push(G, pdf_path, pages):
    sys.path.insert(0, HERE)
    from build_avail_index import WORKER, env_token
    tok = env_token("INGEST_TOKEN")
    if not tok:
        print("  push skipped: no INGEST_TOKEN")
        return False
    slug = "b_%s_%s" % (G["d"], G["id"])
    q = urllib.parse.urlencode({"slug": slug, "name": G["r"].get("name") or slug, "pages": pages, "pics": "0",
                                "pics_kind": "dossier"})
    req = urllib.request.Request(WORKER + "/ingest_sheet?" + q, data=open(pdf_path, "rb").read(), method="POST",
                                 headers={"X-Azimuth-Ingest": tok, "Content-Type": "application/pdf",
                                          "User-Agent": "najma-market-pulse/1.0"})
    try:
        r = urllib.request.urlopen(req, timeout=900)
        print("  pushed %s: %s" % (slug, r.read().decode("utf-8", "replace")[:120]))
        return True
    except Exception as e:
        print("  push failed: %s" % str(e)[:160])
        return False


def one(district, bid, do_push):
    G = gather(district, bid)
    if not G:
        print("%s/%s: not in both registers" % (district, bid))
        return False
    os.makedirs(OUT, exist_ok=True)
    stem = "%s_%s" % (district, bid)
    hp = os.path.join(OUT, stem + ".html")
    pp = os.path.join(OUT, stem + ".pdf")
    open(hp, "w", encoding="utf-8").write(build_html(G))
    import build_client_sheet as S
    ok = S.to_pdf(hp, pp)
    if not ok:
        print("  %s: HTML written, PDF not (no Chrome?)  %s" % (stem, hp))
        return False
    pages = 0
    try:
        import fitz
        pages = fitz.open(pp).page_count
    except Exception:
        pass
    print("  %-28s %-34s %4d KB%s" % (stem, (G["r"].get("name") or "")[:34], os.path.getsize(pp) // 1024,
                                      "  %d pages" % pages if pages else ""))
    if do_push:
        push(G, pp, pages or 2)
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--district", required=True)
    ap.add_argument("--id")
    ap.add_argument("--top", type=int, help="the N tallest buildings in the district instead of one id")
    ap.add_argument("--push", action="store_true")
    a = ap.parse_args()
    if a.top:
        stack = rd("stack_%s.json" % a.district) or {}
        ids = sorted((stack.get("buildings_by_id") or {}).items(), key=lambda kv: -len(kv[1].get("floors") or []))[:a.top]
        for i, _ in ids:
            one(a.district, i, a.push)
        return 0
    if not a.id:
        ap.error("--id or --top")
    return 0 if one(a.district, a.id, a.push) else 1


if __name__ == "__main__":
    sys.exit(main())
