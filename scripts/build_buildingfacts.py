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


def run(slug):
    rep = os.path.join(ROOT, "data", "ce", slug, "report_v3.csv")
    anc = os.path.join(ROOT, "data", "names", f"anchors_{slug}.json")
    if not os.path.exists(anc): return None
    derived = not os.path.exists(rep)
    A = json.load(open(anc, encoding="utf-8"))
    by_i = {a["i"]: a for a in A["anchors"]}
    out, tot_env, tot_units, tot_reg, n_flag = {}, 0.0, 0, 0, 0
    for r in (_rows_from_geojson(slug) if derived else csv.DictReader(open(rep, encoding="utf-8"))):
        sh = r.get("shape") or ""
        if not sh.startswith("b"): continue
        try: i = int(sh[1:].split("_")[0])
        except Exception: continue
        env = float(r.get("gfa_m2") or 0); st = int(float(r.get("storeys") or 0)); fp = float(r.get("footprint_m2") or 0)
        h = float(r.get("height_m") or 0)
        if env <= 0: continue
        flag = any(h > gh and fp > gf for gh, gf in PLATE_GATES)
        rec = {"i": i, "footprint_m2": round(fp), "height_m": round(h, 1), "storeys": st,
               "envelope_m2": round(env), "envelope_sqft": round(env * 10.7639), "class": r.get("class"),
               "facts_source": "footprints" if derived else "ce_v3", "plate_suspect": flag,
               "units_indicative": (None if flag or st <= 1 else max(1, round(env * EFF / UNIT_M2))),
               "basis": "envelope = footprint x storeys from our own massing, an upper bound on floor area"
                        + (" - this footprint is a podium or plot outline, so the envelope is a ceiling only" if flag else "")}
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
        tot_env += env; tot_units += rec["units_indicative"] or 0
        tot_reg += rec.get("units_registered") or 0; n_flag += 1 if flag else 0
        out[str(i)] = rec
    doc = {"district": slug, "buildings": len(out), "envelope_m2_total": round(tot_env),
           "envelope_sqft_total": round(tot_env * 10.7639), "plate_suspect": n_flag,
           "units_indicative_total": tot_units, "units_registered_total": tot_reg,
           "efficiency": EFF, "unit_m2": UNIT_M2, "plate_gates": PLATE_GATES,
           "note": "Envelope is footprint x storeys from our own massing: an upper bound on floor area, not a measured one, "
                   "and a ceiling only on the buildings flagged plate_suspect (a tall building on a footprint wide enough to be "
                   "a podium or a plot outline). Home counts are indicative unless marked registered, and are withheld on flagged buildings.",
           "buildings_by_id": out}
    f = os.path.join(ROOT, "data", "board", f"bldgfacts_{slug}.json")
    json.dump(doc, open(f, "w", encoding="utf-8"), ensure_ascii=False)
    named = sum(1 for v in out.values() if v.get("name")); reg = sum(1 for v in out.values() if v.get("units_registered"))
    print(f"{slug:<26} buildings {len(out):>5}  named {named:>4}  envelope {round(tot_env/1e6,2):>6} M m2  "
          f"podium-flagged {n_flag:>4}  indicative homes {tot_units:>6}  registered {tot_reg:>6} in {reg} buildings")
    return doc


if __name__ == "__main__":
    slugs = sys.argv[1:] or sorted({os.path.basename(os.path.dirname(p)) for p in
                                    glob.glob(os.path.join(ROOT, "data", "ce", "*", "report_v3.csv")) + glob.glob(os.path.join(ROOT, "data", "ce", "*", "buildings.geojson"))})
    tok = env_token("INGEST_TOKEN")
    for s in slugs:
        d = run(s)
        if d: print("   ", "bldgfacts_" + s, "->", push("bldgfacts_" + s, d, tok).get("ok"))
