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



PORT_KEY = {"OMNIYAT": "omniyat", "H&H": "hh", "Meraas": "meraas", "Select Group": "select", "Ellington": "ellington", "Arada": "arada",
            "ZAYA/Palma": "zaya_palma", "Fakhruddin": "fakhruddin", "BEYOND": "beyond", "Imtiaz": "imtiaz", "Iman": "iman"}
ROMAN = {"ii": "2", "iii": "3", "iv": "4", "v": "5", "vi": "6", "one": "1", "two": "2", "three": "3", "four": "4", "five": "5", "six": "6", "i": "1"}


def norm_name(n, aliases=()):
    """'COVE EDITION RESIDENCE 6 BY IMTIAZ' -> 'cove edition 6'; 'Cove Edition III by Imtiaz' -> 'cove edition 3'."""
    t = (n or "").lower()
    for a in aliases:
        t = re.sub(r"\bby\s+" + re.escape(a) + r"\b", " ", t); t = re.sub(r"\b" + re.escape(a) + r"\b", " ", t)
    t = re.sub(r"\b(residences?|residency|tower|the|apartments?|dubai|building)\b", " ", t)
    t = re.sub(r"[^a-z0-9 ]", " ", t)
    t = " ".join(ROMAN.get(w, w) for w in t.split())
    return t.strip()


def load_portfolio(dev):
    f = os.path.join(ROOT, "data", "dev_meta", PORT_KEY.get(dev, "_") + "_portfolio.json")
    if not os.path.exists(f):
        return None
    d = json.load(open(f, encoding="utf-8"))
    return {"source": d.get("source"), "fetched": d.get("fetched"), "properties": d.get("properties", [])}


def same(a, b):
    """Exact match on the normalised, space-less form: 'seacliff' == 'sea cliff'; 'pearl house' != 'pearl house 4'; 'sunset bay' != 'sunset bay grand'."""
    return a and b and a.replace(" ", "") == b.replace(" ", "")


def portfolio_hit(name, port, aliases):
    nn = norm_name(name, aliases)
    if not nn or not port:
        return None
    return next((pr for pr in port["properties"] if same(norm_name(pr["name"], aliases), nn)), None)

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
        # --- developer-site portfolio (data/dev_meta/<key>_portfolio.json) = the authority for WHICH projects are theirs.
        #     Alias-only matches ("cove", "symphony") must land on a portfolio name or carry the developer's name; otherwise dropped
        #     (kills "The Cove" = Emaar, "Symphony" = Town Square, "Discovery Dunes").
        port = load_portfolio(dev)
        if port:
            reg_names = {norm_name(p["project"], al) for p in rec["dld_projects_2026"]}
            kept, dropped = [], []
            for t in tx_projects:
                pe = t["project"].lower()
                hit = portfolio_hit(t["project"], port, al)
                if hit or any(a in pe for a in al) or norm_name(t["project"], al) in reg_names:
                    t["portfolio_slug"] = hit["slug"] if hit else None; kept.append(t)
                else:
                    dropped.append(t["project"])
            tx_projects = kept
            rec["portfolio"] = {"source": port["source"], "fetched": port["fetched"], "count": len(port["properties"]),
                                "properties": [{"slug": pr["slug"], "name": pr["name"], "area": pr.get("area"), "url": pr["url"], "image": pr.get("image"),
                                                **{k: pr["facts"].get(k) for k in ("location", "structure", "storeys", "units", "handover", "payment_plans", "mix")},
                                                "downloads_gated": [d["label"] for d in pr.get("downloads", [])]} for pr in port["properties"]],
                                "tx_dropped_as_name_noise": dropped}
            rec["sources"].append("developer website portfolio register (%s, %s)" % (port["source"], port["fetched"]))
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
        # --- MEED: local cache of the UAE register harvested from the Digital Abbot Cloud read API (data/meed/uae_projects.json;
        #     refresh with scripts/meed_harvest.py using DAC_KEY). Title arrives as "Client - Project", so match the client part + aliases.
        meed_cache = os.path.join(ROOT, "data", "meed", "uae_projects.json")
        if os.path.exists(meed_cache):
            mc = json.load(open(meed_cache, encoding="utf-8"))
            # match on the CLIENT half of "Client - Project" with word boundaries (so "iman" is not "Soliman", "zaya" not "Al Mazaya")
            pats = [re.compile(r"\b" + re.escape(a.strip().lower()) + r"\b") for a in al]
            hits = [it for it in mc["items"] if any(p.search((it.get("title") or "").split(" - ")[0].lower()) for p in pats)]
            stages = {}
            for it in hits:
                stages[it.get("stageLabel")] = stages.get(it.get("stageLabel"), 0) + 1
            rec["meed"] = {"status": "matched from local UAE cache (%s, %d rows)" % (mc.get("harvested"), len(mc["items"])), "projects": len(hits),
                           "stages": stages, "value_usd_m": round(sum(it.get("netValueUsdM") or 0 for it in hits)),
                           "active": [{"id": it["projectId"], "title": it["title"], "stage": it.get("stageLabel"), "usd_m": it.get("netValueUsdM"), "updated": it.get("lastUpdated")}
                                      for it in hits if it.get("stageLabel") not in ("Complete", "Cancelled")][:25],
                           "recent_complete": sorted([it["title"] for it in hits if it.get("stageLabel") == "Complete"], key=lambda t: t)[:15]}
            if hits:
                rec["sources"].append("MEED project register via Digital Abbot Cloud (stored corpus v55, not live)")
        else:
            rec["meed"] = {"status": "no local cache - run scripts/meed_harvest.py with DAC_KEY"}
        dna["developers"][dev] = rec
        md.append("## %s  -  %s (rank %d)\n- DLD entities: %s\n- 2026 registrations: %d project(s), %s units - %s\n- 2026 transactions: %d across %d project(s), AED %s; median AED/m2 %s; areas %s\n- aliases matched %s | unmatched (seed only) %s\n- rents: %s contracts, median AED %s/yr\n- ours: %s\n- MEED: %s projects, stages %s, USD %s m, active: %s\n" % (
            dev, seg["label"], seg["rank"], ", ".join(rec["dld_entities"]) or "none in corpus",
            len(rec["dld_projects_2026"]), int(sum(p["units"] or 0 for p in rec["dld_projects_2026"])), "; ".join("%s (%s, %s)" % (p["project"], p["area"], p["status"]) for p in rec["dld_projects_2026"][:6]) or "-",
            rec["tx_2026"]["transactions"], len(tx_projects), format(rec["tx_2026"]["value_aed"], ","), rec["tx_2026"].get("median_aed_per_sqm_across_projects"), ", ".join(rec["tx_2026"]["areas"][:6]) or "-",
            matched or "-", rec["tx_2026"]["aliases_unmatched"] or "-", rn[0][0], rec["rents_2026"]["median_annual_aed"], json.dumps(ours), rec["meed"].get("projects", 0), json.dumps(rec["meed"].get("stages", {})), rec["meed"].get("value_usd_m", 0), "; ".join("%s (%s)" % (a["title"], a["stage"]) for a in rec["meed"].get("active", [])[:5]) or "-"))

out = os.path.join(ROOT, "data", "dev_meta", "developer_dna.json")
json.dump(dna, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
open(out[:-5] + ".md", "w", encoding="utf-8").write("# Developer DNA - %s\n\nSegments and developers per Kendall's table (2 Sep 2026). DLD figures from the naj.duckdb corpus (transactions Jan-Aug 2026, 2026 project registrations); name-matched, so undercounts are possible where a project is registered under an SPV name we do not know yet.\n\n" % today + "\n".join(md))
tok = env_token("INGEST_TOKEN")
r1 = push("dev_segments", SEG, tok)
r2 = push("dev_dna", dna, tok)
print("developers:", len(dna["developers"]), "| dev_segments ->", r1.get("ok"), "| dev_dna ->", r2.get("ok"), "|", out)
