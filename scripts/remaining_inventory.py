"""What is left to sell - launched, sold, on the developer's sheet, rented - per project and unit type, from four registers at once.

  launched   = units the Land Department has registered for the project (units table, by rooms) - the Oqood register, i.e. the
               developer's full release; a broker pack total is a second witness when we hold one
  sold       = off-plan sales the register recorded (transactions, first sale per unit approximated by off-plan sales count),
               plus resales counted separately
  on sheet   = units the developer's latest availability sheet lists for sale (data/avail/<developer>_<date>.json)
  rented     = Ejari contracts on the project since handover (none before handover - a useful signal of handover itself)
  remaining  = launched - sold      (the register's own view)
  unaccounted = remaining - on sheet (sold but not yet registered, or held back by the developer - both worth a phone call)

Projects: every project in the availability sheets plus any project name passed on the command line.
15 Sep 2026 (digital thread P1.3/P1.4): where the lake's sheet crosswalk (register_joins.py sheet_units) links a sheet project to its registered
project, launched is counted by project_id and sold / resold / price paid by project_number - the registered project's own figures, whatever
block the sheet names ("Hado Tower A" had matched no register name at all). Everything else keeps the name matching below.
Output data/board/remaining.json {"generated", "projects": {<nkey>: {name, developer, sheet_date, by_type: {type: {launched, sold, resold, sheet, rented, remaining, unaccounted}}, totals}}}
Pushed as KV `remaining`; build_unit_mix.py folds it onto the rows.
Usage: python scripts/remaining_inventory.py [--dry] ["Project Name" ...]
"""
import duckdb, glob, json, os, re, sys, time, collections
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
from build_avail_index import env_token, push  # noqa: E402
AVAIL = os.path.join(ROOT, "data", "avail"); BOARD = os.path.join(ROOT, "data", "board")
UNITS = [f for f in sorted(glob.glob(r"C:\Dev\naj-market-pulse\data\raw_downloads\units_2026-09-04_*.csv")) if "(1)" not in f]
TX = [f for f in sorted(glob.glob(r"C:\Dev\naj-market-pulse\data\raw_downloads\transactions_2026-09-04*.csv")) if "(1)" not in f]
RENT = [f for f in sorted(glob.glob(r"C:\Dev\naj-market-pulse\data\raw_downloads\rent_contracts_*.json")) if "(1)" not in f]
TYPE = {"studio": "Studio", "1 b/r": "1 B/R", "2 b/r": "2 B/R", "3 b/r": "3 B/R", "4 b/r": "4 B/R", "5 b/r": "5 B/R", "penthouse": "PENTHOUSE", "office": "Office", "shop": "Shop", "retail": "Shop",
        "1bed room+hall": "1 B/R", "2 bed rooms+hall": "2 B/R", "3 bed rooms+hall": "3 B/R", "4 bed rooms+hall": "4 B/R", "5 bed rooms+hall": "5 B/R", "1br": "1 B/R", "2br": "2 B/R", "3br": "3 B/R", "1 br": "1 B/R", "2 br": "2 B/R", "3 br": "3 B/R"}
GENERIC = r"^(tower|towers|residences?|residence|building|podium|block|phase|[ab]|i{1,3}|[12]|by[a-z]+)*$"   # what a register name may add to a sheet name and still be the same project
# 15 Sep 2026: what a SHEET name may add to a register name - generic words only, never a block/tower/phase letter or number. With the
# letters allowed, 'Soulever Tower B' took the whole of "Soulever' By Beyond" (517 launched units) as if the block were the project.
GENERIC_SHEET = r"^(tower|towers|residences?|residence|building|podium|by[a-z]+)*$"
REGISTRY_MATCHER = "2026-09-15"   # register_fallback.MATCHER: only registry blocks made by the current matcher are carried forward


def nk(s): return re.sub(r"[^a-z0-9]", "", str(s or "").lower())
DEVTOK = set()
def canon(k):
    """drop the developer's own name from a project key ('hado by beyond tower a' -> 'hadotowera'; 'seacliff by imtiaz' -> 'seacliff')"""
    for d in DEVTOK:
        if d: k = k.replace("by" + d, "").replace(d, "")
    return k
def same(sheet_key, reg_name):
    """the register name is the sheet's project, or the sheet's project plus only generic words (Tower A, Residences, Podium, by X)"""
    raw_r, raw_s = nk(reg_name), sheet_key
    r = canon(raw_r); sheet_key = canon(sheet_key)
    if not r or not sheet_key: return False
    if r == sheet_key: return True
    # a sheet name that carries its developer ('Imtiaz Symphony Tower') only takes an unbranded register name when it is the same
    # project exactly - 15 Sep 2026: the generic-suffix rule let it absorb an unrelated 'Symphony' (767 launched units)
    sdev = {d for d in DEVTOK if d and d in raw_s}
    if sdev and not any(d in raw_r for d in sdev): return False
    if r.startswith(sheet_key) and re.fullmatch(GENERIC, r[len(sheet_key):]): return True
    if sheet_key.startswith(r) and re.fullmatch(GENERIC_SHEET, sheet_key[len(r):]): return True
    return False


def sheet_crosswalk():
    """15 Sep 2026 (digital thread P1.3/P1.4): sheet project -> its registered project by id, from the lake's crosswalk (register_joins.py
    sheet_units: accepted lk_xref sheet_project links; the sheet units matched to register units in lk_sheet_register).
    {nk(sheet name): {"project_id", "numbers", "name", "properties"}}. Empty when the lake has no crosswalk: every figure then comes from the
    names, as before. A sheet name two developers use for different projects is left to the names."""
    try:
        import lake
        lk = lake.connect(read_only=True)
        if not lk.execute("select count(*) from information_schema.tables where table_name = 'lk_sheet_register'").fetchone()[0]:
            return {}
        out, clash = {}, set()
        for fid, pid, nums, name in lk.execute("""select x.from_id, p.project_id, p.project_numbers, p.name_en from lk_xref x
                join lk_d_project p on p.canonical_id = x.to_id
                where x.job = 'sheet_project' and x.decision = 'accepted' and p.project_id is not null""").fetchall():
            k = nk(fid.split(":", 2)[2])
            if k in out and out[k]["project_id"] != pid:
                clash.add(k)
            out.setdefault(k, {"project_id": pid, "numbers": [n for n in (nums or []) if n is not None], "name": name, "properties": set()})
        for proj, prop in lk.execute("select project, property_id from lk_sheet_register where unit_decision = 'accepted'").fetchall():
            if nk(proj) in out:
                out[nk(proj)]["properties"].add(prop)
        return {k: v for k, v in out.items() if k not in clash}
    except Exception as e:
        print("  sheet crosswalk unavailable (names only):", str(e)[:100])
        return {}


def ty(s):
    s = str(s or "").strip().lower()
    if s in TYPE: return TYPE[s]
    m = re.match(r"(\d)\s*b", s)
    if "penthouse" in s: return "PENTHOUSE"
    if "duplex" in s: return "Duplex"
    if m: return m.group(1) + " B/R"
    return s.title() if s else "NA"


def sheets():
    """newest sheet per developer AND project; on the same date a hand-verified sheet beats _auto.
    15 Sep 2026 (digital thread Q9): this read only each developer's newest FILE, so a project that was not on the latest sheet
    (a developer that sends one sheet per project, or a partial resend) vanished from remaining.json - 15 Arada and 4 Fakhruddin
    projects on 15 Sep. Every sheet is read now, and each project keeps its own newest sheet and that sheet's date."""
    best = {}
    for f in sorted(glob.glob(os.path.join(AVAIL, "*.json"))):
        b = os.path.basename(f)
        if b.startswith("_") or b == "listener_health.json": continue
        m = re.match(r"([a-z_]+)_(\d{4}-\d{2}-\d{2})(_auto)?\.json$", b)
        if not m: continue
        dev, date, auto = m.group(1), m.group(2), bool(m.group(3))
        key = (dev, date); rank = (date, 0 if auto else 1)
        if key not in best or rank > best[key][0]: best[key] = (rank, f)
    per_project = {}
    for (dev, date), (rank, f) in sorted(best.items(), key=lambda kv: kv[0][1]):          # oldest first, so a newer sheet overwrites
        d = json.load(open(f, encoding="utf-8"))
        dk = nk(d.get("developer") or dev)
        for p in d.get("projects", []):
            if not p.get("p"): continue
            pk = nk(p.get("p")).replace("by" + dk, "").replace(dk, "") or nk(p.get("p"))
            per_project[(dev, pk)] = {"developer": d.get("developer") or dev, "sheet_date": d.get("sheet_date") or date, "name": p.get("p"),
                                      "units": p.get("units") or [], "completion": p.get("completion")}
    return list(per_project.values())


def main():
    dry = "--dry" in sys.argv; extra = [a for a in sys.argv[1:] if not a.startswith("--")]
    S = sheets(); names = sorted({s["name"] for s in S if s.get("name")} | set(extra))
    print("projects:", names)
    keys = {nk(n) for n in names}
    DEVTOK.update(nk(x["developer"]) for x in S if x.get("developer")); DEVTOK.update({"imtiaz", "beyond", "fakhruddin", "binghatti", "danube", "samana", "sobha", "emaar", "damac", "ellington", "omniyat", "meraas", "arada", "select", "azizi"})
    con = duckdb.connect(); t = time.time()
    XW = {k: v for k, v in sheet_crosswalk().items() if k in keys}       # P1.3/P1.4: sheet projects the register crosswalk links by id
    pids = ", ".join(str(int(v["project_id"])) for v in XW.values()) or "null"
    pnums = ", ".join(str(int(n)) for v in XW.values() for n in v["numbers"]) or "null"
    bigint = lambda c: f"try_cast(try_cast({c} as double) as bigint)"
    stems = {canon(k)[:6] for k in keys if len(canon(k)) >= 4}
    like = " or ".join(f"regexp_replace(lower(coalesce(project_name_en, '')), '[^a-z0-9]', '', 'g') like '%{k}%'" for k in stems)
    con.execute(f"create table u as select project_name_en, rooms_en, floor, {bigint('property_id')} property_id, {bigint('project_id')} pid, {bigint('building_number')} bld from read_csv_auto({json.dumps([f.replace(chr(92), '/') for f in UNITS])}, sample_size=50000, all_varchar=true, union_by_name=true) where {like} or {bigint('project_id')} in ({pids})")
    liketx = " or ".join(f"regexp_replace(lower(coalesce(building_name_en, project_name_en, '')), '[^a-z0-9]', '', 'g') like '%{k}%' or regexp_replace(lower(coalesce(project_name_en, '')), '[^a-z0-9]', '', 'g') like '%{k}%'" for k in stems)
    con.execute(f"create table tx as select coalesce(building_name_en, project_name_en) b, project_name_en p, rooms_en, reg_type_en, trans_group_en, instance_date, actual_worth, {bigint('project_number')} pn from read_csv_auto({json.dumps([f.replace(chr(92), '/') for f in TX])}, sample_size=50000, all_varchar=true, union_by_name=true) where ({liketx} or {bigint('project_number')} in ({pnums})) and trans_group_en = 'Sales'")
    src = " UNION ALL ".join(f"select project_name_en, ejari_property_sub_type_en, contract_start_date, contract_reg_type_en from read_json_auto('{f.replace(chr(92), '/')}', maximum_object_size=200000000, sample_size=20000) where {like}" for f in RENT)
    con.execute(f"create table rc as select * from ({src})")
    print(f"register pulled ({time.time()-t:.0f}s): units {con.execute('select count(*) from u').fetchone()[0]:,} | sales {con.execute('select count(*) from tx').fetchone()[0]:,} | ejari {con.execute('select count(*) from rc').fetchone()[0]:,}")
    matched = collections.defaultdict(set)
    def bucket(rows, name_ix, type_ix, val_ix=None):
        out = collections.defaultdict(lambda: collections.Counter())
        for r in rows:
            for pk in keys:
                if same(pk, r[name_ix]): out[pk][ty(r[type_ix])] += (r[val_ix] if val_ix is not None else 1); matched[pk].add(str(r[name_ix]))
        return out
    launched = bucket(con.execute("select project_name_en, rooms_en, count(*) from u group by 1,2").fetchall(), 0, 1, 2)
    sold = bucket(con.execute("select b, rooms_en, count(*) from tx where reg_type_en = 'Off-Plan Properties' group by 1,2").fetchall(), 0, 1, 2)
    resold = bucket(con.execute("select b, rooms_en, count(*) from tx where reg_type_en <> 'Off-Plan Properties' group by 1,2").fetchall(), 0, 1, 2)
    # the register's own median price paid per type (all sales of the project), so the card can show Sold @ next to Ask
    soldmed = collections.defaultdict(dict)
    for b, ty_, med, n_ in con.execute("select b, rooms_en, median(try_cast(actual_worth as double)), count(*) from tx where try_cast(actual_worth as double) > 0 group by 1,2").fetchall():
        for pk in keys:
            if same(pk, b):
                cur = soldmed[pk].get(ty(ty_))
                if cur is None or n_ > cur[1]: soldmed[pk][ty(ty_)] = (med, n_)
    lastsale = {}
    for b, d0, d1, n in con.execute("select b, min(instance_date), max(instance_date), count(*) from tx group by 1").fetchall():
        for pk in keys:
            if same(pk, b): cur = lastsale.get(pk); lastsale[pk] = (min(d0, cur[0]) if cur else d0, max(d1, cur[1]) if cur else d1, n + (cur[2] if cur else 0))
    rented = bucket(con.execute("select project_name_en, ejari_property_sub_type_en, count(*) from rc group by 1,2").fetchall(), 0, 1, 2)
    # P1.3/P1.4: where the crosswalk links the sheet's project, launched is the registered project's units by project_id, and sold, resold,
    # the price paid and the sale dates are its sales by project_number - one scope, the registered project, whatever the sheet calls a
    # block ("Hado Tower A" is on sale in Hado By Beyond). The units the sheet's own buildings hold are kept beside it. Names stay the
    # path for every project the crosswalk does not link, or that has no project number on record yet.
    by_id = {}
    for pk, x in XW.items():
        pid = int(x["project_id"])
        L = collections.Counter({ty(r): n for r, n in con.execute("select rooms_en, count(*) from u where pid = ? group by 1", [pid]).fetchall()})
        if not L:
            continue
        launched[pk] = L; matched[pk] = {x["name"]}
        blds = {b for (b,) in con.execute("select distinct bld from u where pid = ? and property_id in (select unnest(?::bigint[]))", [pid, sorted(x["properties"])]).fetchall() if b is not None} if x["properties"] else set()
        all_blds = {b for (b,) in con.execute("select distinct bld from u where pid = ? and bld is not null", [pid]).fetchall()}
        rec = {"project_id": pid, "project_numbers": x["numbers"], "register_project": x["name"], "launched_by": "project_id"}
        if blds and blds < all_blds:
            rec["sheet_buildings"] = {"buildings": sorted(blds), "launched": con.execute("select count(*) from u where pid = ? and bld in (select unnest(?::bigint[]))", [pid, sorted(blds)]).fetchone()[0]}
        if x["numbers"]:
            ns = [int(n) for n in x["numbers"]]
            q_ = lambda cond: collections.Counter({ty(r): n for r, n in con.execute(f"select rooms_en, count(*) from tx where pn in (select unnest(?::bigint[])) and {cond} group by 1", [ns]).fetchall()})
            sold[pk], resold[pk] = q_("reg_type_en = 'Off-Plan Properties'"), q_("reg_type_en <> 'Off-Plan Properties'")
            soldmed[pk] = {}
            for ty_, med, n_ in con.execute("select rooms_en, median(try_cast(actual_worth as double)), count(*) from tx where pn in (select unnest(?::bigint[])) and try_cast(actual_worth as double) > 0 group by 1", [ns]).fetchall():
                cur = soldmed[pk].get(ty(ty_))
                if cur is None or n_ > cur[1]: soldmed[pk][ty(ty_)] = (med, n_)
            ls_ = con.execute("select min(instance_date), max(instance_date), count(*) from tx where pn in (select unnest(?::bigint[]))", [ns]).fetchone()
            lastsale[pk] = ls_ if ls_ and ls_[2] else lastsale.get(pk)
            rec["sold_by"] = "project_number"
        by_id[pk] = rec
    out = {}
    for n in names:
        pk = nk(n); sh = collections.Counter(); sdate = None; dev = None; ask = collections.defaultdict(list); sqft = collections.defaultdict(list)
        for s in S:
            if nk(s["name"]) == pk:
                sdate = sdate or s["sheet_date"]; dev = dev or s["developer"]
                for u in s["units"]:
                    sh[ty(u[1])] += 1
                    if len(u) > 3 and isinstance(u[3], (int, float)) and u[3] > 0: ask[ty(u[1])].append(float(u[3]))
                    if len(u) > 2 and isinstance(u[2], (int, float)) and u[2] > 0: sqft[ty(u[1])].append(float(u[2]))
        def med(v): v = sorted(v); return v[len(v) // 2] if v else None
        types = sorted(set(launched[pk]) | set(sold[pk]) | set(sh) | set(rented[pk]), key=lambda x: (["Studio", "1 B/R", "2 B/R", "3 B/R", "4 B/R", "5 B/R", "PENTHOUSE", "Duplex", "Office", "Shop"].index(x) if x in ["Studio", "1 B/R", "2 B/R", "3 B/R", "4 B/R", "5 B/R", "PENTHOUSE", "Duplex", "Office", "Shop"] else 99, x))
        by = {}
        for tt in types:
            L, Sd, R, Sh, Rn = launched[pk].get(tt, 0), sold[pk].get(tt, 0), resold[pk].get(tt, 0), sh.get(tt, 0), rented[pk].get(tt, 0)
            rem = (L - Sd) if L else None
            by[tt] = {"launched": L or None, "sold": Sd, "resold": R, "sheet": Sh, "rented": Rn, "remaining": rem, "unaccounted": (rem - Sh) if rem is not None else None,
                      "ask_min": min(ask[tt]) if ask.get(tt) else None, "ask_med": med(ask.get(tt, [])), "ask_max": max(ask[tt]) if ask.get(tt) else None, "ask_n": len(ask.get(tt, [])),
                      "ask_sqft_med": med(sqft.get(tt, [])), "sold_med": (soldmed.get(pk, {}).get(tt) or (None, 0))[0], "sold_med_n": (soldmed.get(pk, {}).get(tt) or (None, 0))[1]}
        tot = {k: sum((v.get(k) or 0) for v in by.values()) for k in ("launched", "sold", "resold", "sheet", "rented")}
        tot["remaining"] = (tot["launched"] - tot["sold"]) if tot["launched"] else None; tot["unaccounted"] = (tot["remaining"] - tot["sheet"]) if tot["remaining"] is not None else None
        ls = lastsale.get(pk)
        out[pk] = {"name": n, "developer": dev, "sheet_date": sdate, "by_type": by, "totals": tot, "first_sale": ls and ls[0], "last_sale": ls and ls[1], "sales_all": ls and ls[2],
                   "basis": "launched = DLD units register (Oqood) · sold = DLD off-plan sales · sheet = developer availability sheet · rented = Ejari contracts", "register_names": sorted(matched.get(pk, []))}
        if pk in by_id:
            out[pk].update(by_id[pk])
            out[pk]["basis"] += " · launched and sold by register id (project %s)" % by_id[pk]["project_id"] if by_id[pk].get("sold_by") else " · launched by register id (project %s)" % by_id[pk]["project_id"]
        print(f"  {n:<32} {dev or '':<12} <- {', '.join(sorted(matched.get(pk, []))[:3])[:52]:<52} launched {tot['launched']:>4} | sold {tot['sold']:>4} | on sheet {sdate or '':<10} {tot['sheet']:>3} | rented {tot['rented']:>3} | remaining {str(tot['remaining']):>4} | unaccounted {str(tot['unaccounted']):>4}")
    # P1.4: several sheet projects on ONE registered project (Hado Tower A / B / C; Soulever + Soulever Tower B) share its launched, sold and
    # remaining - so what is unaccounted is that remaining less every one of those sheets, not only the card's own
    sib = collections.defaultdict(list)
    for pk, rec in out.items():
        if rec.get("project_id"): sib[rec["project_id"]].append(pk)
    for pid, pks in sib.items():
        if len(pks) < 2: continue
        sheet_all = collections.Counter()
        for pk in pks:
            for tt, v in out[pk]["by_type"].items(): sheet_all[tt] += v.get("sheet") or 0
        for pk in pks:
            rec = out[pk]
            for tt, v in rec["by_type"].items():
                if v.get("remaining") is not None: v["unaccounted"] = v["remaining"] - sheet_all[tt]
            if rec["totals"].get("remaining") is not None: rec["totals"]["unaccounted"] = rec["totals"]["remaining"] - sum(sheet_all.values())
            rec["sheet_siblings"] = sorted(out[p]["name"] for p in pks if p != pk)
            rec["basis"] += " · unaccounted counts the sheets of %s too" % ", ".join(rec["sheet_siblings"])
        print(f"  {out[pks[0]]['register_project']}: {len(pks)} sheet projects share it - unaccounted uses their {sum(sheet_all.values())} sheet units together")
    # a sheet project the Land Department does not know (Sharjah, or not yet registered) falls through to the MEED pipeline corpus:
    # the developer's active MEED records, matched on the project's own words - so nothing on a sheet is left without a source
    try:
        DNA = json.load(open(os.path.join(ROOT, "data", "dev_meta", "developer_dna.json"), encoding="utf-8"))["developers"]
        STOPW = {"the", "at", "by", "residences", "residence", "district", "hotels", "and", "tower", "towers", "phase", "community", "residential", "urban"}
        def toks(t): return {w for w in re.sub(r"[^a-z0-9]+", " ", (t or "").lower()).split() if len(w) >= 3 and w not in STOPW}
        hits = 0
        for pk, rec in out.items():
            if rec["totals"].get("launched"): continue
            dev = (rec.get("developer") or "").strip()
            dn = next((k for k in DNA if k.lower() == dev.lower()), None)
            act = ((DNA.get(dn) or {}).get("meed") or {}).get("active") or []
            pt = toks(rec["name"]); best = None
            words = [w for w in re.sub(r"[^a-z0-9]+", " ", rec["name"].lower()).split() if len(w) >= 3 and w not in STOPW]
            first = words[0] if words else None
            for a in act:
                tt = toks(a.get("title")); sh = pt & tt
                # 15 Sep 2026: every project word ('Soulever Tower B' ~ 'Soulever By Beyond'), or the project family - the name's first word -
                # labelled as such ('Passo Bella' ~ MEED 'Passo'); never one arbitrary shared word
                full = bool(pt) and sh == pt
                family = not full and len(pt) >= 2 and first in tt
                score = (2 if full else 1 if family else 0, len(sh))
                if score[0] and (not best or score > best[0]): best = (score, a)
            if best:
                a = best[1]; rec["pipeline"] = {"title": a.get("title"), "stage": a.get("stage"), "usd_m": a.get("usd_m"), "source": "MEED projects corpus (stored snapshot)"}
                qual = lambda t: {("%s %s" % m.groups()).lower() for m in re.finditer(r"\b(tower|block|building|phase)\s*[-']?\s*([a-z]|\d{1,2})\b", t or "", re.I)}
                if best[0][0] == 1 or (qual(rec["name"]) and not (qual(rec["name"]) & qual(a.get("title")))):
                    rec["pipeline"]["scope"] = "project family - MEED names the wider project, not '%s'" % rec["name"]
                rec["basis"] += " · pipeline = MEED (no DLD registration found)"; hits += 1
        print(f"  MEED fallback: {hits} sheet project(s) without a DLD registration matched to a MEED record")
    except Exception as e:
        print("  MEED fallback skipped:", str(e)[:80])
    # carry the fallback tier (register_fallback.py) forward: this rebuild must not erase what the registers said
    prevp = os.path.join(BOARD, "remaining.json"); prev = {}
    try: prev = json.load(open(prevp, encoding="utf-8")) if os.path.exists(prevp) else {}
    except Exception: prev = {}
    kept = stale = 0
    for pk, rec in out.items():
        old = (prev.get("projects") or {}).get(pk) or {}
        if old.get("registry") and not rec.get("registry"):
            if old["registry"].get("matcher") == REGISTRY_MATCHER: rec["registry"] = old["registry"]; kept += 1
            else: stale += 1                     # made by the one-shared-word matcher (before 15 Sep 2026): dropped, not republished
    doc = {"generated": time.strftime("%Y-%m-%d %H:%M"), "projects": out}
    for k in ("registry_note", "registry_matcher", "registry_warnings"):
        if prev.get(k) is not None: doc[k] = prev[k]
    if kept: print(f"registry blocks carried forward: {kept}")
    if stale: print(f"stale registry blocks dropped (old matcher): {stale} - run register_fallback.py to rebuild them")
    json.dump(doc, open(os.path.join(BOARD, "remaining.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    if not dry: print("push ->", push("remaining", doc, env_token("INGEST_TOKEN")))


if __name__ == "__main__":
    main()
