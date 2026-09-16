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
import collections, datetime as dt, glob, json, os, re, statistics, sys, urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
import duckdb  # noqa: E402
from build_avail_index import env_token, push  # noqa: E402

SEG_FILE = os.path.join(ROOT, "data", "dev_meta", "developer_segments.json")
con = None          # main() opens naj.duckdb. Importing norm_name / same must not open the store, rebuild the DNA or push it:
                    # on 14 Sep the twin audit's import pushed 553 KB to the Worker every sweep and failed when the upload dropped.


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
            "ZAYA": "zaya", "Palma": "palma", "Fakhruddin": "fakhruddin", "BEYOND": "beyond", "Imtiaz": "imtiaz", "Iman": "iman", "Prestige One": "prestigeone", "Emaar": "emaar", "Sobha": "sobha"}
STRICT_PORTFOLIO = {"Imtiaz"}
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


# 15 Sep 2026 (Kendall: developer figures leaking across developers). Raw substring matching put Emaar's "The Valley - Alana" under
# OMNIYAT ("lana"), Prestige One / Milestone / Whitestone under Iman ("one residence", "iman "), six Imtiaz Cove Edition projects under
# Ellington. Names now match whole (name_match: short seeds exact only, never substrings); a project registered to another board
# developer in the DLD register, or titled with another board developer's name, is vetoed and listed; strict developers still count
# only confirmed rows.
def wmatch(hay, needle):
    """Whole-word containment: 'iman developers' in 'IMAN DEVELOPERS L.L.C' yes; 'iman' in 'SOLIMAN TOWER' no."""
    n = (needle or "").strip().lower()
    return bool(n) and re.search(r"(?<![a-z0-9])" + re.escape(n) + r"(?![a-z0-9])", (hay or "").lower()) is not None


def wlike(col, pats):
    """SQL twin of wmatch for DuckDB (RE2): whole-word, case-insensitive."""
    pats = [p.strip().lower() for p in pats if p and p.strip()]
    if not pats:
        return "false"
    return " or ".join("regexp_matches(lower(%s), '(^|[^a-z0-9])%s([^a-z0-9]|$)')" % (col, re.escape(p).replace("'", "''")) for p in pats)


_SUFFIX = {"residence", "residences", "residency", "apartment", "apartments"}


def light_name(n):
    """Light normaliser for short or branded seeds: every word kept except residence-type suffixes ('THE LANA RESIDENCES' -> 'the lana')."""
    return " ".join(ROMAN.get(w, w) for w in re.sub(r"[^a-z0-9 ]", " ", (n or "").lower()).split() if w not in _SUFFIX)


def name_match(project, seed, aliases=()):
    """Whole-name matching, never substrings:
      branded seeds ('sobha central', 'sobha one')  or  short seeds (under 6 letters: 'lana', 'vento', 'w residences')
                                                     -> the same name, only residence-type suffixes ignored ('THE ONE', 'VENTO TOWER' do not match)
      one specific word ('nirvana', 'peninsula')     -> exact, or the name's first word ('PENINSULA FIVE')
      two or more words ('cove edition', 'city walk') -> exact, or the words in sequence ('CITY WALK CRESTLANE 1')
    So 'THE VALLEY - ALANA' !~ 'lana', 'MILESTONE RESIDENCES' !~ 'one residence', 'CENTRAL PARK PLAZA' !~ 'sobha central'."""
    s, p = norm_name(seed, aliases), norm_name(project, aliases)
    if s != norm_name(seed) or len(s.replace(" ", "")) < 6:
        s0, p0 = light_name(seed), light_name(project)
        if len(s0.replace(" ", "")) < 3:                  # 'one residence' -> '1': too short to drop the suffix ('1 RESIDENCES' is not it)
            full = lambda n: " ".join(ROMAN.get(w, w) for w in re.sub(r"[^a-z0-9 ]", " ", (n or "").lower()).split())
            s0, p0 = full(seed), full(project)
        return bool(s0 and p0) and same(p0, s0)
    if not p:
        return False
    if same(p, s):
        return True
    if len(s.split()) == 1:
        return p.startswith(s + " ")
    return re.search(r"(^| )" + re.escape(s) + r"( |$)", p) is not None


def partial_match(project, seed, aliases=()):
    """The old substring test, kept only to LIST near-misses for review (never counted)."""
    s, p = norm_name(seed, aliases).replace(" ", ""), norm_name(project, aliases).replace(" ", "")
    return len(s) >= 3 and s in p


def spine_links():
    """15 Sep 2026 (digital thread P1.3): what the lake's project spine knows, for the matcher below. Empty maps when the lake or the spine
    tables cannot be read - every caller then falls back to names, as before. Import stays side-effect free: nothing opens until called.
      groups     board developer -> {developer number: {"name", "decision", "method", "score", "projects"}}   lk_xref developer_group
      key_rows   our sales PROJECT_EN (upper) -> {developer number: sales rows}   each sale paired with ITS register row (or the register's
                 own name-number pair), the project's developer from lk_d_project - a key, not a name match
      key_ids    our sales PROJECT_EN (upper) -> {project canonical id: sales rows}, same pairing
      rent_ids   (rent PROJECT_EN, AREA_EN) -> project canonical id   lk_rent_project, accepted (exact registered name in the rent's own area)"""
    from keys import norm_number
    out = {"groups": {}, "key_rows": {}, "key_ids": {}, "rent_ids": {}, "note": ""}
    try:
        import lake
        lk = lake.connect(read_only=True)
        A = lake.ALIAS
        have = {r[0] for r in lk.execute("select table_name from information_schema.tables where table_catalog = '%s'" % A).fetchall()}
        need = {"lk_xref", "lk_d_developer", "lk_d_project", "v_transactions_register_project"}
        if not need <= have:
            out["note"] = "project spine unavailable (missing %s) - names only" % ", ".join(sorted(need - have))
            return out
        name_of = {v: k for k, v in PORT_KEY.items()}
        for gid, dn, nm, dec, meth, score, nproj in lk.execute(
                "select x.from_id, d.developer_number, d.name_en, x.decision, x.method, x.score, d.projects_as_developer "
                "from %s.lk_xref x join %s.lk_d_developer d on d.canonical_id = x.to_id where x.job = 'developer_group'" % (A, A)).fetchall():
            dev = name_of.get(gid[4:])
            if dev and norm_number(dn):
                out["groups"].setdefault(dev, {})[norm_number(dn)] = {"name": nm, "decision": dec, "method": meth, "score": score, "projects": nproj}
        for nm, dn, cid, n in lk.execute(
                "select upper(trim(v.PROJECT_EN)), d.developer_number, d.canonical_id, count(*) from %s.v_transactions_register_project v "
                "join %s.lk_d_project d on d.project_number = v.project_number "
                "where v.project_link in ('register row', 'register name') and nullif(trim(v.PROJECT_EN), '') is not null group by all" % (A, A)).fetchall():
            if norm_number(dn):
                out["key_rows"].setdefault(nm, collections.Counter())[norm_number(dn)] += n
            out["key_ids"].setdefault(nm, collections.Counter())[cid] += n
        if "lk_rent_project" in have:
            for pe, ae, cid in lk.execute(
                    "select r.project_en, r.area_en, 'prj:' || cast(r.project_id as varchar) from %s.lk_rent_project r "
                    "where r.decision = 'accepted' and r.project_id is not null" % A).fetchall():
                out["rent_ids"][(pe, ae)] = cid
        out["note"] = "project spine: %d developer groups, %d sales project names keyed to their register rows, %d rent names" % (
            len(out["groups"]), len(out["key_rows"]), len(out["rent_ids"]))
    except Exception as e:
        out = {"groups": {}, "key_rows": {}, "key_ids": {}, "rent_ids": {}, "note": "project spine unavailable: %s - names only" % str(e)[:120]}
    return out


def developer_numbers(con_, seg, spine=None):
    """DLD developer numbers per board developer. 15 Sep 2026 (digital thread P1.3): the developer entities the lake's project spine
    accepts for the group (lk_xref developer_group: register name, portfolio projects or a hand decision), plus - as before - the English
    developer names of the 2026 registrations (whole-word alias match), minus any number rejected by hand for that group (a number held
    for review keeps its name match: review never removes what was counted). Without the spine, the names alone. Numbers normalised by
    keys.norm_number ('2537.00' == '2537')."""
    from keys import norm_number
    names = con_.execute("select distinct DEVELOPER_NUMBER, DEVELOPER_EN from projects where DEVELOPER_NUMBER is not null").fetchall()
    groups = (spine or {}).get("groups") or {}
    out = {}
    for s in seg["segments"]:
        for dev in s["developers"]:
            al = seg["aliases"].get(dev, [dev.lower()])
            g = groups.get(dev) or {}
            held = {n for n, l in g.items() if l["decision"] == "rejected"}      # review is not a rejection: a name match still counts
            out[dev] = {n for n, l in g.items() if l["decision"] == "accepted"} | {
                norm_number(n) for n, en in names if norm_number(n) and norm_number(n) not in held and any(wmatch(en, a) for a in al)}
    return out


def register_developers(con_=None, spine=None):
    """Project name (upper) -> DLD developer numbers. Empty when nothing can be read (the veto is then simply not applied, and the
    run says so). 15 Sep 2026 (digital thread Q1/Q3): numbers normalised by keys.norm_number on both sides; the project numbers come
    from lk_project_numbers (register extract + the 2026 registrations, register_joins sales_projects) when the lake has it, else
    from lk_dld_projects; and the 2026 registrations' own English names (naj.duckdb projects) are added directly, so a launch the
    6 Jul extract lacks can still be vetoed. P1.3: plus the developer of the register row each of our sales is paired with (spine key_rows)."""
    from keys import norm_number
    reg, notes = {}, []

    def add(nm, dn):
        n = norm_number(dn)
        if nm and n:
            reg.setdefault(str(nm).strip().upper(), set()).add(n)
    for nm, rows in ((spine or {}).get("key_rows") or {}).items():
        for dn in rows:
            add(nm, dn)
    if (spine or {}).get("key_rows"):
        notes.append("sales rows paired with their register rows")
    try:
        import lake
        lk = lake.connect(read_only=True)
        A = lake.ALIAS
        have = {r[0] for r in lk.execute("select table_name from information_schema.tables where table_catalog = '%s'" % A).fetchall()}
        numbers = "%s.lk_project_numbers" % A if "lk_project_numbers" in have else "%s.lk_dld_projects" % A
        num = "try_cast(try_cast(trim(cast(%s as varchar)) as double) as bigint)"
        rows = lk.execute(
            "select n.project_en, p.developer_number from %s.lk_project_number_names n join %s p on %s = %s "
            "where n.project_en is not null and p.developer_number is not null "
            "union select t.portal_project_en, p.developer_number from %s.lk_txn_register t join %s p on %s = %s "
            "where t.portal_project_en is not null and p.developer_number is not null" % (
                A, numbers, num % "p.project_number", num % "n.project_number", A, numbers, num % "p.project_number", num % "t.project_number")).fetchall()
        for nm, dn in rows:
            add(nm, dn)
        notes.append("project numbers from " + numbers.split(".")[-1])
    except Exception as e:
        notes.append("lake register unavailable: %s" % str(e)[:120])
    if con_ is not None:
        try:
            for nm, dn in con_.execute("select PROJECT_EN, DEVELOPER_NUMBER from projects where PROJECT_EN is not null").fetchall():
                add(nm, dn)
            notes.append("plus the 2026 registrations")
        except Exception as e:
            notes.append("2026 registrations unavailable: %s" % str(e)[:80])
    return reg, (None if reg else "register veto unavailable: " + "; ".join(notes))


def tx_aggregates(con_):
    """One pass over transactions, grouped by project, in the shape the per-developer matcher needs."""
    return con_.execute(
        "select PROJECT_EN, count(*), sum(try_cast(TRANS_VALUE as double)), median(try_cast(TRANS_VALUE as double)/nullif(try_cast(PROCEDURE_AREA as double),0)), "
        "avg(case when IS_OFFPLAN_EN='Off-Plan' then 1.0 else 0.0 end), max(INSTANCE_DATE), min(INSTANCE_DATE), max(AREA_EN), max(MASTER_PROJECT_EN) "
        "from transactions where PROJECT_EN is not null and trim(PROJECT_EN) <> '' group by 1").fetchall()


def match_tx_projects(dev, al, names, reg_names, port, agg, dev_nums, reg_dev, other_aliases=None, strict=False, key_rows=None):
    """-> (counted, unconfirmed, vetoed, matched_names). counted rows are the developer's; the other two are listed, never counted.
    A project is a candidate when its title carries the developer's own name, or it matches a registered name / seed whole (name_match),
    or its master project IS a seed, or (P1.3) most of its sales rows pair with register rows whose developer is one of this developer's
    entities (key_rows: PROJECT_EN upper -> {developer number: rows}). It is vetoed when the DLD register files it under another board
    developer, or its title names another board developer and not this one ('COVE EDITION RESIDENCE 6 BY IMTIAZ' is not Ellington's) -
    a project the register key gives to this developer is never vetoed on its title. Strict developers (register known complete) count
    only rows the portfolio, their own name, a registration or the register confirms."""
    mine = dev_nums.get(dev, set())
    others = {d: ids for d, ids in dev_nums.items() if d != dev and ids}
    other_aliases = other_aliases or {}
    key_rows = key_rows or {}
    counted, unconfirmed, vetoed, matched = [], [], [], []
    for r in agg:
        project, master = (r[0] or "").strip(), (r[8] or "").strip()
        dev_named = any(wmatch(project, a) for a in al)
        kr = key_rows.get(project.upper()) or {}
        keyed = bool(mine) and sum(n for d, n in kr.items() if d in mine) * 2 > sum(kr.values())
        by = next((nm for nm in names if nm.strip() and name_match(project, nm, al)), None)
        master_by = None if by else next((nm for nm in names if nm.strip() and master and len(norm_name(nm, al).replace(" ", "")) >= 6
                                          and same(norm_name(master, al), norm_name(nm, al))), None)
        if not (dev_named or by or master_by or keyed):
            near = next((nm for nm in names if nm.strip() and partial_match(project, nm, al)), None)
            if near:                                   # a partial-name hit: listed for review, never counted
                unconfirmed.append({"project": project, "tx": r[1], "value_aed": round(r[2] or 0), "area": r[7], "matched_by": near,
                                    "reason": "partial name only", "portfolio_unmatched": True})
            continue
        by = by or master_by or ("developer name" if dev_named else "registered developer")
        if by not in matched and by not in ("developer name", "registered developer"):
            matched.append(by)
        t = {"project": project, "tx": r[1], "value_aed": round(r[2] or 0), "median_aed_per_sqm": round(r[3]) if r[3] else None,
             "offplan_share": round(r[4], 2) if r[4] is not None else None, "last": str(r[5])[:10], "first": str(r[6])[:10], "area": r[7], "master": r[8], "matched_by": by}
        reg = reg_dev.get(project.upper(), set())
        owner = next((d for d, ids in others.items() if reg & ids), None)
        if reg and not (reg & mine) and owner:
            t["registered_to"] = owner
            vetoed.append(t)
            continue
        named_other = None if (dev_named or keyed) else next((d for d, als in other_aliases.items() if d != dev and any(wmatch(project, a) for a in als)), None)
        if named_other:
            t["registered_to"] = named_other + " (named in the title)"
            vetoed.append(t)
            continue
        hit = portfolio_hit(project, port, al) if port else None
        t["portfolio_slug"] = hit["slug"] if hit else None
        reg_name = norm_name(project, al) in reg_names
        if dev_named or hit or reg_name or (reg & mine) or not strict:
            t["confirmed_by"] = ("developer name" if dev_named else "portfolio" if hit else "register name" if reg_name else
                                 "DLD project register" if reg & mine else "master community" if master_by else "whole-name match")
            if not (dev_named or hit or reg_name or (reg & mine)):
                t["portfolio_unmatched"] = True          # counted, but the twin binders keep skipping it (bind_registers, build_anchors)
            counted.append(t)
        else:
            t["portfolio_unmatched"] = True
            unconfirmed.append(t)
    return counted, unconfirmed, vetoed, matched


def main():
    global con
    SEG = json.load(open(SEG_FILE, encoding="utf-8"))
    con = duckdb.connect(os.path.join(ROOT, "naj.duckdb"), read_only=True)
    today = dt.date.today().isoformat()
    dna, md = {"updated": today, "source_note": SEG["source"], "segments": SEG["segments"], "developers": {}}, []
    avail_files = sorted(glob.glob(os.path.join(ROOT, "data", "avail", "*_20*.json")))
    curated = {os.path.basename(p)[:-5]: json.load(open(p, encoding="utf-8")) for p in glob.glob(os.path.join(ROOT, "data", "dev_meta", "curated", "*.json"))}
    dac_key = os.environ.get("DAC_KEY")
    agg = tx_aggregates(con)                      # every transaction project once; each developer filters it (no per-name LIKE scans)
    spine = spine_links()                         # P1.3: developer entities per group + each sale's register row, from the lake
    print(spine["note"])
    dev_nums = developer_numbers(con, SEG, spine)  # DLD developer numbers per board developer (spine links + English names, whole word)
    reg_dev, reg_note = register_developers(con, spine)  # project -> registered developer numbers (sales row pairs + lake + 2026), for the veto
    all_aliases = {d: SEG["aliases"].get(d, [d.lower()]) for s in SEG["segments"] for d in s["developers"]}
    from keys import norm_number
    all_prj = q("select PROJECT_EN, coalesce(DEVELOPER_EN, ''), PROJECT_STATUS, PERCENT_COMPLETED, CNT_UNIT, AREA_EN, PROJECT_VALUE, START_DATE, "
                "COMPLETION_DATE, MASTER_PROJECT_EN, DEVELOPER_NUMBER from projects where PROJECT_EN is not null")
    if reg_note:
        print(reg_note)

    for seg in SEG["segments"]:
        for dev in seg["developers"]:
            al = SEG["aliases"].get(dev, [dev.lower()])
            pal = SEG.get("project_aliases", {}).get(dev, [])
            rec = {"segment": seg["key"], "segment_label": seg["label"], "segment_rank": seg["rank"], "aliases": al, "sources": []}
            # --- DLD project register (2026 registrations in the corpus). P1.3: by developer NUMBER - any entity the spine accepts for
            #     this developer - plus whole-word developer names ('iman' is not 'soliman') unless that number is rejected by hand
            links = spine["groups"].get(dev) or {}
            held = {n for n, l in links.items() if l["decision"] == "rejected"}
            prj = [r[:10] for r in all_prj if norm_number(r[10]) in dev_nums.get(dev, set())
                   or (norm_number(r[10]) not in held and any(wmatch(r[1], a) for a in al))]
            acc = sorted(((n, l) for n, l in links.items() if l["decision"] == "accepted"), key=lambda x: (-(x[1]["projects"] or 0), x[1]["name"] or ""))
            rec["dld_entity_links"] = [{"developer_number": int(n), "name": l["name"], "registered_projects": l["projects"], "method": l["method"],
                                        "score": l["score"]} for n, l in acc]
            active = [l["name"] for n, l in acc if (l["projects"] or 0) > 0 and l["name"]]
            rec["dld_entities"] = (active + [e for e in sorted({r[1].strip() for r in prj}) if e and e not in active])[:8]
            rec["dld_projects_2026"] = [{"project": r[0].strip(), "entity": r[1].strip(), "status": r[2], "pct_complete": num(r[3]), "units": num(r[4]), "area": r[5],
                                         "value_aed": num(r[6]), "start": str(r[7])[:10] if r[7] else None, "completion": str(r[8])[:10] if r[8] else None, "master": r[9]} for r in prj]
            if prj:
                rec["sources"].append("DLD project register (corpus of 2026 registrations)")
            # --- transactions: registered project names + seed aliases; report which aliases actually matched
            names = [p["project"] for p in rec["dld_projects_2026"]] + pal
            reg_names = {norm_name(p["project"], al) for p in rec["dld_projects_2026"]}
            # --- developer-site portfolio (data/dev_meta/<key>_portfolio.json) = the authority for WHICH projects are theirs.
            #     A name-matched row counts only when something confirms it: the portfolio, the developer's own name in the project name,
            #     a 2026 registration, the DLD project register, or the seed being the master community. Rows registered to another board
            #     developer are vetoed. The rest are listed as unconfirmed and left out of every total (15 Sep 2026; was: Imtiaz only).
            port = load_portfolio(dev)
            tx_projects, unconfirmed, vetoed, matched = match_tx_projects(dev, al, names, reg_names, port, agg, dev_nums, reg_dev,
                                                                          other_aliases=all_aliases, strict=dev in STRICT_PORTFOLIO,
                                                                          key_rows=spine["key_rows"])
            for t in tx_projects:                        # register ids for the builders downstream (board, compare, project facts)
                ids = spine["key_ids"].get(t["project"].upper())
                if ids:
                    t["project_ids"] = [c for c, _ in ids.most_common(4)]
            if port:
                rec["portfolio"] = {"source": port["source"], "fetched": port["fetched"], "count": len(port["properties"]),
                                    "properties": [{"slug": pr["slug"], "name": pr["name"], "area": pr.get("area"), "url": pr["url"], "image": pr.get("image"),
                                                    **{k: pr["facts"].get(k) for k in ("location", "structure", "storeys", "units", "handover", "payment_plans", "mix")},
                                                    "downloads_gated": [d["label"] for d in pr.get("downloads", [])]} for pr in port["properties"]],
                                    "tx_dropped_as_name_noise": [t["project"] for t in unconfirmed], "tx_unmatched_kept": []}
                rec["sources"].append("developer website portfolio register (%s, %s)" % (port["source"], port["fetched"]))
            rec["tx_2026"] = {"projects": sorted(tx_projects, key=lambda t: -t["tx"]), "transactions": sum(t["tx"] for t in tx_projects), "value_aed": sum(t["value_aed"] for t in tx_projects),
                              "areas": sorted({t["area"] for t in tx_projects if t["area"]}), "aliases_matched": matched, "aliases_unmatched": [n for n in pal if n not in matched],
                              "unconfirmed_not_counted": [{"project": t["project"], "tx": t["tx"], "matched_by": t["matched_by"], "reason": t.get("reason", "not confirmed (strict developer)")} for t in sorted(unconfirmed, key=lambda t: -t["tx"])][:50],
                              "registered_to_other_developer": [{"project": t["project"], "tx": t["tx"], "registered_to": t["registered_to"]} for t in sorted(vetoed, key=lambda t: -t["tx"])],
                              "register_veto": "applied" if reg_dev else (reg_note or "no register rows"),
                              "attribution": dict(collections.Counter(t.get("confirmed_by") for t in tx_projects).most_common())}
            if tx_projects:
                rec["sources"].append("DLD transactions Jan-Aug 2026 (confirmed name match)")
                vals = [t["median_aed_per_sqm"] for t in tx_projects if t["median_aed_per_sqm"]]
                rec["tx_2026"]["median_aed_per_sqm_across_projects"] = round(statistics.median(vals)) if vals else None
            # --- rents on the developer's counted projects only (how the stock lets); exact project names, never substrings. P1.3: plus
            #     the rents whose registered project (lk_rent_project: exact name in the rent's own area) is one of those projects' ids
            kept_names = sorted({t["project"].upper() for t in tx_projects})
            kept_ids = {c for t in tx_projects for c in t.get("project_ids", [])}
            pairs = sorted("%s|%s" % pa for pa, cid in spine["rent_ids"].items() if cid in kept_ids and pa[0] and pa[1])
            sq = lambda xs: ", ".join("'%s'" % x.replace("'", "''") for x in xs) or "''"
            rn = q("select count(*), median(try_cast(ANNUAL_AMOUNT as double)), count(*) filter (where upper(trim(PROJECT_EN)) not in (%s)) "
                   "from rents where upper(trim(PROJECT_EN)) in (%s) or PROJECT_EN || '|' || AREA_EN in (%s)" % (sq(kept_names), sq(kept_names), sq(pairs)))
            rec["rents_2026"] = {"contracts": rn[0][0], "median_annual_aed": round(rn[0][1]) if rn and rn[0][1] else None,
                                 "by_registered_project_only": rn[0][2]}
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
    open(out[:-5] + ".md", "w", encoding="utf-8").write("# Developer DNA - %s\n\nSegments and developers per Kendall's table (2 Sep 2026). DLD figures from the naj.duckdb corpus (transactions Jan-Aug 2026, 2026 project registrations). A project counts when a sale's own register row files it under one of the developer's DLD entities (the lake's project spine), or when a confirmed name match does; %s.\n\n" % (today, spine["note"]) + "\n".join(md))
    tok = env_token("INGEST_TOKEN")
    r1 = push("dev_segments", SEG, tok)
    r2 = push("dev_dna", dna, tok)
    print("developers:", len(dna["developers"]), "| dev_segments ->", r1.get("ok"), "| dev_dna ->", r2.get("ok"), "|", out)


if __name__ == "__main__":
    main()
