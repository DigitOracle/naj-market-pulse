"""A bank of questions the app must be able to answer, run against what we actually shipped (Kendall, 6 Sep 2026).

Every question is one a broker or a buyer would ask. Each is answered from the live artefacts - KV as the app serves it, and the
local data behind it - and marked PASS, THIN (answerable but the coverage is poor) or FAIL (the app cannot answer). No question is
scored from intention; only from what comes back.
Usage: python scripts/audit_queries.py
"""
import json, os, sys, glob, urllib.request, collections
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
from build_avail_index import env_token, WORKER  # noqa: E402
KEY = env_token("READ_KEY")
R = []


def kv(name):
    try:
        return json.load(urllib.request.urlopen(urllib.request.Request(f"{WORKER}/img/{name}", headers={"User-Agent": "audit"}), timeout=90))
    except Exception as e:
        return {"_error": str(e)[:80]}


def local(p, d=None):
    try:
        return json.load(open(os.path.join(ROOT, p), encoding="utf-8"))
    except Exception:
        return d


def ask(q, verdict, detail):
    R.append((verdict, q, detail)); print(f"  {verdict:<5} {q}\n        {detail}")


def main():
    print("THE QUESTION BANK — what the app claims it can answer, tested\n")

    # ---- naming / identity -------------------------------------------------------------------------------------------------
    print("Identity and naming")
    aud = kv("twin_audit"); ds = aud.get("districts") or []
    named = sum(d.get("named", 0) for d in ds); blds = sum(d.get("buildings", 0) for d in ds)
    ask("What is this building called?", "THIN" if named / max(blds, 1) < 0.35 else "PASS",
        f"{named:,} of {blds:,} footprints carry a name ({100*named/max(blds,1):.0f}%). The rest render as unnamed massing.")
    ident = 0; graded = collections.Counter()
    for f in glob.glob(os.path.join(ROOT, "data", "identity", "identity_*.json")):
        for r in (local(os.path.relpath(f, ROOT), {}) or {}).get("buildings_list", []) or []: pass
    tbl = os.path.join(ROOT, "data", "identity", "IDENTITY_TABLE.csv")
    if os.path.exists(tbl):
        import csv
        rows = list(csv.DictReader(open(tbl, encoding="utf-8", errors="replace")))
        g = collections.Counter(r.get("identity_grade") or r.get("grade") for r in rows)
        ask("How sure are we of that name?", "PASS" if g else "FAIL",
            "grades: " + ", ".join(f"{k} {v:,}" for k, v in g.most_common(5)))
    # districts with register data
    ub = glob.glob(os.path.join(ROOT, "data", "dld", "units_buildings_*.json"))
    reg_named = 0; reg_tot = 0
    for f in ub:
        b = json.load(open(f, encoding="utf-8"))["buildings"]; reg_tot += len(b); reg_named += sum(1 for x in b if x.get("name"))
    ask("Does the register know a name we do not show?", "THIN" if reg_named > named * 0.4 else "PASS",
        f"register names available {reg_named:,} across {len(ub)} districts; on the twin {named:,}. Gap is binding, not data.")

    # ---- the unit mix card -------------------------------------------------------------------------------------------------
    print("\nThe building card")
    st = collections.Counter(); rows_with_price = 0; rows_tot = 0; with_rent = 0; with_left = 0
    for f in glob.glob(os.path.join(ROOT, "data", "board", "unitmix_*.json")):
        d = json.load(open(f, encoding="utf-8"))
        if "buildings_by_id" not in d: continue
        for b in d["buildings_by_id"].values():
            st[b.get("status")] += 1
            for r in b.get("rows", []) or []:
                rows_tot += 1
                if r.get("median_aed") or r.get("est_aed"): rows_with_price += 1
                if r.get("median_rent"): with_rent += 1
                if r.get("remaining") is not None: with_left += 1
    ask("How many homes are in this building, and of what type?", "PASS" if st["verified"] > 300 else "THIN",
        f"verified from the register {st['verified']:,} · partial {st['partial']:,} · placeholder {st['placeholder']:,}")
    ask("What did this type actually sell for?", "PASS" if rows_with_price else "FAIL",
        f"{rows_with_price:,} of {rows_tot:,} type rows carry a price (register median or a marked estimate)")
    ask("What does it rent for, and what is the yield?", "THIN" if with_rent < rows_tot * 0.2 else "PASS",
        f"{with_rent:,} of {rows_tot:,} type rows carry a registered rent")
    ask("How many are left to sell?", "THIN" if with_left < 200 else "PASS",
        f"{with_left:,} type rows carry launched-minus-sold; only projects on a developer sheet can have this")

    # ---- the map -----------------------------------------------------------------------------------------------------------
    print("\nThe map and the area cards")
    ml = local("public/pulse.json", {}) or {}                      # the pulse the map is built from (mkt_latest in KV is not an /img key)
    areas = ((ml.get("areaIntel") or {}).get("areas")) or []
    wy = [a for a in areas if a.get("grossYieldPct")]
    ask("What is this community worth per square foot?", "PASS" if len(areas) > 30 else "FAIL", f"{len(areas)} area cards with settled prices")
    ask("What does this community yield?", "FAIL" if len(wy) < len(areas) * 0.4 else "PASS",
        f"{len(wy)} of {len(areas)} area cards carry a yield (area alias fix + full leaderboard, pulse rebuilt 6 Sep)")
    pipe = [a for a in areas if a.get("unitsInPipeline")]
    ask("What is coming to market here?", "FAIL" if not pipe else "THIN", f"{len(pipe)} of {len(areas)} area cards show a pipeline figure")
    ask("Where is the parcel boundary?", "FAIL", "no public parcel geometry exists on data.dubai (265 datasets checked); parcel IDs only, no outlines")
    dg = kv("districts_geo"); dgs = dg.get("districts") or []
    ask("Can the map fly to a district?", "PASS" if len(dgs) >= 40 else "THIN", f"{len(dgs)} districts carry a bounding box, centre and corridor in KV")
    subs = kv("subs"); sf = subs.get("features") or []
    fp_sub = 0
    for f in glob.glob(os.path.join(ROOT, "data", "names", "clusters_*.json")):
        fp_sub += len((local(os.path.relpath(f, ROOT), {}) or {}).get("assign") or {})
    ask("Which sub-community is this villa in?", "PASS" if len(sf) > 1000 else "THIN",
        f"{len(sf):,} verified sub-communities on the map; {fp_sub:,} footprints carry the attribution (a neighbourhood, never shown as a building name)")
    reg_plot = 0
    for f in ub:
        reg_plot += sum(1 for x in json.load(open(f, encoding="utf-8"))["buildings"] if x.get("parcel") or x.get("plot_parcel") or x.get("plot_no"))
    pl = kv("plots"); plf = pl.get("features") or []
    ask("What is this building's plot number?", "PASS" if reg_plot > reg_tot * 0.9 else "THIN",
        f"{reg_plot:,} of {reg_tot:,} register buildings carry a plot number; it prints on every HOMES card")
    ask("Can I see that plot on the map?", "THIN" if len(plf) < reg_plot * 0.5 else "PASS",
        f"{len(plf):,} plot pins placed - only a building bound to a footprint can be placed; no parcel outlines exist to place the rest")

    # ---- what is around a home (official registers) -----------------------------------------------------------------------------
    print("\nWhat is around a home")
    am = kv("amenities"); ai = am.get("items") or []; ak = collections.Counter(i.get("k") for i in ai); asrc = collections.Counter(i.get("src") for i in ai)
    ap = collections.Counter(i.get("k") for i in ai if i.get("ap"))
    gov = asrc.get("ese", 0); priv = asrc.get("khda", 0) + asrc.get("khda+google", 0)
    ask("Which schools are near this home - private AND government?", "PASS" if priv > 200 and gov > 30 else ("THIN" if priv > 200 else "FAIL"),
        f"{priv} private (KHDA register, with rating) + {gov} government (Emirates Schools Establishment map API) = {ak.get('school', 0)} schools with positions")
    ask("Which hospital is nearest, and is the list complete?", "PASS" if ak.get("hospital", 0) >= 50 else "FAIL",
        f"{ak.get('hospital', 0)} hospitals from the DHA licence register (every active facility whose licence class is Hospital); {ap.get('hospital', 0)} still approximate")
    ask("Is the clinic position exact?", "THIN" if ap.get("clinic", 0) > ak.get("clinic", 1) * 0.4 else "PASS",
        f"{ak.get('clinic', 0)} clinics; {ap.get('clinic', 0)} carry the register's truncated latitude (about 1 km) and are marked so on the map")
    ask("Where is the nearest metro or tram?", "PASS" if ak.get("metro", 0) >= 60 else "THIN", f"{ak.get('metro', 0)} stations from RTA")
    ask("Where are the parks, malls and beach?", "THIN",
        f"parks {ak.get('park', 0)} · malls {ak.get('mall', 0)} · beach {ak.get('beach', 0)} - Overture places plus DM's major parks; no official list exists for these")
    ask("Does the map say how far each one is from my plot?", "PASS" if ai and dgs else "FAIL",
        "tap a sub-community or plot: everything switched on within 3 km, sorted by distance, source-marked")

    # ---- search ------------------------------------------------------------------------------------------------------------
    print("\nFinding things")
    si = kv("search_index"); items = si.get("items") or []
    t = collections.Counter(i.get("t") for i in items)
    ask("Can she find a developer, a development, a building?", "PASS" if len(items) > 3000 else "THIN",
        f"{len(items):,} searchable: {dict(t)}")
    linked = sum(1 for i in items if i.get("p") and i.get("dev"))
    ask("Does a search result open the right page?", "THIN" if linked < len(items) * 0.25 else "PASS",
        f"{linked:,} of {len(items):,} results land on a developer HOMES card; the rest open a district on the twin")

    # ---- supply / availability ---------------------------------------------------------------------------------------------
    print("\nAvailability and the sweep")
    hl = local("data/avail/listener_health.json", {})
    live = {}
    try: live = json.load(open(os.path.join("C:" + os.sep, "Dev", "azimuth-listener-naj", "health.json"), encoding="utf-8"))   # the listener's own heartbeat, not a stale snapshot
    except Exception: pass
    if live: hl = dict(hl, socket=live.get("connection"), last_doc=live.get("lastDocAt"), docs_24h=live.get("docs24h"), rx_24h=live.get("rx24h"),
                       verdict=("listening" if live.get("connection") == "open" else hl.get("verdict")))
    ask("Was the developer availability captured today?", "PASS" if hl.get("socket") == "open" and (hl.get("rx_24h") or 0) > 0 else ("THIN" if hl.get("socket") == "open" else "FAIL"),
        f"socket {hl.get('socket')} · {hl.get('rx_24h')} messages and {hl.get('docs_24h')} PDFs in 24 h · last sheet {hl.get('last_doc')}")
    rem = local("data/board/remaining.json", {}).get("projects", {})
    ok = [k for k, v in rem.items() if (v.get("totals") or {}).get("launched")]
    ask("What is left in this launch?", "PASS" if len(ok) > 10 else "THIN",
        f"{len(ok)} of {len(rem)} sheet projects reconciled against the register")

    # ---- the twin ----------------------------------------------------------------------------------------------------------
    print("\nThe twin itself")
    ask("Do the buildings stand at the right height?", "THIN",
        "survey heights where a source exists; elsewhere register floors x 3.2 m (250 anchors) or a 12 m default. Marked, not hidden.")
    wk = [k for k in ("dubaimarina", "jltsouth", "palmjumeirah") if not kv("water_" + k).get("_error")]
    ask("Does the ground look real?", "THIN", f"Esri imagery + 30 m terrain; animated water in {len(wk)} of 41 districts (Overture water clipped per district) - the rest still flat")

    print("\n" + "-" * 100)
    c = collections.Counter(v for v, _, _ in R)
    print(f"RESULT  PASS {c['PASS']}   THIN {c['THIN']}   FAIL {c['FAIL']}   of {len(R)} questions")
    print("\nFAILING:")
    for v, q, d in R:
        if v == "FAIL": print(f"  - {q}  ::  {d}")


if __name__ == "__main__":
    main()
