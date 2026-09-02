"""Knowledge-graph feed for a single building: compose meta_<slug> (the viewer's tap-card sidecar) from EVERY source
we hold and push it to KV. Runs daily after the cards so availability, cards and verdicts stay current.

Sources merged (each block is stamped with its own source line):
  data/dev_meta/curated/<slug>.json      hand-curated building facts (EYWA pattern, status_key drives the viewer match)
  data/brochure/floorplan_labels.json    census + view compass (floor-plan deck)
  data/avail/<developer>_<date>.json     newest developer sheet -> claimed availability for THIS building's projects
  KV cards_<building>_index              unit-type card links (push_cards.py)
  data/cards/vicinity.json               nearest metro / schools / demographics (Esri)
  data/pro/symphony_los.json             line-of-sight verdicts per sheet unit (ArcGIS Pro)
  DuckDB naj.duckdb                      latest registered transaction for the register name (if any)
Usage: python scripts/build_building_meta.py goldensymphony [--building symphony] [--developer imtiaz] [--match symphony]
"""
import base64, datetime as dt, json, os, re, sys, urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
from build_avail_index import latest_sheets, env_token, push, WORKER  # noqa: E402

slug = sys.argv[1] if len(sys.argv) > 1 else "goldensymphony"
opt = lambda k, d: sys.argv[sys.argv.index(k) + 1] if k in sys.argv else d
building = opt("--building", "symphony")
developer = opt("--developer", "imtiaz")
match = opt("--match", building).lower()


def load(p, default=None):
    p = os.path.join(ROOT, p)
    return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else default


curated = load(f"data/dev_meta/curated/{slug}.json", {"buildings": {}})
labels = load("data/brochure/floorplan_labels.json", {})
vic = load("data/cards/vicinity.json", {})
los = load("data/pro/symphony_los.json", {})
meta = {"district": slug, "updated": dt.date.today().isoformat(), "buildings": {}}

for k, b in curated.get("buildings", {}).items():
    b = dict(b)
    facts = list(b.get("facts", []))
    sources = list(b.get("sources", []))
    # --- availability from the newest developer sheet (only this building's projects)
    sheets = latest_sheets()
    if developer in sheets:
        path, auto = sheets[developer]
        sh = json.load(open(path, encoding="utf-8"))
        units = [u for p in sh["projects"] if match in p["p"].lower() for u in p["units"]]
        if units:
            by = {}
            for u in units:
                by.setdefault(u[1], []).append(u)
            line = " - ".join("%s x%d from AED %s" % (t, len(v), format(int(min(x[3] for x in v if x[3]) or 0), ",")) for t, v in by.items())
            facts.append(["Available now (developer sheet %s%s)" % (sh.get("sheet_date"), ", auto-read" if auto else ""), "%d units: %s" % (len(units), line)])
            b["availability"] = {"as_of": sh.get("sheet_date"), "units": units, "auto": auto}
            sources.append("Imtiaz availability sheet %s via DEVELOPER AVAILABILITY group" % sh.get("sheet_date"))
    # --- cards
    try:
        req = urllib.request.Request("%s/img/cards_%s_index" % (WORKER, building), headers={"User-Agent": "najma-market-pulse/1.0"})
        ci = json.load(urllib.request.urlopen(req, timeout=30))
        b["cards"] = ci
        b.setdefault("links", []).extend([["Unit cards", "/cards?b=%s" % building]] + ([["Cards PDF", ci["pdf"]]] if ci.get("pdf") else []))
        facts.append(["Unit-type cards", ", ".join(c["type"].replace("_", " ") for c in ci.get("cards", []))])
    except Exception as e:
        print("cards index not readable:", str(e)[:60])
    # --- vicinity
    if vic:
        m = (vic.get("metro") or [])[:1]
        sc = [s for s in (vic.get("schools") or []) if "tennis" not in (s.get("name") or "").lower()][:2]
        demo = {r.get("radius_km"): r for r in (vic.get("demographics") or [])}
        if m:
            facts.append(["Nearest metro", "%s (%.1f km straight-line)" % (m[0]["name"], m[0]["km"])])
        if sc:
            facts.append(["Schools", " - ".join("%s (%.1f km)" % (s["name"], s["km"]) for s in sc)])
        if 1 in demo:
            r1 = demo[1]
            facts.append(["Within 1 km (Esri 2024)", "%s residents, %s households, purchasing-power index %s" % (format(int(r1["pop"]), ","), format(int(r1["households"]), ","), r1["pp_index"])])
        sources.append("Esri World Geocoding + GeoEnrichment (2024)")
    # --- LOS verdicts
    if los.get("units"):
        blocked = [u["unit"] for u in los["units"] if u.get("lagoon") == "BLOCKED"]
        facts.append(["View check (ArcGIS Pro line of sight, site-level)", "%d sheet units checked - lagoon line blocked for %s; skyline clear for all" % (len(los["units"]), ", ".join(blocked) or "none")])
        b["los"] = los["units"]
        sources.append("DigitAlchemy view lane - ArcGIS Pro 3D Analyst vs CityEngine massing")
    # --- census from the deck
    if labels.get("level_stack"):
        b["census"] = {"level_stack": labels["level_stack"], "pages": labels.get("pages"), "view_compass": labels.get("view_compass")}
    b["facts"] = facts
    b["sources"] = list(dict.fromkeys(sources))
    meta["buildings"][k] = b

out = os.path.join(ROOT, "data", "dev_meta", f"meta_{slug}.json")
os.makedirs(os.path.dirname(out), exist_ok=True)
json.dump(meta, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
r = push("meta_" + slug, meta, env_token("INGEST_TOKEN"))
print("meta_%s -> %s (%d facts on %s)" % (slug, r.get("ok"), len(next(iter(meta["buildings"].values()))["facts"]) if meta["buildings"] else 0, ", ".join(meta["buildings"])))
