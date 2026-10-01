"""The building dossier: everything the building page holds about one building, as a PDF that can be sent to one person.

Kendall, 21 Sep 2026, looking at Prive by DAMAC: "should I be able to pull a PDF from that, like we have the other PDF ... a
more comprehensive PDF that we can capture everything about the building, and send to an individual as well."

The three-page client sheet (build_client_sheet.py) answers "is this the right home?" - price, plans, what else is in the
building. This answers "what IS this building?", which is everything the roll-out has built: the stack floor by floor, the
plate, the flats on a floor, what it sells and lets for, what has sold, the plot and its zoning, the permit, construction from
the project register, and what is around it. It follows the same contract the page does (docs/BUILDING_PAGE_TEMPLATE.md): a
section with no data is left out, never filled in, and every figure names the register it came from.

Who lives in the community is on it at Kendall's instruction (21 Sep, after seeing the first draft without it). It keeps the
rules it has everywhere else: the DEWA customer register at community grain only, communities under 500 homes and shares under
5% unpublished, smaller groups pooled, and the sentence that it describes the community rather than this building and is
context about an area, never a reason to choose one. It is broken by region with the countries inside, because "everyone else,
63%" is the lump Kendall objected to on the page and it tells a reader nothing.

Left out: unit-level availability - the sheet rail already does live availability for the seven developers whose broker groups
we read, and this document is about the building, not the listing.

  python scripts/build_building_dossier.py --district businessbay --id 170
  python scripts/build_building_dossier.py --district businessbay --id 170 --push
  python scripts/build_building_dossier.py --district businessbay --top 5        the five with the most floors
"""
import argparse, datetime as dt, html, json, math, os, re, sys, urllib.parse, urllib.request

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
    n = names.get(slug) or slug.replace("_", " ").title()
    return n.title() if n.isupper() else n


def mark():
    """The Azimuth mark, embedded in the document rather than linked: a PDF that is forwarded must carry its own logo."""
    import base64
    f = os.path.join(ROOT, "data", "brand", "azimuth_mark.png")
    if not os.path.exists(f):
        return ""
    return '<img class=mark src="data:image/png;base64,%s" alt="Azimuth">' % base64.b64encode(open(f, "rb").read()).decode()


def najma_mark():
    """The Najma logo in the header (Kendall, 30 Sep 2026: "ensure the najma logo is on the sheet as well"). It replaces the
    Azimuth mark there - that mark is the same N-and-star emblem without the NAJMA wordmark, so both side by side read as a
    duplicate. From Brand_and_Legal/Logos/Najma_Logo.png, cropped and scaled to print size (the original is 900 KB), embedded."""
    import base64
    f = os.path.join(ROOT, "data", "brand", "najma_logo.png")
    if not os.path.exists(f):
        return ""
    return '<img class=najma src="data:image/png;base64,%s" alt="Najma">' % base64.b64encode(open(f, "rb").read()).decode()


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
# THE HOME TYPES (Kendall, 30 Sep 2026, on a dossier made for "1 bedroom, JVC, AED 65K": "This floor plate is useless ... unless
# somebody asked for a specific floor. What we should be showing is ... the different one bedroom types"). The old page drew
# whichever floor held the most homes - on Binghatti Nova that was level 1, the podium, whose terrace flats are like no other
# floor. A client asking for a one-bedroom wants the KINDS of one-bedroom the building has, how many, where, and what each
# lets and sells for. Homes in the same position on successive floors share a layout (x06 on every floor is one stack), so a
# type is a stack - or several stacks of the same size and balcony - read straight off the Land Department units register.
def _stack_pos(u):
    s = str(u or "").strip()
    return s[-2:] if s.isdigit() and len(s) >= 3 else None


def _med(xs):
    xs = sorted(xs)
    if not xs:
        return None
    n = len(xs)
    return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2.0


def _positions(ps):
    """x04, x06-x11 - the stack positions, consecutive runs joined."""
    nums = sorted(int(p) for p in ps if p and p.isdigit())
    runs, out = [], []
    for n in nums:
        if runs and n == runs[-1][1] + 1:
            runs[-1][1] = n
        else:
            runs.append([n, n])
    for a, b in runs:
        out.append("x%02d" % a if a == b else "x%02d–x%02d" % (a, b))
    return ", ".join(out)


def home_types(G, beds=None):
    """{class: {"types": [...], "special": {level: [flat, ...]}}} from the units register. beds narrows to one class."""
    fl = ((G.get("flats") or {}).get("floors")) or {}
    by_c = {}
    for lvl, us in fl.items():
        try:
            L = int(lvl)
        except (TypeError, ValueError):
            continue
        for x in us or []:
            c = x.get("c")
            if not c or c == "other" or not x.get("sqft") or (beds and c != beds):
                continue
            by_c.setdefault(c, []).append((L, x))
    out = {}
    for c, rows in by_c.items():
        stacks = {}
        for L, x in rows:
            stacks.setdefault(_stack_pos(x.get("u")) or ("u:" + str(x.get("u"))), []).append((L, x))
        norm, special = [], {}
        for pos, us in stacks.items():
            ms, mb = _med([x["sqft"] for _, x in us]), _med([x.get("bal") or 0 for _, x in us])
            keep = []
            for L, x in us:   # a flat unlike the rest of its stack - a podium terrace, a penthouse - is shown on its own
                if len(us) >= 3 and (abs(x["sqft"] - ms) > 0.05 * ms or abs((x.get("bal") or 0) - mb) > max(25, 0.4 * mb)):
                    special.setdefault(L, []).append(x)
                else:
                    keep.append((L, x))
            if len(keep) >= 2:
                norm.append({"pos": pos, "ms": _med([x["sqft"] for _, x in keep]), "mb": _med([x.get("bal") or 0 for _, x in keep]), "units": keep})
            else:
                for L, x in keep:
                    special.setdefault(L, []).append(x)
        types = []
        for st in sorted(norm, key=lambda s: s["ms"]):
            t = types[-1] if types else None
            if t and abs(st["ms"] - t["ms"]) <= 0.025 * t["ms"] and abs(st["mb"] - t["mb"]) <= max(15, 0.2 * t["mb"]):
                t["stacks"].append(st["pos"]); t["units"] += st["units"]
                t["ms"] = _med([x["sqft"] for _, x in t["units"]]); t["mb"] = _med([x.get("bal") or 0 for _, x in t["units"]])
            else:
                types.append({"stacks": [st["pos"]], "units": list(st["units"]), "ms": st["ms"], "mb": st["mb"]})
        for i, t in enumerate(types):
            sz = [x["sqft"] for _, x in t["units"]]; bl = [x.get("bal") or 0 for _, x in t["units"]]; lv = [L for L, _ in t["units"]]
            t.update({"label": chr(65 + i), "n": len(t["units"]), "smin": min(sz), "smax": max(sz), "bmin": min(bl), "bmax": max(bl),
                      "lmin": min(lv), "lmax": max(lv), "where": _positions(t["stacks"])})
        out[c] = {"types": types, "special": special}
    return out


def _latest_csv(prefix):
    """The newest data/<prefix>-YYYY-MM-DD*.csv; of two files for one day, the larger (the other may be a short pull)."""
    import glob
    best = None
    for f in glob.glob(os.path.join(ROOT, "data", prefix + "-20??-??-??*.csv")):
        key = (os.path.basename(f)[len(prefix) + 1:len(prefix) + 11], os.path.getsize(f))
        if best is None or key > best[0]:
            best = (key, f)
    return best[1] if best else None


ROOMS_OF = {"studio": ("studio",), "1": ("1 b/r",), "2": ("2 b/r",), "3": ("3 b/r",), "4": ("4 b/r",)}


def type_prices(types, scheme, c):
    """Each type's rent (Ejari) and sale (Land Department) evidence, placed by registered area. Types whose size ranges overlap
    cannot be told apart by area, so they share one band and one figure, and say so."""
    import csv
    scheme = (scheme or "").strip().lower()
    if not scheme or not types:
        return [], {}
    bands = []   # [lo, hi, [type labels]]
    for t in sorted(types, key=lambda t: t["smin"]):
        lo, hi = t["smin"] * 0.99, t["smax"] * 1.01
        if bands and lo <= bands[-1][1]:
            bands[-1][1] = max(bands[-1][1], hi); bands[-1][2].append(t["label"])
        else:
            bands.append([lo, hi, [t["label"]]])
    ev = {i: {"rent": [], "new": 0, "sale": []} for i in range(len(bands))}
    def band_of(sqft):
        for i, b in enumerate(bands):
            if b[0] <= sqft <= b[1]:
                return i
        return None
    info = {}
    rf = _latest_csv("rents")
    if rf:
        info["rents"] = os.path.basename(rf)
        for row in csv.DictReader(open(rf, encoding="utf-8-sig", errors="replace")):
            if (row.get("PROJECT_EN") or "").strip().lower() != scheme:
                continue
            if (row.get("PROP_SUB_TYPE_EN") or "").strip().lower() not in ("flat", "studio"):
                continue
            try:
                a, amt = float(row.get("ACTUAL_AREA") or 0) * SQM, float(row.get("ANNUAL_AMOUNT") or 0)
            except ValueError:
                continue
            i = band_of(a) if amt > 0 else None
            if i is not None:
                ev[i]["rent"].append(amt); ev[i]["new"] += 1 if (row.get("VERSION_EN") or "").lower().startswith("new") else 0
    tf = _latest_csv("transactions")
    if tf:
        info["sales"] = os.path.basename(tf)
        want = ROOMS_OF.get(c, ())
        for row in csv.DictReader(open(tf, encoding="utf-8-sig", errors="replace")):
            if (row.get("PROJECT_EN") or "").strip().lower() != scheme or (row.get("GROUP_EN") or "") != "Sales":
                continue
            if want and (row.get("ROOMS_EN") or "").strip().lower() not in want:
                continue
            try:
                a, v = float(row.get("PROCEDURE_AREA") or row.get("ACTUAL_AREA") or 0) * SQM, float(row.get("TRANS_VALUE") or 0)
            except ValueError:
                continue
            i = band_of(a) if v > 0 else None
            if i is not None:
                ev[i]["sale"].append(v)
    out = []
    for i, b in enumerate(bands):
        e = ev[i]
        out.append({"labels": b[2], "rent": _med(e["rent"]), "rn": len(e["rent"]), "new": e["new"],
                    "rlo": sorted(e["rent"])[len(e["rent"]) // 4] if len(e["rent"]) >= 4 else None,
                    "rhi": sorted(e["rent"])[(3 * len(e["rent"])) // 4] if len(e["rent"]) >= 4 else None,
                    "sale": _med(e["sale"]), "sn": len(e["sale"])})
    return out, info


def types_block(G, beds=None, plain=False, budget=None):
    """The home-types section: one table per bedroom class (or only the class asked for)."""
    ht = home_types(G, beds)
    if not ht:
        return ""
    r = G["r"]
    scheme = ((r.get("rent") or {}).get("scheme")) or ((r.get("sales") or {}).get("name")) or r.get("name")
    order = [k for k in ("studio", "1", "2", "3", "4") if k in ht]
    html, info_all = "", {}
    for c in order:
        types, special = ht[c]["types"], ht[c]["special"]
        prices, info = type_prices(types, scheme, c)
        info_all.update(info)
        by_label = {}
        for p in prices:
            for lab in p["labels"]:
                by_label[lab] = dict(p, shared=len(p["labels"]) > 1)
        rows = ""
        for t in types:
            p = by_label.get(t["label"]) or {}
            eq = " =" if p.get("shared") else ""
            rent = ("AED %s%s<br><small>%d contract%s%s%s</small>" % (
                fmt(round(p["rent"] / 500.0) * 500 if plain else p["rent"]), eq, p["rn"], "" if p["rn"] == 1 else "s", (", %d new" % p["new"]) if p.get("new") else "",
                (" · middle half %s–%s" % (fmt(p["rlo"]), fmt(p["rhi"]))) if p.get("rlo") else "")) if p.get("rn") else "—"
            sale = ("%s%s<br><small>%d sale%s</small>" % (aed(p["sale"]), eq, p["sn"], "" if p["sn"] == 1 else "s")) if p.get("sn") else "—"
            size = ("%s sq ft" % fmt(t["smin"])) if t["smin"] == t["smax"] else ("%s–%s sq ft" % (fmt(t["smin"]), fmt(t["smax"])))
            bal = ("%s" % fmt(t["bmin"])) if t["bmin"] == t["bmax"] else ("%s–%s" % (fmt(t["bmin"]), fmt(t["bmax"])))
            lv = ("level %d" % t["lmin"]) if t["lmin"] == t["lmax"] else ("levels %d–%d" % (t["lmin"], t["lmax"]))
            rows += ("<tr><td><b>%s</b></td><td>%s</td><td>%s sq ft</td><td>%d<br><small>%s</small></td><td>%s<br><small>%s</small></td>"
                     "<td>%s</td><td>%s</td></tr>" % (t["label"], size, bal, t["n"], "stack" + ("s" if len(t["stacks"]) > 1 else "") + " " + E(t["where"]),
                                                        lv, "", rent, sale)) if not plain else (
                     "<tr><td><b>%s</b></td><td>%s</td><td>%s sq ft</td><td>%d</td><td>%s</td><td>%s</td></tr>"
                     % (t["label"], size, bal, t["n"], lv, rent))
        for L in sorted(special):
            xs = special[L]; sz = [x["sqft"] for x in xs]; bl = [x.get("bal") or 0 for x in xs]
            rows += ('<tr class=sp><td>—</td><td>%s–%s sq ft</td><td>%s–%s sq ft</td><td>%d</td><td>level %d<br><small>%s</small></td>'
                     '<td colspan=2><small>unlike the rest of their stacks%s - priced one by one, not as a type</small></td></tr>'
                     % (fmt(min(sz)), fmt(max(sz)), fmt(min(bl)), fmt(max(bl)), len(xs), L, E(", ".join(str(x.get("u")) for x in xs[:12])),
                        " (larger terraces)" if max(bl) > 2 * (_med([t["mb"] for t in types]) or 1) else ""))
            if plain:
                rows = rows.replace("<td colspan=2><small>unlike", "<td><small>unlike").replace("unlike the rest of their stacks", "one-off homes on this level").replace(" - priced one by one, not as a type", ", each different")
        if budget:   # v273 - what the client's budget gets them in this building, in one plain paragraph
            within, near, over, none = [], [], [], []
            for t in types:
                pr = by_label.get(t["label"]) or {}
                (none if not pr.get("rn") else within if pr["rent"] <= budget * 1.03 else near if pr["rent"] <= budget * 1.10 else over).append((t, pr))
            def _nm(xs):
                labs = [t["label"] for t, _ in xs]
                return ("type " + labs[0]) if len(labs) == 1 else ("types " + ", ".join(labs[:-1]) + " and " + labs[-1])
            def _sz(xs):
                return "%s\u2013%s sq ft" % (fmt(min(t["smin"] for t, _ in xs)), fmt(max(t["smax"] for t, _ in xs)))
            said = []
            if within:
                said.append("%s (%s) let for a median of about AED %s \u2014 within budget" % (_nm(within), _sz(within), fmt(round(_med([p["rent"] for _, p in within]) / 500.0) * 500)))
            if near:
                said.append("%s (%s) at about AED %s \u2014 a little above" % (_nm(near), _sz(near), fmt(round(_med([p["rent"] for _, p in near]) / 500.0) * 500)))
            if over:
                said.append("%s (%s) at about AED %s \u2014 above it" % (_nm(over), _sz(over), fmt(round(_med([p["rent"] for _, p in over]) / 500.0) * 500)))
            if none:
                said.append("%s (%s) had no lets registered in the period, so their rent is not known" % (_nm(none), _sz(none)))
            if said:
                html += '<div class=budget><b>At AED %s a year:</b> %s.</div>' % (fmt(budget), "; ".join(said))
        name = TYPE_NAME.get(c, c)
        html += ('<h3>%s · %d types across %d homes</h3>' % (E(name), len(types), sum(t["n"] for t in types) + sum(len(v) for v in special.values()))
                 + ('<table class=types><tr><th>Type</th><th>Size</th><th>Balcony</th><th>Homes</th><th>Floors</th><th>Rents for, a year</th></tr>' if plain else '<table class=types><tr><th>Type</th><th>Size</th><th>Balcony</th><th>Homes</th><th>Where</th><th>Rents for, a year</th><th>Sold for</th></tr>')
                 + rows + "</table>")
    if not html:
        return ""
    title = ("The %s types" % TYPE_NAME.get(beds, beds).lower().replace(" bedroom", "-bedroom")) if beds else "The home types"
    note = ("Types are read from the Land Department units register: homes in the same position on successive floors share a layout, "
            "so a type is a stack of alike homes (x06 = flat 06 on every floor), grouped with any other stack of the same size and balcony. "
            "Sizes are as registered. Rents are Ejari contracts registered against the scheme <b>%s</b>%s; sales are Land Department sales%s. "
            "Both are placed on a type by their registered area; where two types are the same size their contracts cannot be told apart "
            "and share one figure (marked =). Homes unlike the rest of their stack - a podium terrace, a penthouse - are listed on their own. "
            "Which of these is free today is not in any register: check with the building's leasing team or the listing broker."
            % (E(scheme), (" (%s)" % E(info_all["rents"])) if info_all.get("rents") else "", (" (%s)" % E(info_all["sales"])) if info_all.get("sales") else ""))
    if plain:
        note = ("Each type is a set of identical homes in the same position on every floor, as registered with the Dubai Land Department. "
                "Rents are what these homes were actually let for, from contracts registered with Ejari%s, matched to a type by size; "
                "types of the same size share one figure (marked =). Which homes are free today is confirmed with the leasing team."
                % ((" (%s)" % E(info_all["rents"])) if info_all.get("rents") else ""))
    return '<div class=sec><h2>%s%s</h2>%s<div class=src>%s</div></div>' % (ICON.get("plate", ""), E(title), html, note)


# v273 - when the units register holds no flat-by-flat record for a building (Bloom Heights, Binghatti Amber on 30 Sep 2026),
# the types table cannot be drawn - but a client asking "a 1-bed for AED 65K" still needs the one figure that matters: what
# 1-bed homes here actually let for. From the Ejari contracts registered against the scheme, bedrooms estimated from size with
# the bands measured on 760,600 contracts (data/dld/rent_bed_bands.json); the upper edge is held at the 1-bed 75th percentile
# (84 m2) because in JVC 2-beds start near there. Identical contracts are counted once (Ejari files some twice).
def ejari_fallback(G, beds, budget=None):
    import csv
    if not beds:
        return ""
    r = G["r"]
    scheme = (((r.get("rent") or {}).get("scheme")) or r.get("name") or "").strip().lower()
    rf = _latest_csv("rents")
    if not scheme or not rf:
        return ""
    try:
        bb = json.load(open(os.path.join(ROOT, "data", "dld", "rent_bed_bands.json"), encoding="utf-8"))["flat"]
    except Exception:
        bb = {"city": {"cuts": [52, 92, 162], "quantiles": {}}, "areas": {}}
    rows, seen, area = [], set(), None
    for row in csv.DictReader(open(rf, encoding="utf-8-sig", errors="replace")):
        if (row.get("PROJECT_EN") or "").strip().lower() != scheme:
            continue
        if (row.get("PROP_SUB_TYPE_EN") or "").strip().lower() not in ("flat", "studio"):
            continue
        k = (row.get("REGISTRATION_DATE"), row.get("START_DATE"), row.get("END_DATE"), row.get("ANNUAL_AMOUNT"), row.get("ACTUAL_AREA"), row.get("VERSION_EN"))
        if k in seen:
            continue
        seen.add(k)
        try:
            rows.append((float(row.get("ACTUAL_AREA") or 0), float(row.get("ANNUAL_AMOUNT") or 0), (row.get("VERSION_EN") or "").lower().startswith("new"), (row.get("REGISTRATION_DATE") or "")[:10]))
        except ValueError:
            continue
        area = area or row.get("AREA_EN")
    cuts = ((bb.get("areas") or {}).get(area) or {}).get("cuts") or bb["city"]["cuts"]
    q75 = (((bb.get("city") or {}).get("quantiles") or {}).get(beds) or {}).get("0.75")
    idx = {"studio": 0, "1": 1, "2": 2, "3": 3}.get(beds)
    if idx is None:
        return ""
    lo = 0 if idx == 0 else cuts[idx - 1]
    hi = cuts[idx] if idx < len(cuts) else 10 ** 6
    if q75:
        hi = min(hi, q75)
    got = [x for x in rows if lo <= x[0] < hi and x[1] > 0]
    if len(got) < 3:
        return ""
    rents = sorted(x[1] for x in got)
    med = _med(rents); q1, q3 = rents[len(rents) // 4], rents[(3 * len(rents)) // 4]
    r500 = lambda v: fmt(round(v / 500.0) * 500)
    size = "%s–%s sq ft" % (fmt(min(x[0] for x in got) * SQM), fmt(max(x[0] for x in got) * SQM))
    name = TYPE_NAME.get(beds, beds).lower().replace(" bedroom", "-bedroom")
    body = (row_html("Typical rent", "about AED %s a year" % r500(med)) + row_html("Middle half of rents", "AED %s–%s" % (r500(q1), r500(q3)))
            + row_html("Homes let", "%d, %d of them new lettings" % (len(got), sum(1 for x in got if x[2])))
            + row_html("Sizes let", size) + row_html("Latest contract", max(x[3] for x in got)))
    if budget:
        verdict = "within budget" if med <= budget * 1.03 else "a little above" if med <= budget * 1.10 else "above it"
        body = '<div class=budget><b>At AED %s a year:</b> %s homes here let for a median of about AED %s — %s.</div>' % (fmt(budget), name, r500(med), verdict) + body
    note = ("What %s homes in this building were actually let for, from contracts registered with Ejari (%s), counted once each. "
            "Ejari rarely records bedrooms, so a %s is read from size (%s–%s m²). The Land Department holds no flat-by-flat "
            "record for this building, so its layouts cannot be listed type by type. Which homes are free is confirmed with the leasing team."
            % (name, E(os.path.basename(rf)), name, fmt(lo), fmt(hi)))
    return '<div class=sec><h2>%sWhat a %s here lets for</h2>%s<div class=src>%s</div></div>' % (ICON.get("plate", ""), E(name), body, note)


def row_html(k, v):
    return '<div class=row><span>%s</span><b>%s</b></div>' % (E(k), E(v)) if v not in (None, "", 0) else ""


# v273 - what the registers cannot say and a client asks first: what it looks like, the gym, the pool, the plans (Kendall,
# 30 Sep 2026). From data/brand/buildings/<district>_<id>/brochure.json, sourced from the developer's OWN project page and
# credited under every photo - never a listing portal (a portal once put the wrong building's pictures on a live sheet).
def _brochure(G):
    d = os.path.join(ROOT, "data", "brand", "buildings", "%s_%s" % (G["d"], G["id"]))
    f = os.path.join(d, "brochure.json")
    if not os.path.exists(f):
        return None, d
    try:
        return json.load(open(f, encoding="utf-8")), d
    except Exception:
        return None, d


def _embed(path, max_w=1400):
    """An image as a data URI, scaled down and re-encoded so a forwarded PDF stays small."""
    import base64, io as _io
    try:
        from PIL import Image
        im = Image.open(path)
        im = im.convert("RGB") if im.mode not in ("RGB", "L") else im
        if im.width > max_w:
            im = im.resize((max_w, round(im.height * max_w / im.width)), Image.LANCZOS)
        buf = _io.BytesIO(); im.save(buf, "JPEG", quality=82, optimize=True)
        return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
    except Exception:
        return ""


def _credit(x, b):
    u = (x or {}).get("source_url") or (b or {}).get("source_url") or ""
    host = re.sub(r"^https?://(www\.)?", "", u).split("/")[0] if u else ""
    return ("from %s" % E(host)) if host else ""


def brochure_hero(G):
    b, d = _brochure(G)
    ph = (b or {}).get("photos") or []
    ext = next((p for p in ph if "exterior" in (p.get("file") or "").lower()), ph[0] if ph else None)
    if not ext:
        return ""
    src = _embed(os.path.join(d, ext["file"]))
    return ('<img class=hero src="%s" alt="%s"><div class=cap>%s · %s</div>' % (src, E(ext.get("caption") or ""), E(ext.get("caption") or ""), _credit(None, b))) if src else ""


def brochure_block(G):
    b, d = _brochure(G)
    if not b:
        return ""
    out = ""
    am = b.get("amenities") or []
    ph = [p for p in (b.get("photos") or []) if "exterior" not in (p.get("file") or "").lower()]
    if am or ph:
        out += '<h3>In the building</h3>'
        if am:
            out += '<ul class=am>' + "".join("<li>%s</li>" % E(a) for a in am) + "</ul>"
        imgs = [(p, _embed(os.path.join(d, p["file"]), 700)) for p in ph[:6]]
        imgs = [(p, s) for p, s in imgs if s]
        if imgs:
            out += '<div class=gal>' + "".join('<figure style="margin:0"><img src="%s" alt="%s"><div class=cap>%s</div></figure>'
                                              % (s, E(p.get("caption") or ""), E(p.get("caption") or "")) for p, s in imgs) + "</div>"
        out += '<div class=src>Amenities and photos %s, the developer\'s own project page (retrieved %s).</div>' % (_credit(None, b), E(b.get("retrieved") or ""))
    pl = b.get("plans") or []
    pimgs = [(p, _embed(os.path.join(d, p["file"]), 900)) for p in pl[:4]]
    pimgs = [(p, s) for p, s in pimgs if s]
    if pimgs:
        out += '<h3>Floor plans</h3><div class=plans>' + "".join('<figure style="margin:0"><img src="%s"><div class=cap>%s · %s</div></figure>'
                                                               % (s, E(p.get("caption") or ""), _credit(None, b)) for p, s in pimgs) + "</div>"
    return '<div class=sec>%s</div>' % out if out else ""


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
    # a floor's labels are a map of cell index -> unit number, or a plain list in the same order; the twin reads both
    lab = (b.get("labels") or {}).get(str(level)) or {}
    if isinstance(lab, list):
        lab = {str(i): v for i, v in enumerate(lab) if v}
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


# A line icon per section and per kind of row. Inline SVG, one stroke colour, so they print crisply at any size and the file
# carries no font or image dependency - the house rule for HTML (emoji would render as someone else's artwork, in colour,
# differently on every machine).
def _ic(d, fill=""):
    return ('<svg class=ic viewBox="0 0 24 24" fill="%s" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" '
            'stroke-linejoin="round">%s</svg>' % (fill or "none", d))


ICON = {
    "building": _ic('<path d="M4 21V6l7-3v18"/><path d="M11 21V9l8 3v9"/><path d="M7 9h1M7 13h1M7 17h1M15 14h1M15 18h1"/>'),
    "stack": _ic('<path d="M4 18h16M4 14h16M4 10h16M4 6h16"/><path d="M8 6v12"/>'),
    "sells": _ic('<path d="M20.6 13.4 12 22l-9-9V3h10z"/><circle cx="8" cy="8" r="1.4"/>'),
    "sold": _ic('<path d="M3 17l5-5 4 3 6-7"/><path d="M15 8h4v4"/>'),
    "lets": _ic('<path d="M3 11l9-7 9 7"/><path d="M5 10v10h14V10"/><path d="M10 20v-6h4v6"/>'),
    "build": _ic('<path d="M3 18h18"/><path d="M5 18V9a7 7 0 0 1 14 0v9"/><path d="M12 2v3"/>'),
    "plot": _ic('<path d="M3 20h18M6 20V9l6-4 6 4v11"/><path d="M3 9l9-6 9 6"/>'),
    "permit": _ic('<path d="M7 3h10l3 3v15H7z" /><path d="M10 9h7M10 13h7M10 17h4"/>'),
    "around": _ic('<circle cx="12" cy="10" r="3"/><path d="M12 22s7-6.2 7-12a7 7 0 1 0-14 0c0 5.8 7 12 7 12z"/>'),
    "views": _ic('<path d="M2 12s4-6 10-6 10 6 10 6-4 6-10 6S2 12 2 12z"/><circle cx="12" cy="12" r="2.4"/>'),
    "plate": _ic('<path d="M3 3h18v18H3z"/><path d="M3 9h18M9 3v18M15 9v12"/>'),
    "shops": _ic('<path d="M4 8h16l-1.2 12H5.2z"/><path d="M9 8a3 3 0 0 1 6 0"/><path d="M4 8l1.6-4h12.8L20 8"/>'),
    "people": _ic('<circle cx="9" cy="8" r="3"/><path d="M3 20a6 6 0 0 1 12 0"/><path d="M16 5.5a3 3 0 0 1 0 5.8"/><path d="M17.5 20a6 6 0 0 0-2-4.5"/>'),
}
ROW_ICON = {"Nearest metro": _ic('<circle cx="12" cy="12" r="9"/><path d="M8 15l4-7 4 7"/>'),
            "Nearest mall": _ic('<path d="M5 8h14l-1 12H6z"/><path d="M9 8a3 3 0 0 1 6 0"/>'),
            "Nearest landmark": _ic('<path d="M12 2l2.4 6.4H21l-5.2 4 2 6.6-5.8-4.2L6.2 19l2-6.6L3 8.4h6.6z"/>')}


def head_for(title):
    t = title.lower()
    for k, key in (("the building permit", "permit"), ("the building", "building"), ("the stack", "stack"),
                   ("sells", "sells"), ("sold here", "sold"), ("lets", "lets"), ("construction", "build"),
                   ("the plot", "plot"), ("around", "around"), ("sees over", "views"), ("level", "plate"),
                   ("shops", "shops"), ("who lives", "people")):
        if k in t:
            return ICON[key]
    return ""


# --------------------------------------------------------------------------------------------------------------------------
def near(G, kinds, n=5, max_km=4.0):
    """The nearest of each kind to THIS building, straight-line. Never walking minutes: every routed estimate we checked said
    8-13 minutes where the truth was 5, so the sheets have always given metres and said they are as the crow flies."""
    a = G["a"]
    if not a.get("lat"):
        return []
    items = (rd("amenities.json") or {}).get("items") or []
    lat, lon = a["lat"], a["lon"]
    k = math.cos(math.radians(lat))
    out = []
    for i in items:
        if i.get("k") not in kinds or not i.get("lat"):
            continue
        d = math.hypot((i["lon"] - lon) * k, i["lat"] - lat) * 111320
        if d <= max_km * 1000:
            out.append((d, i))
    out.sort(key=lambda x: x[0])
    seen, keep = set(), []
    for d, i in out:
        nm = (i.get("n") or "").strip()
        if not nm or nm.lower() in seen:
            continue
        seen.add(nm.lower())
        keep.append((d, i))
        if len(keep) >= n:
            break
    return keep


def people_of(G):
    """The community's resident mix, from the DEWA customer register. Kendall asked for it on the dossier (21 Sep 2026); it
    carries its own disclosure floors - communities under 500 homes are not published, shares under 5% stay pooled - and the
    sentence that goes with it everywhere it appears: it is context about an area, never a reason to choose one."""
    m = None
    f = os.path.join(ROOT, "data", "internal", "community_resident_mix.json")
    if os.path.exists(f):
        m = json.load(open(f, encoding="utf-8"))
    if not m:
        return None
    want = "".join(ch for ch in (G["district_name"] or "").lower() if ch.isalnum())
    for c in (m.get("communities") or []):
        names = [c.get("name")] + list(c.get("known") or [])
        if any("".join(ch for ch in str(x or "").lower() if ch.isalnum()) == want for x in names):
            return {"c": c, "rules": m.get("rules") or {}}
    return None



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
    if facts and G.get("audience") == "rent":   # v273 - a tenant's version: plain words, no register-only rows
        homes = u.get("total_units") or dld.get("units_registered")
        cars = u.get("car_parks") or dm.get("indoor_parking")
        keep = {"Developer": "Developer", "Homes registered": "Homes in the building", "Height": "Height", "Completed": "Completed",
                "Lifts": "Lifts", "Stack": "Floors"}
        facts = [(keep[k], v) for k, v in facts if k in keep]
        if cars:
            facts.append(("Parking", "%s spaces for %s homes" % (fmt(cars), fmt(homes)) if homes else fmt(cars) + " spaces"))
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
            n_sold = sold.get(t.get("t")) or 0
            pct = min(100, round(100.0 * n_sold / t["units"])) if t["units"] else 0
            rows.append('<tr><td><span class=swatch style="background:%s"></span>%s</td><td>%s</td>'
                        '<td>%s<div class=mini><i style="width:%d%%"></i></div></td><td>%s%s</td><td>%s</td></tr>'
                        % (CELL.get(t.get("c") or "other", CELL["other"]), E(t.get("t")), fmt(t["units"]),
                           (fmt(n_sold) + " · %d%%" % pct) if n_sold else "—", pct,
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

    # when it filled up - the only thing on this document that says a building is lived in rather than sold or let
    oc = r.get("occupancy")
    if oc and oc.get("connections"):
        dist = (G["stack"].get("district_occupancy") or {})
        body = (row("Meters connected", fmt(oc["connections"]))
                + row("First connection", oc.get("first")) + row("Most recent", oc.get("last"))
                + row("In 2025", fmt(oc.get("y2025")) if oc.get("y2025") else "")
                + row("In 2024", fmt(oc.get("y2024")) if oc.get("y2024") else "")
                + row("Homes / commercial", ("%s / %s" % (fmt(oc.get("residential")), fmt(oc.get("commercial") or 0)))
                      if oc.get("residential") else ""))
        out.append(("When it filled up", body +
                    "<div class=src><b>A connection is not a home.</b> One home let three times is three connections, so this "
                    "cannot be divided by the number of homes to give an occupancy rate. It is DEWA's record of meters "
                    "connected in this building, matched to it through its own entrance, and it is the only figure here that "
                    "says a building is lived in rather than sold or let. Months only.%s</div>"
                    % (" %s smaller buildings in this district are withheld entirely: below %s connections the figure stops "
                       "being a statistic and becomes a household." % (fmt(dist["withheld"]), dist.get("floor"))
                       if dist.get("withheld") else "")))

    # who designed it and who built it - the Municipality's contractor and consultant registers, reached through the
    # crosswalk. A team is the PARCEL's: where a plot holds several buildings the firm built something on that plot and
    # not necessarily this tower, so it is labelled the way the permit already is.
    tm = r.get("team")
    if tm and (tm.get("contractor") or tm.get("consultant")):
        many = (tm.get("on_plot") or 1) > 1
        body = (row("Built by", tm.get("contractor")) + row("Designed by", tm.get("consultant"))
                + row("Project type", tm.get("type")) + row("Recorded as", tm.get("building_type"))
                + row("First building permit", tm.get("permit")) + row("Project status", tm.get("status")))
        st = r.get("stage") or {}
        if st.get("stage"):
            body += row("Municipality's stage", st["stage"])
        if st.get("cost"):
            body += row("Declared building cost", "AED " + fmt(st["cost"]))
        out.append(("Designed and built by", body +
                    '<div class=src>Dubai Municipality contractor and consultant registers, joined by parcel through the Land '
                    "Department's building crosswalk.%s%s</div>"
                    % (" This plot carries %d buildings, so the firms are the plot's and not necessarily this one's."
                       % tm["on_plot"] if many else "",
                       " The stage is the Municipality's own record of how far construction has got - a second opinion beside "
                       "the developer's percent complete below, not a correction to it." if st.get("stage") else "")))

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
    body = "".join(('<div class=row><span>%s%s</span><b>%s</b></div>' % (ROW_ICON.get(k, ""), E(k), E(v)))
                   for k, v in around)
    if schools:
        body += '<table><tr><th>School</th><th>Curriculum</th><th>Rating</th></tr>'
        for s2 in schools:
            body += "<tr><td>%s</td><td>%s</td><td>%s</td></tr>" % (E(s2.get("name")), E(s2.get("curriculum") or "—"),
                                                                    E(s2.get("rating") or "—"))
        body += "</table>"
    if body:
        out.append(("Around it", body +
                    '<div class=src>Stops and stations are the RTA\'s own layers, measured straight-line from this building. '
                    'Landmarks are the Land Department\'s own nearest-to fields, which describe the project and carry no '
                    'distance. Schools are KHDA, within %s km '
                    'of the centre of %s with their inspection rating - district context, not a distance from this door.'
                    '</div>' % (E((G["amen"] or {}).get("radius_km") or 5), E(G["district_name"]))))

    # shops and groceries
    shops = near(G, ("supermarket", "mall"), 6)
    if shops:
        body = "".join('<div class=row><span>%s%s<br><small>%s</small></span><b>%s</b></div>'
                       % (ROW_ICON["Nearest mall"], E(i.get("n")), E("supermarket" if i.get("k") == "supermarket" else "mall"),
                          ("%d m" % round(d)) if d < 1000 else ("%.1f km" % (d / 1000.0)))
                       for d, i in shops)
        out.append(("Shops and groceries", body +
                    '<div class=src>The nearest of each, measured straight-line from this building - not walking minutes, '
                    "which every routed estimate we have checked has overstated. Source: OpenStreetMap and the app's own "
                    'amenity register.</div>'))

    # who lives in the community
    pp = people_of(G)
    if pp:
        c, rules = pp["c"], pp["rules"]
        # by region, then the countries inside it - "everyone else, 63%" tells a reader nothing, which is exactly what
        # Kendall said about the same lump on the page (21 Sep 2026)
        regions = sorted((c.get("regions") or []), key=lambda x: -(x.get("pct") or 0))[:6]
        mix = (c.get("mix") or [])[:6]
        if regions or mix:
            body = ""
            for rg in regions:
                inside = ", ".join("%s %d%%" % (n2, v) for n2, v in (rg.get("countries") or [])[:4])
                body += ('<div class=row><span>%s%s</span><b>%d%%</b></div>'
                         '<div class=mini style="width:100%%"><i style="width:%d%%"></i></div>'
                         % (E(rg.get("name")), ("<br><small>" + E(inside) + "</small>") if inside else "",
                            rg.get("pct") or 0, min(100, rg.get("pct") or 0)))
            if not regions:
                body = "".join('<div class=row><span>%s</span><b>%s%%</b></div>'
                               '<div class=mini style="width:100%%"><i style="width:%d%%"></i></div>'
                               % (E(n2), v, min(100, v)) for n2, v in mix)
            if c.get("noNationalityPct"):
                body += ('<div class=row><span>Not stated on the account</span><b>%d%%</b></div>'
                         % c["noNationalityPct"])
            out.append(("Who lives in %s" % E(c.get("name", "").title()), body +
                        '<div class=src>The community&rsquo;s resident mix, from the DEWA customer register%s. Shares under %s%% '
                        'and communities under %s homes are not published, and smaller groups stay pooled, so nobody can be '
                        'identified by subtraction. It describes the whole community, not this building, and it is context '
                        'about an area - never a reason to choose one.</div>'
                        % ((", %s accounts" % fmt(c["accounts"])) if c.get("accounts") else "",
                           rules.get("minSharePct", 5), fmt(rules.get("minResidentialAccounts", 500)))))

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
    rent = G.get("audience") == "rent"
    if rent:   # v273 - what a tenant asked for; the buyer and investor material stays in the full dossier
        TENANT = ("The building", "Around it", "Shops and groceries", "What it sees over")
        secs = [(h, b) for h, b in secs if h in TENANT]
        secs = [("Views" if h == "What it sees over" else h,
                 b.replace(">blocked<", ">faces the next building<") if h == "What it sees over" else b) for h, b in secs]

    # ---- the floor page: only when a floor was asked for (--floor). v273: it used to draw whichever floor held the most homes,
    # which answers a question nobody asked - the home types below answer the one they did (Kendall, 30 Sep 2026). --------------
    lvl = G.get("floor")
    if lvl is not None:
        lvl = next((f.get("l") for f in (r.get("floors") or []) if str(f.get("l")) == str(lvl)), lvl)
    svg, p = plate_svg(G, lvl) if lvl is not None else (None, None)
    flats = ((G["flats"] or {}).get("floors") or {}).get(str(lvl)) if G["flats"] else None

    plate_block = ""
    if svg:
        # every level the register draws with this same plate, so the page says what it covers instead of one arbitrary floor
        pb = G["plate"]
        ix = pb["floors"].get(str(lvl))
        same = [k for k, v in pb["floors"].items() if v == ix]
        rng = ""
        if len(same) > 1:
            def _n(x):
                try:
                    return int(x)
                except (TypeError, ValueError):
                    return None
            nums = sorted(x for x in (_n(k) for k in same) if x is not None)
            if nums and nums[-1] - nums[0] + 1 == len(nums):
                rng = "Levels %d to %d are drawn to this same plate." % (nums[0], nums[-1])
            else:
                rng = "%d levels are drawn to this same plate." % len(same)

        # what is on the floor: the flats where the register reaches them, the type counts where it does not
        side = ""
        if flats:
            side = ('<h3>The homes on this floor · %d</h3>' % len(flats)
                    + '<table><tr><th>Home</th><th>Type</th><th>Size</th><th>Balcony</th></tr>' + "".join(
                        '<tr><td><span class=swatch style="background:%s"></span>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>'
                        % (CELL.get(x.get("c") or "other", CELL["other"]), E(x.get("u")), E(x.get("t")),
                           (fmt(x.get("sqft")) + " sq ft") if x.get("sqft") else "—",
                           (fmt(x.get("bal")) + " sq ft") if x.get("bal") else "—") for x in flats[:26]) + "</table>"
                    + ('<div class=src>%d more homes on this level.</div>' % (len(flats) - 26) if len(flats) > 26 else ""))
        else:
            counts = p.get("counts") or []
            by_t = {t.get("c"): t for t in (r.get("types") or []) if t.get("c")}
            if counts:
                side = ('<h3>What stands on this floor</h3><table><tr><th>Home</th><th>On this floor</th>'
                        '<th>Size here</th><th>In the building</th></tr>' + "".join(
                            '<tr><td><span class=swatch style="background:%s"></span>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>'
                            % (CELL.get(c[0], CELL["other"]), E(TYPE_NAME.get(c[0], c[0])), c[1],
                               (fmt(c[2] * SQM) + " sq ft") if len(c) > 2 and c[2] else "—",
                               fmt((by_t.get(c[0]) or {}).get("units")) or "—")
                            for c in sorted(counts, key=lambda c: -c[1])) + "</table>"
                        + '<div class=src>The unit numbers are not drawn: the Land Department units register does not reach '
                          'this building, so the homes are placed by count and size, not by address.</div>')
        legend = "".join('<span class=key><i style="background:%s"></i>%s</span>'
                         % (CELL.get(k, CELL["other"]), E(v)) for k, v in TYPE_NAME.items()
                         if any(c[0] == k for c in p["cells"]))
        plate_block = ('<h2>%sThe floor plate · level %s</h2>'
                       '<div class=two><div>%s<div class=legend>%s</div>%s</div><div>%s</div></div>'
                       '<div class=src>%s</div>'
                       % (ICON["plate"], E(lvl), svg, legend,
                          ('<div class=rng>%s</div>' % E(rng)) if rng else "", side, says_plate(p, G["plate_note"])))

    plate_block = (types_block(G, G.get("beds"), plain=rent, budget=G.get("budget")) or ejari_fallback(G, G.get("beds"), G.get("budget"))) + brochure_block(G) + plate_block
    hero = brochure_hero(G)
    head = "".join('<div class=sec><h2>%s%s</h2>%s</div>' % (head_for(h), E(h), b) for h, b in secs)
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
.brand{display:flex;align-items:center;gap:9px;text-align:right;color:%(muted)s;font:600 10px/1.5 "Segoe UI";letter-spacing:.16em}
.brand small{letter-spacing:.04em;font-weight:400;font-size:8.5px}
.mark{height:54px;width:auto}
.najma{height:84px;width:auto;margin-right:4px}
.agent{margin-top:14px;padding:8px 10px;border:1px solid %(gold)s;border-radius:6px;font-size:11px}.agent b{color:%(gold)s;margin-right:8px}
.hero{width:100%%;max-height:230px;object-fit:cover;border-radius:6px;margin:0 0 6px}.cap{color:%(muted)s;font-size:8.5px;margin:0 0 12px}
.gal{display:grid;grid-template-columns:repeat(3,1fr);gap:6px}.gal img{width:100%%;height:110px;object-fit:cover;border-radius:4px}
.plans{display:grid;grid-template-columns:repeat(2,1fr);gap:8px}.plans img{width:100%%;height:auto;border:1px solid %(rule)s}
.am{columns:2;margin:0;padding-left:16px}.budget{margin:8px 0;padding:7px 9px;background:#FAF8F3;border-left:3px solid %(gold)s;font-size:11px}
table.types td{vertical-align:top}table.types small{color:%(muted)s;font-size:8.5px}tr.sp td{color:%(muted)s}
.ft{margin-top:16px;padding-top:7px;border-top:1px solid %(rule)s;color:%(muted)s;font-size:9px}
.rng{margin-top:7px;padding:6px 8px;background:#FAF8F3;border-left:2px solid %(gold)s;font-size:9.5px;color:%(muted)s}
h3{font:600 10px/1.3 "Segoe UI";letter-spacing:.1em;text-transform:uppercase;color:%(navy)s;margin:0 0 5px}
.ic{width:13px;height:13px;vertical-align:-2px;margin-right:6px;color:%(gold)s;flex:none}
.row .ic{width:11px;height:11px;color:%(muted)s;margin-right:5px}
.legend{display:flex;flex-wrap:wrap;gap:4px 12px;margin-top:6px}
.key{display:flex;align-items:center;gap:5px;font-size:9px;color:%(muted)s}
.key i{width:9px;height:9px;border-radius:2px;display:inline-block}
.swatch{width:8px;height:8px;border-radius:2px;display:inline-block;margin-right:6px;vertical-align:0}
.mini{height:3px;background:%(rule)s;border-radius:2px;margin-top:3px;width:62px}
.mini i{display:block;height:3px;border-radius:2px;background:%(gold)s}
</style>
<div class=hd><div><h1>%(name)s</h1><div class=sub>%(dev)s%(district)s</div></div>
<div class=brand>%(najma)s<div>AZIMUTH<br><small>DigitAlchemy®</small><br><small>%(when)s</small></div></div></div>
%(body)s
%(foot)s
""" % {"name": E(name), "dev": E(dev + " · " if dev else ""), "district": E(G["district_name"]), "when": E(when),
       "body": (hero + '<div class=sec>%s</div><div class=cols>%s</div>' % (plate_block, head)) if rent
               else ('<div class=cols>%s</div><div class=sec>%s</div>' % (head, plate_block)),
       "foot": FOOT_RENT % {"asof": E(when)} if rent else FOOT_FULL % {"asof": E(asof or when)},
       "mark": mark(), "najma": najma_mark(), "ink": INK, "navy": NAVY, "gold": GOLD,
       "muted": MUTED, "rule": RULE}


FOOT_FULL = ('<div class=ft>Every figure above names the register it came from. The registers: the Dubai Land Department (units, sales,'
             ' rents through Ejari, projects, land), Dubai Municipality (the floor register, permits, Makani) and KHDA (schools).'
             ' Register data as at %(asof)s. Prepared for one named recipient; it is not a listing and not an offer.<br>'
             'contact@digitalabbot.io · +971 56 227 6093</div>')
# v273 - the tenant's version names the person to call. Kendall, 30 Sep 2026: "for the footer, all we're going to do is put
# curated by Najjuko ... a WhatsApp symbol ... +971 56 548 4397 ... Dubai Decoded" (confirmed by Kendall). Sources are credited
# where they are used, under each photo and table, not here.
WA_ICON = ('<svg viewBox="0 0 24 24" width="14" height="14" style="vertical-align:-2px;margin:0 5px 0 12px"><circle cx="12" cy="12" r="12" fill="#25D366"/>'
           '<path fill="#fff" d="M12 5.2a6.8 6.8 0 0 0-5.9 10.2L5.2 18.8l3.5-.9A6.8 6.8 0 1 0 12 5.2zm0 12.4a5.6 5.6 0 0 1-2.9-.8l-.2-.1-2.1.5.6-2-.1-.2'
           'a5.6 5.6 0 1 1 4.7 2.6zm3.1-4.2c-.2-.1-1-.5-1.2-.5-.2-.1-.3-.1-.4.1l-.5.7c-.1.1-.2.1-.4 0a4.6 4.6 0 0 1-2.3-2c-.2-.3.2-.3.5-1'
           '.1-.1 0-.3 0-.4l-.5-1.3c-.1-.3-.3-.3-.4-.3h-.4a.7.7 0 0 0-.5.3 2.2 2.2 0 0 0-.7 1.6 3.8 3.8 0 0 0 .8 2 8.7 8.7 0 0 0 3.3 2.9'
           'c1.2.5 1.7.6 2.3.5a2 2 0 0 0 1.3-.9 1.6 1.6 0 0 0 .1-.9c-.1-.1-.2-.1-.4-.2z"/></svg>')
FOOT_RENT = ('<div class=agent style="text-align:center">Curated by <b style="margin:0">Najjuko</b> · Dubai Decoded' + WA_ICON + '+971 56 548 4397</div>'
             '<!-- %(asof)s -->')


MANIFEST = os.path.join(ROOT, "data", "board", "dossier_manifest.json") if "ROOT" in dir() else None


def manifest_path():
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "board", "dossier_manifest.json")


def manifest():
    """What has been CONFIRMED STORED, keyed by KV slug. Written only after the worker accepts the push.

    Added 22 Sep 2026: the batch rebuilt every building from scratch on every run, so a district that died two-fifths
    through cost a full re-run, and 41 Dubai Marina dossiers were built twice for nothing. At 59-79 s per building that is
    the difference between a cheap sweep and three hours. It records a PUSH, never a build - a PDF on disk that never
    reached KV is exactly the silent-success failure that lost seven district uploads this morning.
    """
    p = manifest_path()
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:
        return {}


def source_stamp(district):
    """When the files this dossier is built FROM last changed.

    Added 22 Sep 2026. The manifest answers "did this reach KV"; a resume was asking it "is this current", and those are
    different questions wearing the same tick. stack_businessbay.json was regenerated at 10:01:39 with developer names
    added, halfway through a 164-building run - so the first 111 dossiers lack a developer line the rest carry, and every
    one of them is marked done. Without this stamp the only way to refresh them is --force over the whole district, which
    throws away the resume entirely. A cache that cannot express staleness is only half a cache.
    """
    out = {}
    for key, path in (("stack", os.path.join(BOARD, "stack_%s.json" % district)),
                      ("unitmix", os.path.join(BOARD, "unitmix_%s.json" % district))):
        try:
            out[key] = int(os.path.getmtime(path))
        except OSError:
            out[key] = None
    return out


def note_built(slug, pdf_path, pages, district=None):
    p = manifest_path()
    m = manifest()
    m[slug] = {"bytes": os.path.getsize(pdf_path), "pages": pages, "at": dt.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
               "src": source_stamp(district) if district else None}
    tmp = p + ".tmp"
    json.dump(m, open(tmp, "w", encoding="utf-8"), ensure_ascii=False)
    os.replace(tmp, p)


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
        note_built(slug, pdf_path, pages, G["d"])
        return True
    except Exception as e:
        print("  push failed: %s" % str(e)[:160])
        return False


def one(district, bid, do_push, beds=None, floor=None, audience=None, budget=None):
    G = gather(district, bid)
    if not G:
        print("%s/%s: not in both registers" % (district, bid))
        return False
    G["beds"], G["floor"], G["audience"], G["budget"] = beds, floor, audience, budget
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
    ap.add_argument("--all", action="store_true", help="every building in the district that meets both registers")
    ap.add_argument("--push", action="store_true")
    ap.add_argument("--force", action="store_true", help="rebuild even if the manifest says it is already stored")
    ap.add_argument("--beds", choices=["studio", "1", "2", "3", "4"], help="the request: show only this bedroom class's types")
    ap.add_argument("--floor", help="draw this level's floor plate as well (only when a floor was asked for)")
    ap.add_argument("--audience", choices=["rent"], help="rent: the tenant's version - plain words, no buyer or investor sections")
    ap.add_argument("--budget", type=int, help="the client's budget (AED a year for rent) - adds what it gets them here")
    a = ap.parse_args()
    if a.top or a.all:
        stack = rd("stack_%s.json" % a.district) or {}
        rows = sorted((stack.get("buildings_by_id") or {}).items(), key=lambda kv: -len(kv[1].get("floors") or []))
        ids = rows if a.all else rows[:a.top]
        # One building must never take the district down. 22 Sep 2026: a headless-Chrome PDF render timed out after 180 s
        # on dubaimarina_449 - the machine was busy with a CityEngine export - and the exception ended the run at 41 of 190
        # with no summary and no list of what was missing. A batch that dies silently two-fifths through is worse than a
        # slow one, because the gap looks like a district that was never started.
        n = 0; bad = []; skipped = 0
        have = manifest() if (a.push and not a.force) else {}
        now_src = source_stamp(a.district)
        stale = 0
        for i, _ in ids:
            rec = have.get("b_%s_%s" % (a.district, i))
            if rec is not None:
                # only skip when the dossier was built from the files as they stand NOW. An entry with no stamp predates
                # this check and is treated as stale rather than current, which is the safe direction.
                if rec.get("src") == now_src:
                    skipped += 1
                    continue
                stale += 1
            try:
                n += 1 if one(a.district, i, a.push, a.beds, a.floor, a.audience, a.budget) else 0
            except Exception as e:
                bad.append(i)
                print("  %s_%s FAILED: %s" % (a.district, i, str(e).splitlines()[0][:90]))
        print("%d of %d buildings in %s%s%s" % (n, len(ids), a.district,
              (", %d already current and skipped" % skipped) if skipped else "",
              (", %d rebuilt because their source data moved" % stale) if stale else ""))
        if bad:
            print("  %d failed, retry with: python scripts/build_building_dossier.py --district %s --push --id %s"
                  % (len(bad), a.district, (" --id ").join(bad[:8]) + (" ..." if len(bad) > 8 else "")))
        return 0
    if not a.id:
        ap.error("--id or --top")
    return 0 if one(a.district, a.id, a.push, a.beds, a.floor, a.audience, a.budget) else 1


if __name__ == "__main__":
    sys.exit(main())
