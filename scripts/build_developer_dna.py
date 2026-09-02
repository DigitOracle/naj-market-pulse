"""Developer DNA - the classification layer for the Azimuth board (Kendall's segment table, 2 Sep 2026).
Only the developers in data/dev_meta/developer_segments.json are ingested. For each one this composes a DNA record from
everything we hold, source-stamped:
  DLD (naj.duckdb)   projects registered 2026 (developer name match), transactions Jan-Aug 2026 (project-name match via
                     aliases + registered project names), rents (same names)
  Ours               availability sheets captured (data/avail), curated building meta (data/dev_meta/curated), Golden Building lane
  MEED               Digital Abbot Cloud read API - only when DAC_KEY is set in the environment (key never stored here)
Writes data/dev_meta/developer_dna.json + developer_dna.md and pushes KV dev_segments + dev_dna (knowledge-graph feed).
Every project alias is a SEED until it matches DLD rows - matched aliases are reported, unmatched are flagged, never quoted.
"""
import datetime as dt, glob, json, os, re, statistics, sys, urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
import duckdb  # noqa: E402
from build_avail_index import env_token, push  # noqa: E402

SEG = json.load(open(os.path.join(ROOT, "data", "dev_meta", "developer_segments.json"), encoding="utf-8"))
con = duckdb.connect(os.path.join(ROOT, "naj.duckdb"), read_only=True)
today = dt.date.today().isoformat()


def like(cols, pats):
    return " or ".join("lower(%s) like '%%%s%%'" % (c, p.lower().replace("'", "''")) for c in cols for p in pats)


def q(sql):
    return con.execute(sql).fetchall()


def num(v):
    try:
        return float(v)
    except Exception:
        return None


dna, md = {"updated": today, "source_note": SEG["source"], "segments": SEG["segments"], "developers": {}}, []
avail_files = sorted(glob.glob(os.path.join(ROOT, "data", "avail", "*_20*.json")))
curated = {os.path.basename(p)[:-5]: json.load(open(p, encoding="utf-8")) for p in glob.glob(os.path.join(ROOT, "data", "dev_meta", "curated", "*.json"))}
dac_key = os.environ.get("DAC_KEY")

for seg in SEG["segments"]:
    for dev in seg["developers"]:
        al = SEG["aliases"].get(dev, [dev.lower()])
        pal = SEG.get("project_aliases", {}).get(dev, [])
        rec = {"segment": seg["key"], "segment_label": seg["label"], "segment_rank": seg["rank"], "aliases": al, "sources": []}
        # --- DLD project register (2026 registrations in the corpus)
        prj = q("select PROJECT_EN, DEVELOPER_EN, PROJECT_STATUS, PERCENT_COMPLETED, CNT_UNIT, AREA_EN, PROJECT_VALUE, START_DATE, COMPLETION_DATE, MASTER_PROJECT_EN from projects where %s" % like(["DEVELOPER_EN"], al))
        rec["dld_entities"] = sorted({r[1].strip() for r in prj})
        rec["dld_projects_2026"] = [{"project": r[0].strip(), "entity": r[1].strip(), "status": r[2], "pct_complete": num(r[3]), "units": num(r[4]), "area": r[5],
                                     "value_aed": num(r[6]), "start": str(r[7])[:10] if r[7] else None, "completion": str(r[8])[:10] if r[8] else None, "master": r[9]} for r in prj]
        if prj:
            rec["sources"].append("DLD project register (corpus of 2026 registrations)")
        # --- transactions: registered project names + seed aliases; report which aliases actually matched
        names = [p["project"] for p in rec["dld_projects_2026"]] + pal
        matched, tx_projects = [], []
        for nm in names:
            if not nm.strip():
                continue
            rows = q("select PROJECT_EN, count(*), sum(try_cast(TRANS_VALUE as double)), median(try_cast(TRANS_VALUE as double)/nullif(try_cast(PROCEDURE_AREA as double),0)), "
                     "avg(case when IS_OFFPLAN_EN='Off-Plan' then 1.0 else 0.0 end), max(INSTANCE_DATE), min(INSTANCE_DATE), max(AREA_EN), max(MASTER_PROJECT_EN) "
                     "from transactions where %s group by 1" % like(["PROJECT_EN", "MASTER_PROJECT_EN"], [nm]))
            if rows:
                matched.append(nm)
            for r in rows:
                if r[0] and r[0] not in [t["project"] for t in tx_projects]:
                    tx_projects.append({"project": r[0].strip(), "tx": r[1], "value_aed": round(r[2] or 0), "median_aed_per_sqm": round(r[3]) if r[3] else None,
                                        "offplan_share": round(r[4], 2) if r[4] is not None else None, "last": str(r[5])[:10], "first": str(r[6])[:10], "area": r[7], "master": r[8], "matched_by": nm})
        rec["tx_2026"] = {"projects": sorted(tx_projects, key=lambda t: -t["tx"]), "transactions": sum(t["tx"] for t in tx_projects), "value_aed": sum(t["value_aed"] for t in tx_projects),
                          "areas": sorted({t["area"] for t in tx_projects if t["area"]}), "aliases_matched": matched, "aliases_unmatched": [n for n in pal if n not in matched]}
        if tx_projects:
            rec["sources"].append("DLD transactions Jan-Aug 2026 (name match)")
            vals = [t["median_aed_per_sqm"] for t in tx_projects if t["median_aed_per_sqm"]]
            rec["tx_2026"]["median_aed_per_sqm_across_projects"] = round(statistics.median(vals)) if vals else None
        # --- rents on the same names (how the stock lets)
        rn = q("select count(*), median(try_cast(ANNUAL_AMOUNT as double)) from rents where %s" % like(["PROJECT_EN", "MASTER_PROJECT_EN"], [n for n in names if n.strip()] or ["__none__"]))
        rec["rents_2026"] = {"contracts": rn[0][0], "median_annual_aed": round(rn[0][1]) if rn and rn[0][1] else None}
        # --- what WE hold
        ours = {"availability_sheets": [os.path.basename(p) for p in avail_files if os.path.basename(p).lower().startswith(al[0].split(" ")[0])],
                "curated_buildings": [k for k, v in curated.items() if any(a in json.dumps(v).lower() for a in al)],
                "golden_building_lane": dev == "Imtiaz"}
        rec["ours"] = ours
        if ours["availability_sheets"] or ours["curated_buildings"]:
            rec["sources"].append("DigitAlchemy holdings (availability sheets / curated meta)")
        # --- MEED (only with a key in the environment)
        rec["meed"] = {"status": "not queried - set DAC_KEY to enable (key is never stored in the repo)"} if not dac_key else {"status": "queried"}
        if dac_key:
            try:
                req = urllib.request.Request("https://www.digitalabbot.io/api/cloud/v1/meed/projects?country=United%20Arab%20Emirates&limit=200", headers={"x-dac-key": dac_key, "User-Agent": "najma-dna/1.0"})
                data = json.load(urllib.request.urlopen(req, timeout=60))
                hits = [p for p in data.get("items", data.get("projects", [])) if any(a in json.dumps(p).lower() for a in al)]
                rec["meed"] = {"status": "queried", "corpus": data.get("corpus") or data.get("version"), "hits": hits[:20]}
                rec["sources"].append("Digital Abbot Cloud MEED corpus (stored snapshot, not live)")
            except Exception as e:
                rec["meed"] = {"status": "error: " + str(e)[:80]}
        dna["developers"][dev] = rec
        md.append("## %s  -  %s (rank %d)\n- DLD entities: %s\n- 2026 registrations: %d project(s), %s units - %s\n- 2026 transactions: %d across %d project(s), AED %s; median AED/m2 %s; areas %s\n- aliases matched %s | unmatched (seed only) %s\n- rents: %s contracts, median AED %s/yr\n- ours: %s\n- MEED: %s\n" % (
            dev, seg["label"], seg["rank"], ", ".join(rec["dld_entities"]) or "none in corpus",
            len(rec["dld_projects_2026"]), int(sum(p["units"] or 0 for p in rec["dld_projects_2026"])), "; ".join("%s (%s, %s)" % (p["project"], p["area"], p["status"]) for p in rec["dld_projects_2026"][:6]) or "-",
            rec["tx_2026"]["transactions"], len(tx_projects), format(rec["tx_2026"]["value_aed"], ","), rec["tx_2026"].get("median_aed_per_sqm_across_projects"), ", ".join(rec["tx_2026"]["areas"][:6]) or "-",
            matched or "-", rec["tx_2026"]["aliases_unmatched"] or "-", rn[0][0], rec["rents_2026"]["median_annual_aed"], json.dumps(ours), rec["meed"]["status"]))

out = os.path.join(ROOT, "data", "dev_meta", "developer_dna.json")
json.dump(dna, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
open(out[:-5] + ".md", "w", encoding="utf-8").write("# Developer DNA - %s\n\nSegments and developers per Kendall's table (2 Sep 2026). DLD figures from the naj.duckdb corpus (transactions Jan-Aug 2026, 2026 project registrations); name-matched, so undercounts are possible where a project is registered under an SPV name we do not know yet.\n\n" % today + "\n".join(md))
tok = env_token("INGEST_TOKEN")
r1 = push("dev_segments", SEG, tok)
r2 = push("dev_dna", dna, tok)
print("developers:", len(dna["developers"]), "| dev_segments ->", r1.get("ok"), "| dev_dna ->", r2.get("ok"), "|", out)
