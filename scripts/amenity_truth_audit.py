"""Amenity truth audit - every place, every layer, judged the way a local would (Kendall, 8 Sep 2026, after Naj: "Chelsea by
Damac is literally on the coast so it's weird that it says there is not beach").

For each of the ~1,800 sub-communities (data/board/subs.json) this measures, against the LIVE amenity layer (data/board/amenities.json,
the same items the map serves): the nearest school / hospital / clinic / metro / mall / park / beach and the counts within 3 km,
plus the distance to the sea when a coastline is on disk (data/board/coast.json, built by scripts/coastline.py). It then flags what
a resident would call wrong, and checks the mall and beach layers against a short list of places every Dubai broker knows.

Flags (per place):
  COAST_NO_BEACH      sea within 400 m, nearest public beach more than 3 km       -> the Chelsea case: waterfront is not "no beach"
  NO_SCHOOL_5KM       >= 200 units and no school within 5 km                       -> KHDA/ESE gap or a genuinely remote place
  NO_CLINIC_3KM       >= 500 units and no clinic within 3 km                       -> DHA gap
  NO_MALL_5KM         >= 500 units and no DM-register mall within 5 km             -> DM mall layer thin (36 malls)
  NO_PARK_2KM         >= 500 units and no named park within 2 km                   -> OSM park gap
Layer checks:
  known malls / beaches missing from the layer (name match on distinctive words)
  contact-field quirks per source: digits-only address, operator name as address, missing rating

Output: data/board/amenity_truth_audit.json and a Markdown report path given with --md (default Operations/Quality_Audits/...).
Usage: python scripts/amenity_truth_audit.py [--md PATH]
"""
import json, math, os, re, sys, time
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, "..")); BOARD = os.path.join(ROOT, "data", "board")
KINDS = ["school", "hospital", "clinic", "metro", "mall", "park", "beach"]
KNOWN_MALLS = ["Dubai Mall", "Mall of the Emirates", "Ibn Battuta", "Mirdif City Centre", "Deira City Centre", "Festival City", "Dubai Hills Mall",
               "Dubai Marina Mall", "Nakheel Mall", "City Walk", "BurJuman", "Wafi", "Mercato", "Dubai Outlet Mall", "Circle Mall", "Al Ghurair",
               "Dragon Mart", "Bluewaters", "The Pointe", "Times Square", "Oasis Mall", "Souk Al Bahar", "Me'aisem City Centre", "Al Barsha Mall",
               "Arabian Center", "Dubai Creek Harbour", "Silicon Central", "Town Square", "Cityland Mall", "Golden Mile Galleria", "Dubai Festival Plaza"]
KNOWN_BEACHES = ["Kite Beach", "Jumeirah Beach", "Marina Beach Dubai", "La Mer", "Al Mamzar", "Sufouh", "Palm Jumeirah Beach", "Jebel Ali Open", "Mercato", "Pearl Jumeirah", "Deira Islands", "Jumeirah Public Beach", "Beyond the Beach"]
# JBR = Marina Beach Dubai / Beyond the Beach; Umm Suqeim and Sunset are the southern end of the Kite Beach polygon; Black Palace closed 2025; Nessnass / Al Jaddaf / Creek Harbour have no OSM polygon yet


def arg(flag, default):
    return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv else default


def m(a, b):
    R = 6371000.0; p = math.pi / 180; x = (b[1] - a[1]) * p; y = (b[0] - a[0]) * p * math.cos((a[1] + b[1]) / 2 * p)
    return R * math.sqrt(x * x + y * y)


def seg_dist(pt, a, b):
    """metres from pt to segment a-b, all lon/lat, equirectangular (fine at 25 N over a few km)."""
    k = math.cos(pt[1] * math.pi / 180)
    px, py = pt[0] * k, pt[1]; ax, ay = a[0] * k, a[1]; bx, by = b[0] * k, b[1]
    dx, dy = bx - ax, by - ay; L2 = dx * dx + dy * dy
    t = 0 if L2 == 0 else max(0, min(1, ((px - ax) * dx + (py - ay) * dy) / L2))
    cx, cy = ax + t * dx, ay + t * dy
    return math.hypot(px - cx, py - cy) * 111320.0


def tok(s):
    ws = [w for w in re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).split() if len(w) > 2 and w != "the" and w != "and"]
    core = {w for w in ws if w not in {"beach", "mall", "centre", "center", "public", "dubai", "park", "shopping"}}
    return core or set(ws)


def main():
    md = arg("--md", os.path.join(os.path.expanduser("~"), "OneDrive", "Desktop", "DigitAlchemy_31MAY2026", "Operations", "Quality_Audits", f"DA-AUD-004_Najma_Amenity_Truth_{time.strftime('%d%b%Y').upper()}.md"))
    subs = json.load(open(os.path.join(BOARD, "subs.json"), encoding="utf-8")); subs = subs.get("features", subs)
    D = {d["slug"]: d for d in json.load(open(os.path.join(BOARD, "districts_geo.json"), encoding="utf-8"))["districts"]}
    A = json.load(open(os.path.join(BOARD, "amenities.json"), encoding="utf-8")); items = A.get("items", A)
    by = {k: [i for i in items if i.get("k") == k] for k in KINDS}
    # access-aware layers (8 Sep): the beach and park counts a buyer can use are the PUBLIC ones; private ones are reported beside them
    by["beach_all"] = by["beach"]; by["beach"] = [i for i in by["beach_all"] if (i.get("acc") or "public") == "public"]
    by["park_all"] = by["park"]; by["park"] = [i for i in by["park_all"] if (i.get("acc") or "public") in ("public", "community")]
    coast = None; cp = os.path.join(BOARD, "coast.json")
    if os.path.exists(cp):
        cj = json.load(open(cp, encoding="utf-8")); coast = cj.get("segments") or []
    print(f"places {len(subs):,} · layer {A.get('generated')} · " + " · ".join(f"{k} {len(by[k])}" for k in KINDS) + f" · coast {'yes (' + str(len(coast)) + ' segments)' if coast else 'NO - run scripts/coastline.py'}")
    rows = []; flags = {"COAST_NO_BEACH": [], "NO_SCHOOL_5KM": [], "NO_CLINIC_3KM": [], "NO_MALL_5KM": [], "NO_PARK_2KM": []}
    for f in subs:
        p = f["properties"]; g = f["geometry"]["coordinates"]; c = g if isinstance(g[0], (int, float)) else g[0][0]
        units = p.get("units") or 0; r = {"name": p.get("name"), "district": p.get("district"), "units": units, "lon": c[0], "lat": c[1]}
        for k in KINDS:
            best = None; n3 = 0
            for i in by[k]:
                d = m(c, (i["lon"], i["lat"]))
                if d <= 3000: n3 += 1
                if best is None or d < best[0]: best = (d, i["n"])
            r[k] = {"nearest_m": round(best[0]) if best else None, "nearest": best[1] if best else None, "within_3km": n3}
        if coast:
            wmin = {}
            for sg in coast:
                d = seg_dist(c, (sg[0], sg[1]), (sg[2], sg[3]))
                if wmin.get(sg[4]) is None or d < wmin[sg[4]]: wmin[sg[4]] = d
            sea = wmin.get("sea", 1e9); r["sea_m"] = round(sea); r["water"] = {k: round(v) for k, v in wmin.items() if v < 2000}
            priv = sorted((m(c, (i["lon"], i["lat"])), i["n"], i.get("acc")) for i in by["beach_all"] if (i.get("acc") or "public") != "public")
            r["private_beach"] = {"nearest_m": round(priv[0][0]), "nearest": priv[0][1], "acc": priv[0][2]} if priv else None
            if sea <= 400 and (r["beach"]["nearest_m"] or 1e9) > 3000: flags["COAST_NO_BEACH"].append(r)
        if units >= 200 and (r["school"]["nearest_m"] or 1e9) > 5000: flags["NO_SCHOOL_5KM"].append(r)
        if units >= 500 and r["clinic"]["within_3km"] == 0: flags["NO_CLINIC_3KM"].append(r)
        if units >= 500 and (r["mall"]["nearest_m"] or 1e9) > 5000: flags["NO_MALL_5KM"].append(r)
        if units >= 500 and (r["park"]["nearest_m"] or 1e9) > 2000: flags["NO_PARK_2KM"].append(r)
        rows.append(r)
    # layer completeness against what every broker knows
    def missing(known, layer):
        names = [i["n"] for i in layer]; out = []
        for k in known:
            kt = tok(k)
            if not any(kt and kt <= tok(n) or (kt and len(kt & tok(n)) >= max(1, len(kt) - 1) and len(kt) > 1) for n in names): out.append(k)
        return out
    miss_m = missing(KNOWN_MALLS, by["mall"]); miss_b = missing(KNOWN_BEACHES, by["beach"])
    # contact-field quirks
    quirk = {}
    for i in items:
        src = i.get("src") or "?"; q = quirk.setdefault(src, {"n": 0, "addr_digits": 0, "addr_short": 0, "no_rating": 0, "no_tel": 0})
        q["n"] += 1; ad = str(i.get("addr") or i.get("address") or "").strip()
        if ad and re.fullmatch(r"[\d\s\-+]+", ad): q["addr_digits"] += 1
        if ad and len(ad.split()) == 1 and not ad.isdigit(): q["addr_short"] += 1
        if i.get("k") == "school" and not (i.get("x") or "").strip(): q["no_rating"] += 1
        if i.get("k") in ("school", "hospital", "clinic") and not (i.get("tel") or i.get("phone")): q["no_tel"] += 1
    out = {"generated": time.strftime("%Y-%m-%d %H:%M"), "layer_generated": A.get("generated"), "places": len(rows), "coast": bool(coast),
           "flag_counts": {k: len(v) for k, v in flags.items()}, "flags": {k: v[:400] for k, v in flags.items()}, "missing_malls": miss_m, "missing_beaches": miss_b, "quirks": quirk}
    json.dump(out, open(os.path.join(BOARD, "amenity_truth_audit.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    # the report
    L = [f"# DA-AUD-004 — Najma · do the amenity layers tell the truth? ({time.strftime('%d %b %Y')})", "",
         f"**Trigger:** Najjuko, 11:40 GST: *\"Chelsea by Damac is literally on the coast so it's weird that it says there is not beach.\"* Kendall: full audit, deep dive.",
         f"**Method:** every one of the {len(rows):,} sub-communities measured against the live amenity layer (generated {A.get('generated')}) — nearest of each kind, counts within 3 km" + (", distance to the sea from the Overture coastline" if coast else " (coastline not yet on disk — sea-front check pending)") + ". Thresholds are what a resident would call wrong, not statistics.", "",
         "## 1 · Flags", "", "| Flag | Meaning | Places |", "|---|---|---:|"]
    meaning = {"COAST_NO_BEACH": "open sea (not creek/canal/marina) within 400 m, no public beach within 3 km — waterfront reads as 'no beach'", "NO_SCHOOL_5KM": "200+ units, no school within 5 km",
               "NO_CLINIC_3KM": "500+ units, no clinic within 3 km", "NO_MALL_5KM": "500+ units, no DM-register mall within 5 km", "NO_PARK_2KM": "500+ units, no named park within 2 km"}
    for k, v in flags.items(): L.append(f"| {k} | {meaning[k]} | {len(v)} |")
    for k, v in flags.items():
        if not v: continue
        L += ["", f"### {k} — worst first", "", "| Place | District | Units | Nearest | " + ("Sea | " if coast else "") + "|", "|---|---|---:|---|" + ("---:|" if coast else "")]
        key = {"COAST_NO_BEACH": "beach", "NO_SCHOOL_5KM": "school", "NO_CLINIC_3KM": "clinic", "NO_MALL_5KM": "mall", "NO_PARK_2KM": "park"}[k]
        for r in sorted(v, key=lambda r: -(r["units"] or 0))[:25]:
            nm = r[key]["nearest_m"]; L.append(f"| {r['name']} | {D.get(r['district'], {}).get('name', r['district'])} | {r['units']:,} | {r[key]['nearest'] or '—'} {('· ' + (str(round(nm / 1000, 1)) + ' km') if nm else '')} | " + (f"{r.get('sea_m', '—')} m | " if coast else ""))
    L += ["", "## 2 · Layer completeness against what every broker knows", "",
          f"**Malls (DM register, {len(by['mall'])} in the layer)** — known malls with no match: " + (", ".join(miss_m) if miss_m else "none") + ".",
          f"**Beaches ({len(by['beach'])} public + {len(by['beach_all']) - len(by['beach'])} hotel/residents in the layer, Overture land = OpenStreetMap, access classified)** — known public beaches with no match: " + (", ".join(miss_b) if miss_b else "none") + ".", "",
          "## 3 · Contact-field quirks by source", "", "| Source | Items | Address is only digits | One-word address | School with no rating | Health/school with no phone |", "|---|---:|---:|---:|---:|---:|"]
    for s, q in sorted(quirk.items(), key=lambda x: -x[1]["n"]): L.append(f"| {s} | {q['n']} | {q['addr_digits']} | {q['addr_short']} | {q['no_rating']} | {q['no_tel']} |")
    L += ["", "## 4 · What to change", "",
          "1. **Waterfront is a fact of its own.** Add `sea · N m` to every place panel and to the beach card's second line (`0 beaches within 3 km · sea 40 m`), from the Overture coastline (`coast` KV). A resident's 'on the coast' and the register's 'public beach' are different things and the app must say both.",
          "2. **Beach layer:** add the missing public beaches by name from the Dubai Municipality beach list and OSM (`natural=beach` + `leisure=beach_resort` with public access), and mark private/hotel beaches as such rather than dropping them.",
          "3. **Mall layer:** the DM register's 36 is right by its definition (completed shopping centres ≥ 50k m²) but a broker's mental list includes community malls; add a `community mall` tier from the DM register below 50k m² and label it.",
          "4. **Schools/clinics gaps:** every NO_SCHOOL_5KM / NO_CLINIC_3KM place is either a new district (register lag) or a real gap — say which on the card (`none licensed yet within 5 km`).",
          "5. **Contact fields:** validate on build (digits-only address → phone; operator name → operator line; rating from the KHDA inspection table).", "",
          f"*Data: `data/board/amenity_truth_audit.json` · script `scripts/amenity_truth_audit.py` · run {time.strftime('%Y-%m-%d %H:%M')} GST*"]
    os.makedirs(os.path.dirname(md), exist_ok=True); open(md, "w", encoding="utf-8").write("\n".join(L))
    print("flags:", out["flag_counts"]); print("missing malls:", miss_m); print("missing beaches:", miss_b); print("report:", md)


if __name__ == "__main__":
    main()
