"""What does the twin actually KNOW about each building? One honest report, per district and per source.

The twin holds a modelled block for every footprint in a district - that is geometry, not knowledge. This audit separates the two.
Every building is graded by the strongest evidence we hold about it, and each evidence layer is counted separately so nobody
mistakes "we drew it" for "we have data on it".

Layers (a building can carry several; the grade is the strongest):
  massing   our own model only - footprint, height, storeys, envelope. No name, no owner, no market data.
  survey    a name from the open survey record (OpenStreetMap, Overture, Wikidata) - we know WHAT it is, nothing more.
  register  bound to a developer's scheme, and the Dubai Land Department register carries settled sales for that scheme:
            volumes, median price, price per square metre, off-plan share. Public, settled, never asking prices.
  pipeline  the scheme appears in the MEED projects corpus: stage, contract value, last update. Programme intelligence,
            not sales - a building can be in MEED and have no register sales at all, and vice versa.
  live      a current availability sheet captured from the developer group: real units, real asking prices, dated.
            This is the only layer that says what is for sale TODAY, and the only one that arrives through the group.

Outputs: data/board/TWIN_AUDIT_<date>.md (the report) and data/board/twin_audit.json (the same numbers, machine-readable).
Usage: python scripts/twin_audit.py [--md-only]
"""
import collections, datetime as dt, glob, json, os, re, sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
from build_developer_dna import norm_name, same  # noqa: E402

DISTRICT_NAME = {"burjkhalifa": "Downtown Dubai", "palmdeira": "Dubai Islands", "jumeirahvillagecircle": "JVC",
                 "jumeirahvillagetriangle": "JVT", "althanyahfifth": "JLT / Al Thanyah Fifth", "samaaljadaf": "Al Jaddaf",
                 "sobhaheartland": "Sobha Hartland", "alwasl": "Al Wasl", "motorcity": "Motor City",
                 "businessbay": "Business Bay", "dubaimarina": "Dubai Marina", "palmjumeirah": "Palm Jumeirah"}
SURVEY = {"osm", "osm_en", "overture", "wikidata"}

SEG = json.load(open(os.path.join(ROOT, "data", "dev_meta", "developer_segments.json"), encoding="utf-8"))
DNA = json.load(open(os.path.join(ROOT, "data", "dev_meta", "developer_dna.json"), encoding="utf-8"))["developers"]
PROJ = json.load(open(os.path.join(ROOT, "data", "board", "projfacts.json"), encoding="utf-8"))["projects"]
BOARD = json.load(open(os.path.join(ROOT, "data", "board", "board_devs.json"), encoding="utf-8"))
KEY2NAME = {d["key"]: d["name"] for d in BOARD["developers"]}
NAME2KEY = {v: k for k, v in KEY2NAME.items()}

# --- what each developer's schemes carry, keyed by normalised project name
sheets, meed = {}, {}
for d in BOARD["developers"]:
    al = SEG["aliases"].get(d["name"], [d["name"].lower()])
    for p in d["properties"]:
        if p.get("sheet"):
            sheets[(d["key"], norm_name(p["name"], al))] = {"units": p["sheet"]["units"], "date": p["sheet"].get("sheet"),
                                                            "types": p["sheet"].get("types") or [], "card": p["name"],
                                                            "area": p.get("area"), "dev": d["key"]}
    m = (DNA.get(d["name"]) or {}).get("meed") or {}
    for a in m.get("active") or []:
        t = re.sub(r"\s*\(Plot No\.[^)]*\)", "", a.get("title") or "")
        t = t.split(":")[-1].strip() if ":" in t else t.split(" - ")[-1].strip()
        if t: meed[(d["key"], norm_name(t, al))] = {"stage": a.get("stage"), "usd_m": a.get("usd_m"), "title": a.get("title")}


def look(table, dev, project):
    if not (dev and project): return None
    al = SEG["aliases"].get(KEY2NAME.get(dev, ""), [dev])
    nn = norm_name(project, al)
    return next((v for (k, kn), v in table.items() if k == dev and same(kn, nn)), None)


def dld_for(dev, project):
    if not (dev and project): return None
    al = SEG["aliases"].get(KEY2NAME.get(dev, ""), [dev])
    nn = norm_name(project, al)
    p = next((v for v in PROJ.values() if v.get("dev") == dev and same(norm_name(v.get("name", ""), al), nn)), None)
    return (p or {}).get("dld")


def run():
    districts, all_rows = [], []
    for f in sorted(glob.glob(os.path.join(ROOT, "data", "board", "bldgfacts_*.json"))):
        slug = os.path.basename(f)[10:-5]
        BF = json.load(open(f, encoding="utf-8"))
        anc = os.path.join(ROOT, "data", "names", f"anchors_{slug}.json")
        A = {a["i"]: a for a in (json.load(open(anc, encoding="utf-8"))["anchors"] if os.path.exists(anc) else [])}
        rows = []
        for b in BF["buildings_by_id"].values():
            a = A.get(b["i"]) or {}
            dev, proj = a.get("dev"), a.get("dev_project")
            sh = look(sheets, dev, proj); md = look(meed, dev, proj); dl = dld_for(dev, proj)
            layers = ["massing"]
            if a.get("name") and a.get("source") in SURVEY: layers.append("survey")
            if a.get("name") and a.get("source") in ("dld", "register"): layers.append("register-named")
            if dl: layers.append("register")
            if md: layers.append("pipeline")
            if sh: layers.append("live")
            grade = "live" if sh else ("register" if dl else ("pipeline" if md else ("survey" if a.get("name") else "massing")))
            rows.append({"district": slug, "i": b["i"], "name": a.get("name"), "name_source": a.get("source"),
                         "height_m": b.get("height_m"), "storeys": b.get("storeys"), "dev": dev, "project": proj,
                         "dld_sales": (dl or {}).get("sales_2026"), "dld_median_aed": (dl or {}).get("median_aed"),
                         "meed_stage": (md or {}).get("stage"), "meed_usd_m": (md or {}).get("usd_m"),
                         "sheet_units": (sh or {}).get("units"), "sheet_date": (sh or {}).get("date"),
                         "layers": layers, "grade": grade})
        all_rows += rows
        g = collections.Counter(r["grade"] for r in rows)
        districts.append({"slug": slug, "name": DISTRICT_NAME.get(slug, slug), "buildings": len(rows),
                          "named": sum(1 for r in rows if r["name"]), "bound": sum(1 for r in rows if r["dev"]),
                          "grades": dict(g), "tallest": max((r["height_m"] or 0) for r in rows) if rows else 0})
    return districts, all_rows


def report(districts, rows):
    n = len(rows); date = dt.date.today().isoformat()
    g = collections.Counter(r["grade"] for r in rows)
    lay = collections.Counter(l for r in rows for l in r["layers"])
    devs = collections.Counter(r["dev"] for r in rows if r["dev"])
    srcs = collections.Counter(r["name_source"] for r in rows if r["name"])
    pct = lambda x: f"{100 * x / max(1, n):.1f}%"
    L = []
    L.append(f"# Digital twin — data audit\n")
    L.append(f"*{date} · {len(districts)} districts · {n:,} buildings modelled*\n")
    L.append("## The headline\n")
    L.append(f"| | Buildings | Share |\n|---|---:|---:|")
    L.append(f"| **Modelled in the twin** | {n:,} | 100% |")
    L.append(f"| Carrying a name | {sum(1 for r in rows if r['name']):,} | {pct(sum(1 for r in rows if r['name']))} |")
    L.append(f"| Bound to one of the eleven developers | {sum(1 for r in rows if r['dev']):,} | {pct(sum(1 for r in rows if r['dev']))} |")
    L.append(f"| **Carrying real data beyond geometry** | {n - g['massing']:,} | {pct(n - g['massing'])} |")
    L.append(f"| Geometry only — no name, no owner, no market data | {g['massing']:,} | {pct(g['massing'])} |\n")
    L.append("## Graded by the strongest evidence we hold\n")
    L.append("| Grade | What it means | Buildings | Share |\n|---|---|---:|---:|")
    for k, d in (("live", "a dated availability sheet from the developer group — real units and asking prices"),
                 ("register", "DLD register: settled sales, median price, price per m², off-plan share"),
                 ("pipeline", "in the MEED projects corpus — stage and contract value, but no sales"),
                 ("survey", "a name from the open survey record only"),
                 ("massing", "our own model only — footprint, height, storeys")):
        L.append(f"| **{k}** | {d} | {g[k]:,} | {pct(g[k])} |")
    L.append("\n## Every layer, counted separately\n")
    L.append("A building can carry more than one, so these do not sum to the total.\n")
    L.append("| Layer | Source | Buildings |\n|---|---|---:|")
    for k, s in (("survey", "OpenStreetMap / Overture / Wikidata (open survey)"),
                 ("register-named", "named by the DLD register or a developer's own register entry"),
                 ("register", "Dubai Land Department Open Data — settled transactions"),
                 ("pipeline", "MEED projects corpus — stage, value, last update"),
                 ("live", "developer group (captured via Najjuko's WhatsApp) — availability sheets")):
        L.append(f"| {k} | {s} | {lay[k]:,} |")
    L.append("\n## Where the names come from\n")
    L.append("| Source | Buildings |\n|---|---:|")
    for s, c in srcs.most_common(): L.append(f"| {s} | {c:,} |")
    L.append(f"\n## Districts\n")
    L.append("| District | Buildings | Named | Bound to a developer | live | register | pipeline | survey | massing only |")
    L.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for d in sorted(districts, key=lambda x: -x["buildings"]):
        gg = d["grades"]
        L.append(f"| {d['name']} | {d['buildings']:,} | {d['named']:,} | {d['bound']:,} | {gg.get('live',0)} | {gg.get('register',0)} | "
                 f"{gg.get('pipeline',0)} | {gg.get('survey',0):,} | {gg.get('massing',0):,} |")
    L.append(f"\n## Developers present in the twin\n")
    L.append(f"{len(devs)} of the eleven on the board have at least one building bound in a modelled district.\n")
    L.append("| Developer | Buildings bound | with a live sheet | with register sales | in MEED |\n|---|---:|---:|---:|---:|")
    for k, c in devs.most_common():
        sub = [r for r in rows if r["dev"] == k]
        L.append(f"| {KEY2NAME.get(k, k)} | {c} | {sum(1 for r in sub if r['sheet_units'])} | "
                 f"{sum(1 for r in sub if r['dld_sales'])} | {sum(1 for r in sub if r['meed_stage'])} |")
    absent = [KEY2NAME[k] for k in KEY2NAME if k not in devs]
    if absent: L.append(f"\nOn the board but not yet bound to any modelled building: {', '.join(sorted(absent))}.")
    L.append(f"\n## The buildings we hold real data on\n")
    L.append("Every building above 'survey' grade, strongest evidence first.\n")
    L.append("| Building | District | Developer | Scheme | Height | Live sheet | DLD sales | Median (AED) | MEED |")
    L.append("|---|---|---|---|---:|---:|---:|---:|---|")
    rank = {"live": 0, "register": 1, "pipeline": 2}
    for r in sorted([x for x in rows if x["grade"] in rank], key=lambda x: (rank[x["grade"]], -(x["height_m"] or 0))):
        med = f"{r['dld_median_aed']:,.0f}" if r["dld_median_aed"] else "—"
        L.append(f"| {r['name'] or '(unnamed)'} | {DISTRICT_NAME.get(r['district'], r['district'])} | {KEY2NAME.get(r['dev'], r['dev'] or '—')} | "
                 f"{r['project'] or '—'} | {round(r['height_m'] or 0)} m | {r['sheet_units'] or '—'} | {r['dld_sales'] or '—'} | {med} | "
                 f"{(r['meed_stage'] or '—')} |")
    # the live layer is the scarce one - say plainly which sheets we hold that do NOT reach a modelled building, and why
    landed = {(r["dev"], r["project"]) for r in rows if r["sheet_units"]}
    landed_cards = {look(sheets, d, p)["card"] for d, p in landed if look(sheets, d, p)}
    orphans = [v for v in sheets.values() if v["card"] not in landed_cards]
    if orphans:
        modelled = {DISTRICT_NAME.get(d["slug"], d["slug"]).lower() for d in districts} | {d["slug"] for d in districts}
        L.append(f"\n## Live sheets we hold that do not yet reach a building\n")
        L.append(f"{sum(v['units'] for v in orphans):,} units across {len(orphans)} schemes are captured and priced, but no modelled "
                 f"building carries them — either the district is not massed yet, or the scheme is not yet bound to a footprint. "
                 f"This is the shortest list of work that would turn captured data into twin data.\n")
        L.append("| Developer | Scheme | Units | Sheet date | Where it is | District massed? |\n|---|---|---:|---|---|---|")
        for v in sorted(orphans, key=lambda x: -x["units"]):
            area = (v.get("area") or "").strip() or "—"
            hit = any(m in area.lower() for m in modelled if len(m) > 4)
            L.append(f"| {KEY2NAME.get(v['dev'], v['dev'])} | {v['card']} | {v['units']} | {v.get('date') or '—'} | {area[:38]} | "
                     f"{'yes — needs binding' if hit else 'not yet'} |")
    L.append(f"\n## How to read this\n")
    L.append("- **Geometry is not knowledge.** Every footprint in a district becomes a modelled block; that is what the twin draws, "
             "not what it knows. The gap between the two rows at the top is the honest state of the data.\n")
    L.append("- **The live layer is the scarce one.** It arrives only through the developer group, only for developers who post, "
             "and only for the units they are selling that week. It is also the only layer with an asking price on it.\n")
    L.append("- **DLD and MEED answer different questions.** DLD says what has actually sold and for how much; MEED says what is being "
             "built, at what stage and contract value. A building can appear in one and not the other.\n")
    L.append("- Heights, storeys and footprints come from our own massing on open survey footprints. Areas the model reports are an "
             "envelope (footprint × storeys), an upper bound, never a floor-area schedule.\n")
    return "\n".join(L)


if __name__ == "__main__":
    districts, rows = run()
    md = report(districts, rows)
    out_md = os.path.join(ROOT, "data", "board", f"TWIN_AUDIT_{dt.date.today().isoformat()}.md")
    open(out_md, "w", encoding="utf-8").write(md)
    if "--md-only" not in sys.argv:
        json.dump({"generated": dt.datetime.now().isoformat(timespec="seconds"), "districts": districts, "buildings": rows},
                  open(os.path.join(ROOT, "data", "board", "twin_audit.json"), "w", encoding="utf-8"), ensure_ascii=False)
    g = collections.Counter(r["grade"] for r in rows)
    print(f"districts {len(districts)} | buildings {len(rows):,} | named {sum(1 for r in rows if r['name']):,} | "
          f"bound {sum(1 for r in rows if r['dev']):,}")
    print("grades:", dict(g))
    print("report ->", out_md)
