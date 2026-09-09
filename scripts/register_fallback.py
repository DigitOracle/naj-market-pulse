"""The fallback tier (Kendall, 8 Sep 2026: "if something falls through the cracks, check MEED, Dubai Statistics, all of those CSVs -
run it against absolutely everything").

For every project on a developer sheet (data/board/remaining.json) this walks the registers we hold, in order of authority, and
records the first identity hit plus whatever context the others add. Nothing is guessed: a hit needs the project's own words
(minus generic ones) inside the register name, and the developer to agree where the register names one.

  1  DLD projects register        data/registers/projects            name, developer, master project, area, status, % complete, unit counts, escrow agent
  2  DLD developers register      data/registers/developers          the developer's licence, phone, web
  3  DLD buildings + land         data/dld/buildings_register.csv, land_registry     parcel / property ids by project name
  4  DM projects (by parcel)      data/registers/project_information + project_building_information   consultant, contractor, permit and completion dates, construction stage
  5  MEED pipeline                already joined by remaining_inventory.py (developer_dna active records)
  6  DSC population by community  data/registers/estimated_population_by_community   people living in the community the project sits in (latest year)
  7  Every other register CSV     data/registers/**/*.csv, data/dld/*.csv, Downloads/*.csv with a name-like column - a last sweep, reported as 'mentions'

Writes the result under each project as "registry" in remaining.json, prints a per-project line, and pushes KV `remaining`.
Usage: python scripts/register_fallback.py [--no-push] [--only "<name substring>"]
"""
import csv, glob, json, os, re, sys, time
import duckdb
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
from build_avail_index import env_token, push  # noqa: E402
BOARD = os.path.join(ROOT, "data", "board"); REG = os.path.join(ROOT, "data", "registers"); DLD = os.path.join(ROOT, "data", "dld")
DOWN = os.path.join(os.path.expanduser("~"), "Downloads")
STOP = {"the", "at", "by", "and", "of", "residences", "residence", "residential", "district", "hotels", "hotel", "tower", "towers", "phase",
        "community", "urban", "apartments", "apartment", "villas", "villa", "townhouses", "project", "dubai", "sharjah", "llc", "fz", "fzco"}
DEV_ALIAS = {"arada": ["arada"], "beyond": ["beyond"], "fakhruddin": ["fakhruddin"], "imtiaz": ["imtiaz"], "emaar": ["emaar"], "omniyat": ["omniyat"],
             "meraas": ["meraas"], "select group": ["select"], "ellington": ["ellington"], "iman": ["iman"], "prestige one": ["prestige one", "prestigeone"], "zaya/palma": ["zaya", "palma"], "h&h": ["h&h", "h & h"]}


def toks(t):
    return {w for w in re.sub(r"[^a-z0-9]+", " ", (t or "").lower()).split() if len(w) >= 3 and w not in STOP and not w.isdigit()}


def q(con, sql, *a):
    try: return con.execute(sql, list(a)).fetchall()
    except Exception as e:
        print("   query failed:", str(e)[:90]); return []


def csvglob(*parts):
    return ",".join("'" + p.replace(chr(92), "/") + "'" for p in glob.glob(os.path.join(*parts)))


def dev_ok(sheet_dev, reg_dev):
    if not sheet_dev or not reg_dev: return True
    al = DEV_ALIAS.get(sheet_dev.lower(), [sheet_dev.lower()])
    return any(a in reg_dev.lower() for a in al)


def best_name_match(pt, rows, name_ix, dev_ix=None, sheet_dev=None, min_share=1):
    """rows: tuples; return (score, row) for the register row whose name shares the most distinctive words with the project."""
    best = None
    for r in rows:
        rt = toks(r[name_ix]); sh = pt & rt
        if len(sh) < min_share: continue
        if dev_ix is not None and not dev_ok(sheet_dev, r[dev_ix]): continue
        score = (len(sh), -abs(len(rt) - len(pt)))
        if best is None or score > best[0]: best = (score, r)
    return best


def main():
    do_push = "--no-push" not in sys.argv; only = (sys.argv[sys.argv.index("--only") + 1].lower() if "--only" in sys.argv else None)
    remp = os.path.join(BOARD, "remaining.json"); doc = json.load(open(remp, encoding="utf-8")); P = doc["projects"]
    con = duckdb.connect()
    PR = f"read_csv_auto([{csvglob(REG, 'projects', '*.csv')}], all_varchar=true, union_by_name=true)"
    DV = f"read_csv_auto([{csvglob(REG, 'developers', '*.csv')}], all_varchar=true, union_by_name=true)"
    PI = f"read_csv_auto([{csvglob(REG, 'project_information', '*.csv')}], all_varchar=true, union_by_name=true)"
    PB = f"read_csv_auto([{csvglob(REG, 'project_building_information', '*.csv')}], all_varchar=true, union_by_name=true)"
    POP = f"read_csv_auto([{csvglob(REG, 'estimated_population_by_community', '*.csv')}], all_varchar=true)"
    BR = f"read_csv_auto('{os.path.join(DLD, 'buildings_register.csv').replace(chr(92), '/')}', all_varchar=true, ignore_errors=true)"
    LR = f"read_csv_auto('{os.path.join(DOWN, 'land_registry_2026-09-04_17-30-03_0001.csv').replace(chr(92), '/')}', all_varchar=true, sample_size=50000)"
    projects = q(con, f"select project_name, developer_name, master_project_en, area_name_en, project_status, percent_completed, no_of_units, no_of_villas, no_of_buildings, escrow_agent_name, project_number, property_id, project_end_date, project_description_en from {PR} where project_name is not null")
    devs = q(con, f"select developer_name_en, developer_number, license_number, license_expiry_date, phone, webpage, legal_status_en from {DV} where developer_name_en is not null")
    pop_year = (q(con, f'select max("Year") from {POP}') or [[None]])[0][0]
    pop = {r[0].strip().lower(): (r[1], r[0].strip()) for r in q(con, f'select "Sector & Community", "Value" from {POP} where "Year" = ?', pop_year)}
    # last-sweep CSV inventory: any csv with a name-like column
    sweep_files = [f for f in glob.glob(os.path.join(REG, "**", "*.csv"), recursive=True) + glob.glob(os.path.join(DLD, "*.csv")) + glob.glob(os.path.join(DOWN, "*.csv"))
                   if os.path.getsize(f) < 400 * 1024 * 1024 and not re.search(r"building_floor_level|building_permits|building_summary|bus_stop|sheryan", f)]
    print(f"registers: {len(projects):,} DLD projects · {len(devs):,} developers · population {pop_year} for {len(pop)} communities · {len(sweep_files)} CSVs in the last sweep")
    BR_ROWS = q(con, f"select PROJECT_EN, PARCEL_ID, PARENT_PROPERTY_ID, count(*) from {BR} where PROJECT_EN is not null group by 1,2,3")
    LR_ROWS = q(con, f"select project_name_en, master_project_en, area_name_en, munc_zip_code, count(*), any_value(parcel_id) from {LR} where project_name_en is not null group by 1,2,3,4")
    print(f"grouped once: {len(BR_ROWS):,} building-project rows, {len(LR_ROWS):,} land-project rows")
    # 7 (precomputed): one pass over every register CSV, all projects at once - which files mention which project
    PATS = {pk: re.compile(".*".join(re.escape(w) for w in sorted(toks(rec.get("name") or pk))[:3]), re.I) for pk, rec in P.items() if toks(rec.get("name") or pk)}
    ANY = re.compile("|".join(sorted({re.escape(w) for pk, rec in P.items() for w in toks(rec.get("name") or pk)}, key=len, reverse=True)), re.I) if PATS else None
    MENTIONS = {pk: [] for pk in P}
    t0 = time.time()
    for f in sweep_files:
        try:
            found = set()
            with open(f, encoding="utf-8", errors="ignore") as fh:
                fh.readline()
                for line in fh:
                    if not ANY or not ANY.search(line): continue
                    for pk, pat in PATS.items():
                        if pk in found: continue
                        if pat.search(line): found.add(pk)
                    if len(found) == len(PATS): break
            label = os.path.relpath(f, ROOT) if f.startswith(ROOT) else os.path.basename(f)
            for pk in found: MENTIONS[pk].append(label)
        except Exception: pass
    print(f"csv sweep: {len(sweep_files)} files in {time.time()-t0:.0f}s")
    hits = 0
    for pk, rec in P.items():
        name = rec.get("name") or pk
        if only and only not in name.lower(): continue
        pt = toks(name); dev = rec.get("developer") or ""
        R = {"checked": time.strftime("%Y-%m-%d"), "sources_hit": []}
        # 1 DLD projects register
        b = best_name_match(pt, projects, 0, 1, dev)
        if b:
            r = b[1]
            R["dld_project"] = {"name": r[0], "developer": r[1], "master": r[2], "area": r[3], "status": r[4], "percent_completed": r[5], "units": r[6], "villas": r[7], "buildings": r[8], "escrow_agent": r[9], "project_number": r[10], "property_id": r[11], "end_date": r[12]}
            R["sources_hit"].append("DLD projects register")
            area_for_pop = r[3]
        else:
            area_for_pop = None
        # 2 developers register
        if dev:
            al = DEV_ALIAS.get(dev.lower(), [dev.lower()])
            d = next((x for x in devs if any(a in (x[0] or "").lower() for a in al)), None)
            if d:
                R["dld_developer"] = {"name": d[0], "number": d[1], "licence": d[2], "licence_expiry": d[3], "phone": d[4], "web": d[5], "status": d[6]}
                R["sources_hit"].append("DLD developers register")
        # 3 DLD buildings / land: parcel and property ids by name
        b = best_name_match(pt, BR_ROWS, 0)
        if b and b[0][0] >= max(1, len(pt) - 1):
            R["dld_buildings"] = {"project": b[1][0], "parcel_id": b[1][1], "parent_property_id": b[1][2], "rows": b[1][3]}; R["sources_hit"].append("DLD buildings register")
        b = best_name_match(pt, LR_ROWS, 0)
        if b and b[0][0] >= max(1, len(pt) - 1):
            R["dld_land"] = {"project": b[1][0], "master": b[1][1], "area": b[1][2], "community_no": b[1][3], "plots": b[1][4], "parcel_id": b[1][5]}; R["sources_hit"].append("DLD land registry")
            area_for_pop = area_for_pop or b[1][2]
        # 4 DM by parcel: consultant / contractor / stage
        parcel = (R.get("dld_buildings") or {}).get("parcel_id") or (R.get("dld_land") or {}).get("parcel_id")
        if parcel:
            pid = str(parcel).split(".")[0]
            dm = q(con, f"select project_no, consultant_english, contractor_english, project_status_english, permit_date, expected_completion_date, project_completion_date from {PI} where split_part(parcel_id,'.',1) = ? order by permit_date desc limit 1", pid)
            if dm:
                r = dm[0]; stage = q(con, f"select building_construction_stage_e, count(*) from {PB} where project_no = ? group by 1 order by 2 desc limit 1", r[0])
                R["dm_project"] = {"project_no": r[0], "consultant": r[1], "contractor": r[2], "status": r[3], "permit": r[4], "expected_completion": r[5], "completed": r[6], "stage": (stage[0][0] if stage else None)}
                R["sources_hit"].append("DM project register")
        # 6 DSC population for the community
        if area_for_pop:
            at = toks(area_for_pop); hit = None
            for k, (v, label) in pop.items():
                if at and at <= toks(label): hit = (label, v); break
            if hit: R["community_population"] = {"community": hit[0], "people": hit[1], "year": pop_year, "source": "Dubai Statistics Centre"}; R["sources_hit"].append("DSC population")
        mentions = MENTIONS.get(pk, [])
        if mentions: R["mentions"] = mentions[:12]
        if R["sources_hit"] or mentions: hits += 1
        rec["registry"] = R
        idn = R.get("dld_project") or {}
        print(f"  {name[:30]:<30} {dev[:10]:<10} | {', '.join(R['sources_hit']) or 'no register hit':<75} | {('DLD: ' + str(idn.get('status')) + ' ' + str(idn.get('percent_completed') or '') + '%') if idn else ''} | mentions {len(mentions)}")
    doc["registry_note"] = "registry = the fallback tier (DLD projects/developers/buildings/land, DM project register, DSC population, then every register CSV); MEED sits under 'pipeline'."
    json.dump(doc, open(remp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n{hits} of {len(P)} sheet projects touched by at least one register")
    if do_push: print("remaining ->", push("remaining", doc, env_token("INGEST_TOKEN")).get("ok"))


if __name__ == "__main__":
    main()
