"""Export the truth store's decisions to what the app reads — step 4 of Kendall's order (9 Sep 2026). Runs only after graph_golden_check.py passes.

1. Canonical names   v_canonical_name (matrix + role rule) -> data/graph/canonical_names.json  {duid: {name, source, weight, was}}
                     apply_identity.py reads this and lets a matrix winner from an authoritative source (weight >= 90) replace the
                     resolver's display name; pinned names still win; nothing is deleted.
2. KV views          graph_place_cards       v_place_card (sub-community -> nearest public amenities, units, plots)
                     graph_unresolved_towers v_unresolved_towers (the tall buildings still without a name)
                     graph_identity_summary  per-district counts + gate result, for the fact panel's "who says so"
Usage: python scripts/graph_export.py [--no-push]
"""
import json, os, subprocess, sys, time
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
import duckdb
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
from build_avail_index import env_token, push  # noqa: E402
G = os.path.join(ROOT, "data", "graph"); DB = os.path.join(G, "najma.duckdb")


def rows(con, q):
    r = con.execute(q); cols = [d[0] for d in r.description]
    return [dict(zip(cols, x)) for x in r.fetchall()]


def connect_when_free(path, tries=20, wait=30):
    """DuckDB is single-writer: while the daily refresh's graph_build holds the file, wait rather than fail (up to tries x wait seconds)."""
    import time as _t
    for k in range(tries):
        try: return duckdb.connect(path, read_only=True)
        except duckdb.IOException as e:
            if "being used by another process" not in str(e) or k == tries - 1: raise
            print(f"  truth store busy (another process is writing it) - waiting {wait}s ({k+1}/{tries})"); _t.sleep(wait)


def main():
    gate = subprocess.run([sys.executable, os.path.join(HERE, "graph_golden_check.py")], capture_output=True, text=True)
    if gate.returncode != 0:
        print(gate.stdout[-1500:]); print("golden gate FAILED - nothing exported"); sys.exit(1)
    gate_line = [l for l in gate.stdout.splitlines() if l.startswith("golden gate")][-1]
    # 13 Sep 2026 (Data Spine Phase 2): the gate passed, so the checked store is published as a new DuckLake snapshot and the
    # export reads THAT, never the work-in-progress file - an export is always reproducible from a numbered version, and
    # it no longer waits on (or blocks) a builder holding najma.duckdb. A publish the contract refuses exports nothing.
    import lake
    if lake.publish(note="graph_export after the golden gate") != 0:
        print("lake publish HELD - nothing exported"); sys.exit(1)
    con = lake.connect(); now = time.strftime("%Y-%m-%dT%H:%M:%S")
    can = rows(con, "select duid, canonical_name, canonical_source, weight, current_name, current_source from v_canonical_name where differs and canonical_name is not null")
    canon = {"generated": now, "gate": gate_line, "n": len(can), "rule": "matrix winner over ACCEPTED/MANUALLY_VERIFIED BUILDING_NAME claims; place sources excluded; applied by apply_identity when weight >= 90",
             "items": {r["duid"]: {"name": r["canonical_name"], "source": r["canonical_source"], "weight": r["weight"], "was": r["current_name"], "was_source": r["current_source"]} for r in can}}
    json.dump(canon, open(os.path.join(G, "canonical_names.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    cards = rows(con, "select * from v_place_card"); towers = rows(con, "select * from v_unresolved_towers")
    summ = rows(con, "select district, count(*) buildings, count(display_name) named, sum(case when display_role='BUILDING_NAME' then 1 else 0 end) building_named, sum(case when height_m>=60 and display_name is null then 1 else 0 end) unnamed_tall from building group by district order by buildings desc")
    conflicts = con.execute("select count(*) from v_conflicting_names").fetchone()[0]; aliases = con.execute("select count(*) from alias").fetchone()[0]
    con.close()
    views = {"graph_place_cards": {"generated": now, "n": len(cards), "items": cards},
             "graph_unresolved_towers": {"generated": now, "n": len(towers), "items": towers},
             "graph_identity_summary": {"generated": now, "gate": gate_line, "canonical_changes": len(can), "conflicting_names": conflicts, "aliases": aliases, "districts": summ}}
    for k, v in views.items():
        json.dump(v, open(os.path.join(G, f"{k}.json"), "w", encoding="utf-8"), ensure_ascii=False, default=str)
    print(f"{gate_line} | canonical changes {len(can)} | place cards {len(cards)} | unresolved towers {len(towers)} | conflicts {conflicts} | aliases {aliases}")
    if "--no-push" in sys.argv: return
    tok = env_token("INGEST_TOKEN")
    for k, v in views.items():
        r = push(k, json.loads(json.dumps(v, default=str)), tok); print(f"  {k} -> {r.get('ok')} {r.get('bytes', '')}")


if __name__ == "__main__":
    main()
