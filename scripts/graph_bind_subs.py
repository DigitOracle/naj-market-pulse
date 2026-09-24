"""graph_bind_subs.py -- bind every DLD sub-community card to the buildings it stands on, in the truth store, the same way the MAP tab
already places it: the card's point and radius (Kendall, 12 Sep 2026: "same methodology, always cross-checking with the duckdb").

For each row of sub_community (1,834 cards: point, radius_m, buildings, units) take the buildings of the same district whose point
lies within radius_m; keep real buildings (height >= 12 m) when there are any, otherwise whatever stands there (villa clusters); if the
card says N buildings and more than 3N qualify, keep the tallest 3N. Lands:
  sub_community_building   (sub_id, duid, footprint_i, district, dist_m, height_m, rank, method)
  evidence                 building.sub_community = card name, source dld_project, role LOCATION, DISCOVERED (geometry, not a register fact)
  KV img_subbind_<slug>    {"<card name>": [footprint_i, ...]}  -- what the twin highlights when a card is tapped (v121)
  data/audit/sub_bindings_result.md

    python scripts/graph_bind_subs.py [--no-push] [slug ...]
"""
import hashlib, json, os, sys, time
import duckdb

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, ".."))
DB = os.path.join(ROOT, "data", "graph", "najma.duckdb"); AUD = os.path.join(ROOT, "data", "audit"); os.makedirs(AUD, exist_ok=True)
NOW = time.strftime("%Y-%m-%dT%H:%M:%S"); RUN = time.strftime("%Y%m%d-%H%M%S") + "-subbind"; SCHEMA = "1.2"; RESOLVER = "identity-2026-09-08-rolerule"
sys.path.insert(0, HERE)
from build_avail_index import env_token, push
PUSH = "--push" in sys.argv and "--no-push" not in sys.argv; ONLY = [a for a in sys.argv[1:] if not a.startswith("--")]


def connect_writer(path, tries=20, wait=30):
    for k in range(tries):
        try: return duckdb.connect(path)
        except duckdb.IOException as e:
            if "being used by another process" not in str(e) or k == tries - 1: raise
            print(f"  truth store busy - waiting {wait}s ({k+1}/{tries})"); time.sleep(wait)


def eid(entity_id, attribute, value, source, rec):
    return hashlib.sha1(f"{entity_id}|{attribute}|{value}|{source}|{rec}".encode("utf-8")).hexdigest()[:24]


def main():
    t0 = time.time(); con = connect_writer(DB)
    con.execute("delete from source_authority where source_id = 'dld_project' and attribute = 'sub_community'")
    con.execute("insert into source_authority values ('dld_project','sub_community',80)")
    where = ("and s.district in (" + ",".join("'" + x + "'" for x in ONLY) + ")") if ONLY else ""
    con.execute(f"""create or replace table sub_community_building as
        with cand as (
            select s.sub_id, s.name as sub_name, s.district, s.buildings as card_buildings, b.duid, b.footprint_i, b.height_m,
                   sqrt(power((b.lat - s.lat) * 111320, 2) + power((b.lon - s.lon) * 100800, 2)) as dist_m
            from sub_community s join building b on b.district = s.district
            where s.lon is not null and b.lon is not null {where}
              and abs(b.lat - s.lat) * 111320 <= coalesce(s.radius_m, 150) and abs(b.lon - s.lon) * 100800 <= coalesce(s.radius_m, 150)),
        inr as (select c.* from cand c join sub_community s using (sub_id) where c.dist_m <= coalesce(s.radius_m, 150)),
        tall as (select *, count(*) filter (where coalesce(height_m, 0) >= 12) over (partition by sub_id) as n_tall from inr),
        keep as (select * from tall where n_tall = 0 or coalesce(height_m, 0) >= 12),
        ranked as (select *, row_number() over (partition by sub_id order by coalesce(height_m, 0) desc, dist_m) as rank from keep)
        select sub_id, sub_name, district, duid, footprint_i, round(dist_m, 1) as dist_m, height_m, rank,
               case when n_tall = 0 then 'within card radius (low-rise, any height)' else 'within card radius, >= 12 m' end as method
        from ranked where card_buildings is null or card_buildings <= 0 or rank <= greatest(3 * card_buildings, 3)""")
    n = con.execute("select count(*), count(distinct sub_id), count(distinct duid) from sub_community_building").fetchone()
    tot = con.execute(f"select count(*) from sub_community s where s.lon is not null {where}").fetchone()[0]
    print(f"  bound: {n[1]:,} of {tot:,} cards -> {n[0]:,} building links ({n[2]:,} distinct buildings) in {round(time.time()-t0)} s")
    # evidence (append-only, DISCOVERED: a geometry inference, never a name)
    rows = con.execute("select duid, sub_name, sub_id, dist_m, method from sub_community_building").fetchall()
    ev = [(eid(d, "sub_community", nm, "dld_project", sid), RUN, "building", d, "sub_community", nm, "LOCATION", "dld_project", sid, m, 0.7, None, float(dist), True, NOW, "DISCOVERED", SCHEMA, RESOLVER, NOW[:10], None) for d, nm, sid, dist, m in rows]
    con.execute("create or replace temp table ev_new as select * from evidence limit 0")
    con.executemany("insert into ev_new values (" + ",".join("?" * 20) + ")", ev)
    added = con.execute("insert into evidence select n.* from ev_new n where not exists (select 1 from evidence e where e.evidence_id = n.evidence_id)").fetchone()[0]
    print(f"  evidence: {len(ev):,} prepared, {added:,} new")
    con.execute("""create or replace view v_sub_community_buildings as
        select s.sub_id, s.name as sub_community, s.district, s.units, s.buildings as card_buildings, count(x.duid) as bound_buildings,
               max(x.height_m) as tallest_m, list(x.footprint_i order by x.rank) as footprints
        from sub_community s left join sub_community_building x using (sub_id) group by 1, 2, 3, 4, 5""")
    per = con.execute("select district, count(*), count(*) filter (where bound_buildings > 0) from v_sub_community_buildings group by 1 order by 1").fetchall()
    # KV per district
    tok = env_token("INGEST_TOKEN") if PUSH else None; pushed = 0
    for d, cards, bound in per:
        if ONLY and d not in ONLY: continue
        m = {name: fps for name, fps in con.execute("select sub_community, footprints from v_sub_community_buildings where district = ? and bound_buildings > 0", [d]).fetchall()}
        if PUSH and m:
            try: r = push("subbind_" + d, {"district": d, "built": NOW, "cards": m}, tok); pushed += 1 if r.get("ok") else 0
            except Exception as ex: print(f"  push subbind_{d}: {str(ex)[:80]}")
    with open(os.path.join(AUD, "sub_bindings_result.md"), "w", encoding="utf-8") as f:
        f.write(f"# Sub-community -> building bindings ({time.strftime('%d %b %Y %H:%M')})\n\nPrepared for Dr. Digital Abbot. Run {RUN}. Cards bound {n[1]:,} of {tot:,}; links {n[0]:,}; KV registers pushed {pushed}.\n\n| District | Cards | Bound |\n|---|---|---|\n")
        for d, cards, bound in per: f.write(f"| {d} | {cards} | {bound} |\n")
    try:
        rc = [c[0] for c in con.execute("describe run").fetchall()]
        vals = {"run_id": RUN, "started": NOW, "finished": time.strftime("%Y-%m-%dT%H:%M:%S"), "script": "graph_bind_subs.py", "label": "sub-community geometry bindings", "notes": f"{n[0]} links, {added} evidence", "schema_version": SCHEMA, "resolver_version": RESOLVER}
        use = [c for c in rc if c in vals]; con.execute(f"insert into run ({', '.join(use)}) values ({', '.join('?' * len(use))})", [vals[c] for c in use])
    except Exception as ex: print("  run row skipped:", str(ex)[:80])
    con.close(); print(f"done: {pushed} district registers pushed · data/audit/sub_bindings_result.md · now: python scripts/graph_golden_check.py")


if __name__ == "__main__":
    main()
