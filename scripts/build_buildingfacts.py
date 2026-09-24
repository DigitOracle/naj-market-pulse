"""Per-building facts for the twin's panel and the district stock report, from the reports the massing itself writes.

For each district: read data/ce/<slug>/report_v3.csv (one row per building: footprint, height, storeys, envelope area, class),
join it to the anchors (name, developer, project) and, where the project is one of the eleven developers' registered schemes,
to the register facts (projfacts) so a broker can read the bulk of a building beside its price.

HONESTY GATE - read this before quoting any number off this file.
The massing extrudes each footprint straight up to the building's height. That makes the area it reports an ENVELOPE:
footprint x storeys, an upper bound on floor area, not a measured floor area. It is close for a slab or a plain tower whose
footprint is the tower itself. It is far too large wherever the footprint we hold is the podium or the plot outline rather
than the tower plate - a tall building on a wide footprint is flagged `plate_suspect` and its envelope must be read as a
ceiling only. Anything published from this file says "envelope", never "floor area", and never carries a developer's name
as though the developer stated it.

Indicative homes are envelope x efficiency 0.78 / a typical 105 m2 apartment - a planning figure for scale only, withheld
entirely on a flagged building. Where the register or the developer's own site gives a real unit count, that wins outright
and is labelled registered.

WHICH HEIGHT THIS PUBLISHES, because a building's height lives in four places and they do not agree.

    data/ce/<slug>/buildings.geojson    bHeight, the massing INPUT
    data/ce/<slug>/report_v4.csv        what the LOD 3 massing BUILT      <- read first
    data/ce/<slug>/report_v3.csv        the older massing                 <- fallback only
    data/names/anchors_<slug>.json      what height_check reads (not this file)

This read report_v3 until 24 Sep 2026, a whole massing version behind. Measured across the 15 districts holding both:
713 buildings differ by more than 2 m and **v4 is higher in every single one, never lower** - each is a building v3 had
at the 12 m placeholder and v4 has at a real height, matching the geojson exactly wherever that carries one.
althanyahfifth alone gains 510 real heights.

**BUT V4 IS AUTHORITATIVE FOR HEIGHT AND NOT FOR STOREYS**, and taking it wholesale is a trap I walked into before
measuring. On the 65,073 buildings where both reports give the SAME height, v3's storeys are exactly twice v4's on
47,846 of them: the implied floor-to-floor is 3.00 m in v3 and 6.00 m in v4. Three metres is a Dubai floor. Six is a
banding artefact of the LOD 3 rule or a mezzanine convention, but it is not a floor count. Publishing it halved every
floor count in the estate - jltnorth's envelope fell 22% and 15,000 indicative homes disappeared - which would have
read as a correction and was a unit error.

So: height from v4, storeys from v3 where it described the same building at the same height, and otherwise derived
from the height at 3.0 m. Envelope is recomputed here rather than read, because each report's gfa_m2 is footprint x
ITS OWN storeys and mixing the two would carry v4's floor count in through the back door.

THE CANDIDATE RULE, for buildings raised in the geojson since the district was last massed. A height raised this
morning reaches neither report until a re-mass, so Horizon Tower stood at 147 m in the model and 9.4 m with 3 storeys
on the card. Where the report is still at the placeholder and the geojson holds a real height, the geojson height is
published - but STOREYS, ENVELOPE AND HOME COUNT ARE WITHHELD, not derived from it.

That restraint is the whole point. Envelope is footprint x storeys and indicative homes are envelope x 0.78 / 105, so
deriving storeys from a height would multiply a tower's published home count fifteenfold on the strength of one number
the massing has not yet agreed with. A wrong storey count is worse than none, and an invented home count is worse
still. The record says `awaiting_remass` and carries the height alone until the massing catches up.

Output: data/board/bldgfacts_<slug>.json -> KV `bldgfacts_<slug>` (served at /img/bldgfacts_<slug>).
Usage: python scripts/build_buildingfacts.py [slug ...]
"""
import csv, glob, json, os, sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
from build_avail_index import env_token, push  # noqa: E402
from build_developer_dna import norm_name  # noqa: E402

EFF, UNIT_M2 = 0.78, 105.0        # net-to-gross and a typical Dubai apartment, both stated on the card
# A tower standing on a wide footprint is standing on a podium or a plot outline, not on a tower plate: past these gates the
# envelope is a ceiling, not an estimate, and we publish no home count for it at all. Two gates, because the plate a tower can
# plausibly carry falls as it rises - a 400 m residential tower is not sitting on 3,500 m2 of floor, whatever the outline says.
PLATE_GATES = [(100.0, 2500.0), (60.0, 4000.0)]   # (height above which, footprint above which) the outline stops being the building
PF = os.path.join(ROOT, "data", "board", "projfacts.json")
PROJ = json.load(open(PF, encoding="utf-8"))["projects"] if os.path.exists(PF) else {}


def _levels(v):
    """Storeys above ground. '12' -> 12 · 'G+5' -> 6 · '2B+G+12' -> 13 (basements excluded) · 'G+M+8' -> 10 · 'G' -> 1."""
    import re
    t = str(v or "").strip().upper()
    if not t: return 0
    try: return int(float(t))
    except Exception: pass
    n = 0
    for tok in re.split(r"[+/,]", t):
        tok = tok.strip()
        if not tok: continue
        m = re.match(r"^(\d*)\s*([A-Z]*)$", tok)
        if not m: continue
        num, kind = m.group(1), m.group(2)
        c = int(num) if num else 1
        if kind.startswith("B"): continue                  # basements sit below ground
        n += c
    return n


def _rows_from_geojson(slug):
    """No v3 massing report for this district: derive footprint / height / storeys from the footprints we already hold, so the
    register facts still reach a card. Same envelope definition (footprint x storeys), same honesty gate, flagged as derived."""
    import math
    gj = os.path.join(ROOT, "data", "ce", slug, "buildings.geojson")
    if not os.path.exists(gj): return []
    try:
        import pyproj
        to_utm = pyproj.Transformer.from_crs("EPSG:4326", "EPSG:32640", always_xy=True).transform
    except Exception:
        return []
    out = []
    for i, f in enumerate(json.load(open(gj, encoding="utf-8"))["features"]):
        g = f.get("geometry") or {}; pr = f.get("properties") or {}
        rings = [g["coordinates"][0]] if g.get("type") == "Polygon" else ([pg[0] for pg in g.get("coordinates", [])] if g.get("type") == "MultiPolygon" else [])
        if not rings: continue
        ring = max(rings, key=len)
        pts = [to_utm(x, y) for x, y in ring]
        a = abs(sum(pts[j][0] * pts[(j + 1) % len(pts)][1] - pts[(j + 1) % len(pts)][0] * pts[j][1] for j in range(len(pts)))) / 2.0
        h = float(pr.get("bHeight") or 0)
        st = _levels(pr.get("levels")) or (int(h / 3.2) if h >= 3.2 else 0)
        if a <= 0 or st <= 0: continue
        out.append({"shape": f"b{i}", "footprint_m2": a, "height_m": h, "storeys": st, "gfa_m2": a * st, "class": pr.get("status") or None})
    return out


M_PER_FLOOR = 3.0           # v3's implied floor-to-floor, median across 65,073 buildings - a Dubai floor
PLACEHOLDER_MAX = 12.7      # the massing default is 12.0, and rounds to 12.6 with a parapet
LIFT_MIN = 15.0             # below this a "lift" is noise, not a tower the massing missed


def geojson_heights(slug):
    """bHeight per footprint index, for the candidate rule. Input to the massing, not output of it."""
    p = os.path.join(ROOT, "data", "ce", slug, "buildings.geojson")
    if not os.path.exists(p):
        return {}
    try:
        feats = json.load(open(p, encoding="utf-8"))["features"]
    except Exception:
        return {}
    out = {}
    for i, f in enumerate(feats):
        h = (f.get("properties") or {}).get("bHeight")
        try:
            out[i] = float(h)
        except Exception:
            pass
    return out


def run(slug):
    # v4 is the LOD 3 massing and is higher than v3 in all 713 measured disagreements, never lower. v3 is a fallback
    # for districts that have not been re-massed, not an equal alternative.
    rep4 = os.path.join(ROOT, "data", "ce", slug, "report_v4.csv")
    rep3 = os.path.join(ROOT, "data", "ce", slug, "report_v3.csv")
    rep = rep4 if os.path.exists(rep4) else rep3
    ver = "ce_v4" if rep is rep4 else "ce_v3"
    # v4 is authoritative for HEIGHT and not for STOREYS. Measured on the 65,073 buildings the two reports give the
    # same height: v3 storeys are exactly twice v4's on 47,846 of them, and the implied floor-to-floor is 3.00 m in v3
    # against 6.00 m in v4. Three metres is a Dubai floor; six is a mezzanine convention or a banding artefact of the
    # LOD 3 rule. Taking v4 wholesale halved every floor count - jltnorth's envelope fell 22% and 15,000 indicative
    # homes vanished - on the strength of a number that is not a floor count.
    V3ST = {}
    if rep is rep4 and os.path.exists(rep3):
        for r in csv.DictReader(open(rep3, encoding="utf-8")):
            sh = r.get("shape") or ""
            if not sh.startswith("b"):
                continue
            try:
                V3ST[int(sh[1:].split("_")[0])] = (float(r.get("height_m") or 0), int(float(r.get("storeys") or 0)))
            except Exception:
                pass
    anc = os.path.join(ROOT, "data", "names", f"anchors_{slug}.json")
    if not os.path.exists(anc): return None
    derived = not os.path.exists(rep)
    A = json.load(open(anc, encoding="utf-8"))
    by_i = {a["i"]: a for a in A["anchors"]}
    GH = geojson_heights(slug)
    out, tot_env, tot_units, tot_reg, n_flag = {}, 0.0, 0, 0, 0
    lifted, conflicts = [], []
    for r in (_rows_from_geojson(slug) if derived else csv.DictReader(open(rep, encoding="utf-8"))):
        sh = r.get("shape") or ""
        if not sh.startswith("b"): continue
        try: i = int(sh[1:].split("_")[0])
        except Exception: continue
        st = int(float(r.get("storeys") or 0)); fp = float(r.get("footprint_m2") or 0)
        h = float(r.get("height_m") or 0)
        # storeys from v3 where it described the SAME building at the same height; otherwise from the height itself at
        # the v3 convention. Never v4's own count, for the reason above.
        v3h, v3s = V3ST.get(i, (None, None))
        if v3s and v3h is not None and abs(v3h - h) <= 0.5:
            st = v3s
        elif V3ST or rep is rep4:
            st = max(1, int(round(h / M_PER_FLOOR)))
        env = fp * st                       # recomputed, because each report's gfa is footprint x ITS OWN storeys
        if env <= 0: continue
        # A height raised in the geojson since this district was massed reaches no report until a re-mass. Publish the
        # height; withhold everything derived from storeys, because envelope and homes would be a guess on a guess.
        ahead = False
        gh_i = GH.get(i)
        if gh_i and h <= PLACEHOLDER_MAX and gh_i >= LIFT_MIN and gh_i > h + 2:
            lifted.append((i, h, gh_i))
            h, ahead = gh_i, True
        elif gh_i and h > PLACEHOLDER_MAX and abs(gh_i - h) > 2 and gh_i > PLACEHOLDER_MAX:
            conflicts.append((i, h, gh_i))          # both real and disagreeing: recorded, never resolved here

        flag = any(h > gh and fp > gf for gh, gf in PLATE_GATES)
        rec = {"i": i, "footprint_m2": round(fp), "height_m": round(h, 1),
               "storeys": (None if ahead else st),
               "envelope_m2": (None if ahead else round(env)),
               "envelope_sqft": (None if ahead else round(env * 10.7639)), "class": r.get("class"),
               "facts_source": "footprints" if derived else ver, "plate_suspect": flag,
               "units_indicative": (None if (ahead or flag or st <= 1) else max(1, round(env * EFF / UNIT_M2))),
               "basis": ("height from the building register; the massing still has this footprint at its default, so "
                         "floor count, envelope and home count are withheld until it is rebuilt" if ahead else
                         "envelope = footprint x storeys from our own massing, an upper bound on floor area"
                         + (" - this footprint is a podium or plot outline, so the envelope is a ceiling only" if flag else ""))}
        if ahead:
            rec["awaiting_remass"] = True
        if a := by_i.get(i):
            rec["name"] = a.get("name"); rec["dev"] = a.get("dev"); rec["project"] = a.get("dev_project")
            # a real unit count always beats the indicative one
            if a.get("dev") and a.get("dev_project"):
                key = norm_name(a["dev_project"], [a["dev"]]).replace(" ", "")
                p = next((v for k, v in PROJ.items() if v.get("dev") == a["dev"]
                          and norm_name(v.get("name", ""), [a["dev"]]).replace(" ", "") == key), None)
                if p and p.get("units"):
                    try:
                        rec["units_registered"] = int(str(p["units"]).replace(",", "")); rec["units_source"] = "developer site / DLD register"
                    except Exception:
                        pass
        tot_env += 0 if ahead else env; tot_units += rec["units_indicative"] or 0
        tot_reg += rec.get("units_registered") or 0; n_flag += 1 if flag else 0
        out[str(i)] = rec
    doc = {"district": slug, "buildings": len(out), "envelope_m2_total": round(tot_env),
           "envelope_sqft_total": round(tot_env * 10.7639), "plate_suspect": n_flag,
           "units_indicative_total": tot_units, "units_registered_total": tot_reg,
           "efficiency": EFF, "unit_m2": UNIT_M2, "plate_gates": PLATE_GATES,
           "massing_report": ver if not derived else "footprints",
           "awaiting_remass": len(lifted),
           "height_conflicts": [{"i": i, "massed_m": round(a, 1), "register_m": round(b, 1)} for i, a, b in conflicts],
           "note": "Envelope is footprint x storeys from our own massing: an upper bound on floor area, not a measured one, "
                   "and a ceiling only on the buildings flagged plate_suspect (a tall building on a footprint wide enough to be "
                   "a podium or a plot outline). Home counts are indicative unless marked registered, and are withheld on flagged buildings. "
                   "Buildings marked awaiting_remass carry a register height the massing has not caught up with, and publish no "
                   "floor count, envelope or home count at all rather than derive one from it.",
           "buildings_by_id": out}
    f = os.path.join(ROOT, "data", "board", f"bldgfacts_{slug}.json")
    json.dump(doc, open(f, "w", encoding="utf-8"), ensure_ascii=False)
    named = sum(1 for v in out.values() if v.get("name")); reg = sum(1 for v in out.values() if v.get("units_registered"))
    print(f"{slug:<26} {ver if not derived else 'footprints':<11} buildings {len(out):>5}  named {named:>4}  "
          f"envelope {round(tot_env/1e6,2):>6} M m2  podium-flagged {n_flag:>4}  indicative homes {tot_units:>6}  "
          f"registered {tot_reg:>6} in {reg}  awaiting re-mass {len(lifted):>3}  height conflicts {len(conflicts):>3}")
    for i, a, b in lifted[:4]:
        nm = (by_i.get(i) or {}).get("name") or ""
        print(f"      lifted b{i} {a:.1f} -> {b:.1f} m  {nm[:34]}  (floors, envelope and homes withheld)")
    return doc


if __name__ == "__main__":
    # --dry builds the files without publishing. Push one district, assert it on the wire, then push the rest: on
    # 22 Sep a district went live stripped of its enrichment and nobody looked until afterwards.
    dry = "--dry" in sys.argv
    slugs = [a for a in sys.argv[1:] if not a.startswith("-")] or sorted(
        {os.path.basename(os.path.dirname(p)) for p in
         glob.glob(os.path.join(ROOT, "data", "ce", "*", "report_v4.csv"))
         + glob.glob(os.path.join(ROOT, "data", "ce", "*", "report_v3.csv"))
         + glob.glob(os.path.join(ROOT, "data", "ce", "*", "buildings.geojson"))})
    tok = None if dry else env_token("INGEST_TOKEN")
    for s in slugs:
        d = run(s)
        if d and not dry:
            print("   ", "bldgfacts_" + s, "->", push("bldgfacts_" + s, d, tok).get("ok"))
    if dry:
        print("\n--dry: files written to data/board/, nothing published.")
