"""The launches block — what has actually launched and is selling now, for PULSE and for the launch board.

Kendall, 21 Sep 2026: "this somehow ties in with the pulse... it's important that the Pulse has the Pulse, and this is the Pulse,
because we have all of these new launches, and these new launches are what people will be talking about. This is what's on the
billboards, this is on the radio, this is the open houses."

He is right and PULSE was thin on exactly that. `collect_projects()` in build_pulse.py reads `data/projects-<date>.csv`, which is
a **326-row open sample** of the register and says so in its own coverage note. We hold the whole register: 3,039 projects, of
which 471 launched in 2025-26 and are still selling. This module reads the whole thing.

Three name problems, all handled here rather than in the surfaces:

1. **The register's `developer_name` is the LANDOWNER, not the brand.** Tested 21 Sep: it returns Dubai Properties for Binghatti
   Aquarise and Dubai Maritime City for Breez by Danube. It is right only where the brand owns its own land (Sobha, DAMAC).
2. **The register carries only Arabic names.** `data/registers/developers/developers_*.json` (2,348 rows) maps `developer_id` to
   `developer_name_en`, which gives the landowner in English for every row.
3. **The real brand** is in `data/projects-<date>.csv` as `DEVELOPER_EN` — AZIZI DEVELOPMENTS where the register says Nakheel.
   It joins on `project_number` and reaches about 7% of live launches. Where it is missing, `brand` is null and no surface may
   guess: the brand is usually in the project name, which is what a broker reads anyway.

    python scripts/build_launches.py            -> prints the block
    python scripts/build_launches.py --inject   -> writes it into public/pulse.json as pulse["launches"]
"""
import collections, csv, glob, io, json, os, re, sys, time

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
REG = os.path.join(ROOT, "data", "raw_downloads", "dda", "prod", "dld__dld_projects-open-api.json")
LIVE = ("NOT_STARTED", "ACTIVE", "PENDING", "CONDITIONAL_ACTIVATING")
YEARS = ("2025", "2026")


def _newest(pattern):
    c = sorted(glob.glob(os.path.join(ROOT, pattern)))
    return c[-1] if c else None


def landowners_en():
    """developer_id -> English name, from the DLD developer register (2,348 rows). This is the LANDOWNER for register rows."""
    p = _newest("data/registers/developers/developers_*.json")
    if not p:
        return {}
    return {r.get("developer_id"): (r.get("developer_name_en") or "").strip()
            for r in json.load(io.open(p, encoding="utf-8")) if r.get("developer_name_en")}


def brands():
    """project_number -> the real developer brand, from the DLD projects CSV. Partial coverage, and that is stated, not hidden."""
    p = _newest("data/projects-????-??-??.csv")
    if not p:
        return {}
    out = {}
    with io.open(p, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            d = (r.get("DEVELOPER_EN") or "").strip()
            if d:
                out[str(r.get("PROJECT_NUMBER"))] = d
    return out


def english_project_names():
    out = {}
    for p in glob.glob(os.path.join(ROOT, "data", "board", "projects_*.json")):
        for r in json.load(io.open(p, encoding="utf-8")).get("projects", []):
            n = (r.get("project_name_en") or "").strip()
            if n:
                out[r.get("project_id")] = n
    return out


def market_names():
    p = os.path.join(ROOT, "data", "dld", "area_alias.json")
    if not os.path.exists(p):
        return {}
    rev = {}
    for market, area in json.load(io.open(p, encoding="utf-8"))["alias"].items():
        rev.setdefault(area, market.title())
    return rev


def launches():
    """Every project launched in 2025-26 and still selling, with the names resolved and the caveats attached."""
    rows = json.load(io.open(REG, encoding="utf-8"))["results"]
    own, brand, en, mk = landowners_en(), brands(), english_project_names(), market_names()
    out = []
    for r in rows:
        if (r.get("project_start_date") or "")[:4] not in YEARS:
            continue
        if r.get("project_status") not in LIVE or not (r.get("no_of_units") or 0):
            continue
        out.append({
            "project": en.get(r["project_id"]) or r.get("project_name") or None,
            "brand": brand.get(str(r.get("project_number"))),             # the real developer, where the CSV reaches
            "master": own.get(r.get("developer_id")) or None,             # the landowner, in English
            "area": r.get("area_name_en"),
            "marketArea": mk.get(r.get("area_name_en")),
            "units": r["no_of_units"],
            "percentComplete": r.get("percent_completed"),
            "started": (r.get("project_start_date") or "")[:10],
            "handover": (r.get("project_end_date") or "")[:10] or None,
            "escrow": bool((r.get("escrow_agent_name") or "").strip()),
            "status": r.get("project_status"),
        })
    out.sort(key=lambda x: -x["units"])
    return out


def block():
    ls = launches()
    area = collections.defaultdict(lambda: {"units": 0, "projects": 0, "units2026": 0})
    for x in ls:
        a = area[x["area"] or "?"]
        a["units"] += x["units"]; a["projects"] += 1
        if x["started"][:4] == "2026":
            a["units2026"] += x["units"]
        a["marketArea"] = x["marketArea"]
    brandc = collections.Counter()
    brandu = collections.Counter()
    for x in ls:
        if x["brand"]:
            brandc[x["brand"]] += 1; brandu[x["brand"]] += x["units"]
    n26 = [x for x in ls if x["started"][:4] == "2026"]
    late = [x for x in ls if x["handover"] and x["handover"] < "2027-01-01" and (x["percentComplete"] or 0) < 10]
    return {
        "note": ("Every project launched in 2025 or 2026 and still selling or being built, from the FULL DLD project register "
                 "(3,039 rows) - not the 326-row open sample behind pulse.projects. This is what is on the billboards."),
        "asOf": time.strftime("%Y-%m-%d"),
        "count": len(ls), "units": sum(x["units"] for x in ls),
        "count2026": len(n26), "units2026": sum(x["units"] for x in n26),
        "escrowPct": round(100.0 * sum(1 for x in ls if x["escrow"]) / max(1, len(ls))),
        "byArea": {a: v for a, v in sorted(area.items(), key=lambda kv: -kv[1]["units"])},
        "topByUnits": ls[:40],
        "started2026": sorted(n26, key=lambda x: -x["units"]),
        "topBrands": [{"developer": d, "projects": brandc[d], "units": brandu[d]} for d, _ in brandu.most_common(12)],
        "brandCoverage": {"withBrand": sum(1 for x in ls if x["brand"]), "of": len(ls),
                          "note": ("The register's developer field is the LANDOWNER, not the brand - it gives Dubai Properties "
                                   "for Binghatti Aquarise. 'brand' comes from the DLD projects CSV and reaches only part of the "
                                   "register; where it is null the brand is usually in the project name. 'master' is the "
                                   "landowner in English and must never be labelled the developer.")},
        "handoverRisk": {"count": len(late), "units": sum(x["units"] for x in late),
                         "note": ("Handover before Jan 2027 and under 10% built. percent_completed is not reliably maintained, "
                                  "so this is a question to ask, never a claim to publish.")},
    }


if __name__ == "__main__":
    b = block()
    if "--inject" in sys.argv:
        p = os.path.join(ROOT, "public", "pulse.json")
        d = json.load(io.open(p, encoding="utf-8"))
        d["launches"] = b
        io.open(p, "w", encoding="utf-8").write(json.dumps(d, ensure_ascii=False, separators=(",", ":")))
        print("pulse.json <- launches: %d projects, %s units (%.1f MB)"
              % (b["count"], "{:,}".format(b["units"]), os.path.getsize(p) / 1e6))
    else:
        print("%d launches, %s units | 2026: %d / %s | escrow on %d%% | brand known for %d of %d"
              % (b["count"], "{:,}".format(b["units"]), b["count2026"], "{:,}".format(b["units2026"]),
                 b["escrowPct"], b["brandCoverage"]["withBrand"], b["brandCoverage"]["of"]))
        for x in b["topBrands"][:8]:
            print("   %-44s %4d units  %2d projects" % (x["developer"][:43], x["units"], x["projects"]))
