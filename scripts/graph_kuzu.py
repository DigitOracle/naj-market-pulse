"""Kùzu projection of the truth store — Kendall's step 4 (9 Sep 2026), run only after graph_golden_check.py passes.

DuckDB (data/graph/najma.duckdb) stays the truth store. This script projects its gold tables into a Kùzu property graph
(data/graph/najma.kuzu) so the questions the app asks ("homes within 400 m of a public beach", "what does this developer
hold in Creek Harbour", "which towers on this waterfront have no name") are one Cypher pattern each instead of a join chain.
Nothing is written back: rebuild from scratch on every run, never edit the projection by hand.

Nodes:  District, Building, SubCommunity, Plot, Project, Developer, Amenity, WaterBody
Edges:  IN_DISTRICT (Building|SubCommunity|Plot|Amenity -> District), NEAREST (SubCommunity -> Amenity: kind, relation, distance_m, access),
        WATERFRONT (Building -> WaterBody: cls, distance_m), DEVELOPED_BY (Project -> Developer)
Usage:  python scripts/graph_kuzu.py            builds and runs the smoke queries, writes data/graph/kuzu_stats.json
"""
import json, os, shutil, sys, time
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
import duckdb, kuzu
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, ".."))
G = os.path.join(ROOT, "data", "graph"); DB = os.path.join(G, "najma.duckdb"); KZ = os.path.join(G, "najma.kuzu"); TMP = os.path.join(G, "_parquet")

# (kuzu table, kuzu DDL columns, duckdb select) — the select's column order is the DDL's column order; integers cast to BIGINT for Kùzu INT64
NODES = [
    ("District", "slug STRING, name STRING, corridor STRING, lon DOUBLE, lat DOUBLE, subs INT64, plots INT64, named INT64, PRIMARY KEY(slug)",
     "select slug, name, corridor, lon, lat, cast(subs as bigint), cast(plots as bigint), cast(named as bigint) from district where slug is not null"),
    ("Building", "duid STRING, district STRING, footprint_i INT64, lon DOUBLE, lat DOUBLE, height_m DOUBLE, storeys INT64, display_name STRING, display_role STRING, official_name STRING, grade STRING, name_source STRING, confidence DOUBLE, developer STRING, kind STRING, PRIMARY KEY(duid)",
     "select duid, district, cast(footprint_i as bigint), lon, lat, height_m, cast(storeys as bigint), display_name, display_role, official_name, grade, name_source, cast(confidence as double), developer, kind from building where duid is not null"),
    ("SubCommunity", "sub_id STRING, name STRING, district STRING, lon DOUBLE, lat DOUBLE, radius_m DOUBLE, plots INT64, units INT64, buildings INT64, PRIMARY KEY(sub_id)",
     "select sub_id, name, district, lon, lat, radius_m, cast(plots as bigint), cast(units as bigint), cast(buildings as bigint) from sub_community where sub_id is not null"),
    ("Plot", "plot_no STRING, name STRING, district STRING, master STRING, parcel_id STRING, units INT64, area_sqm DOUBLE, lon DOUBLE, lat DOUBLE, PRIMARY KEY(plot_no)",
     "select plot_no, any_value(name), any_value(district), any_value(master), any_value(parcel_id), cast(any_value(units) as bigint), any_value(area_sqm), any_value(lon), any_value(lat) from plot where plot_no is not null group by plot_no"),
    ("Project", "project_key STRING, name STRING, district STRING, footprint_i INT64, status STRING, total_units INT64, floors INT64, developer STRING, master_project STRING, register_aed_sqm DOUBLE, PRIMARY KEY(project_key)",
     "select project_key, name, district, cast(footprint_i as bigint), status, cast(total_units as bigint), cast(floors as bigint), developer, master_project, register_aed_sqm from project where project_key is not null"),
    ("Developer", "dev_key STRING, name STRING, segment STRING, tier STRING, portfolio_count INT64, PRIMARY KEY(dev_key)",
     "select dev_key, name, segment, tier, cast(portfolio_count as bigint) from developer where dev_key is not null"),
    ("Amenity", "amenity_id STRING, kind STRING, name STRING, lon DOUBLE, lat DOUBLE, source STRING, access STRING, detail STRING, district STRING, PRIMARY KEY(amenity_id)",
     "select amenity_id, kind, name, lon, lat, source, access, detail, district from amenity where amenity_id is not null"),
    ("WaterBody", "body_id INT64, name STRING, named BOOLEAN, cls STRING, area_ha DOUBLE, lon DOUBLE, lat DOUBLE, district STRING, PRIMARY KEY(body_id)",
     "select cast(body_id as bigint), name, named, cls, area_ha, lon, lat, district from water_body where body_id is not null"),
]
RELS = [
    ("IN_DISTRICT", "FROM Building TO District", "b_district",
     "select b.duid, d.slug from building b join district d on d.slug=b.district"),
    ("IN_DISTRICT", "FROM SubCommunity TO District", "s_district",
     "select s.sub_id, d.slug from sub_community s join district d on d.slug=s.district"),
    ("IN_DISTRICT", "FROM Plot TO District", "p_district",
     "select p.plot_no, d.slug from (select plot_no, any_value(district) district from plot group by plot_no) p join district d on d.slug=p.district"),
    ("IN_DISTRICT", "FROM Amenity TO District", "a_district",
     "select a.amenity_id, d.slug from amenity a join district d on d.slug=a.district"),
    ("NEAREST", "FROM SubCommunity TO Amenity, kind STRING, relation STRING, distance_m INT64, access STRING", "nearest",
     "select e.sub_id, e.amenity_id, e.kind, e.relation, cast(e.distance_m as bigint), e.access from sub_community_amenity e join sub_community s on s.sub_id=e.sub_id join amenity a on a.amenity_id=e.amenity_id"),
    ("WATERFRONT", "FROM Building TO WaterBody, cls STRING, distance_m DOUBLE", "waterfront",
     "select w.duid, cast(w.body_id as bigint), w.cls, w.distance_m from building_waterfront w join building b on b.duid=w.duid join water_body wb on wb.body_id=w.body_id"),
    ("DEVELOPED_BY", "FROM Project TO Developer", "developed_by",
     "select pd.project_key, pd.dev_key from project_developer pd join project p on p.project_key=pd.project_key join developer d on d.dev_key=pd.dev_key"),
]
SMOKE = [
    ("homes within 400 m of a PUBLIC beach (sub-communities)",
     "MATCH (s:SubCommunity)-[r:NEAREST {kind:'beach', relation:'NEAREST_PUBLIC'}]->(a:Amenity) WHERE r.distance_m <= 400 RETURN s.name, a.name, r.distance_m ORDER BY r.distance_m LIMIT 5"),
    ("Chelsea Residences 2: nearest water vs nearest public beach",
     "MATCH (s:SubCommunity)-[r:NEAREST {kind:'beach'}]->(a:Amenity) WHERE lower(s.name) CONTAINS 'chelsea residences 2' RETURN r.relation, a.name, a.access, r.distance_m ORDER BY r.relation"),
    ("tall waterfront buildings with no name (top 5 by height)",
     "MATCH (b:Building)-[w:WATERFRONT]->(wb:WaterBody) WHERE b.display_name IS NULL AND b.height_m >= 100 AND w.distance_m <= 150 RETURN b.duid, b.district, b.height_m, wb.name, w.distance_m ORDER BY b.height_m DESC LIMIT 5"),
    ("Emaar projects per district",
     "MATCH (p:Project)-[:DEVELOPED_BY]->(d:Developer {dev_key:'emaar'}) RETURN p.district, count(*) AS n ORDER BY n DESC LIMIT 5"),
    ("districts by named share",
     "MATCH (b:Building)-[:IN_DISTRICT]->(d:District) RETURN d.slug, count(b) AS buildings, sum(CASE WHEN b.display_name IS NULL THEN 0 ELSE 1 END) AS named ORDER BY buildings DESC LIMIT 5"),
]


def main():
    t0 = time.time()
    if os.path.exists(KZ):
        shutil.rmtree(KZ) if os.path.isdir(KZ) else os.remove(KZ)
    for ext in (".wal", ".lock"):
        if os.path.exists(KZ + ext): os.remove(KZ + ext)
    os.makedirs(TMP, exist_ok=True)
    src = duckdb.connect(DB, read_only=True); stats = {"generated": time.strftime("%Y-%m-%dT%H:%M:%S"), "nodes": {}, "rels": {}, "smoke": []}
    for name, ddl, sel in NODES:
        p = os.path.join(TMP, f"node_{name}.parquet").replace("\\", "/")
        src.execute(f"copy ({sel}) to '{p}' (format parquet)")
        stats["nodes"][name] = src.execute(f"select count(*) from read_parquet('{p}')").fetchone()[0]
    for name, ddl, tag, sel in RELS:
        p = os.path.join(TMP, f"rel_{tag}.parquet").replace("\\", "/")
        src.execute(f"copy ({sel}) to '{p}' (format parquet)")
        stats["rels"][tag] = src.execute(f"select count(*) from read_parquet('{p}')").fetchone()[0]
    src.close()
    db = kuzu.Database(KZ); con = kuzu.Connection(db)
    for name, ddl, _ in NODES:
        con.execute(f"CREATE NODE TABLE {name}({ddl})")
        con.execute(f"COPY {name} FROM '{os.path.join(TMP, f'node_{name}.parquet').replace(chr(92), '/')}'")
    # one rel table per name; IN_DISTRICT is a multi-pair rel table (Kùzu: FROM A TO B, FROM C TO B ...)
    groups = {}
    for name, ddl, tag, _ in RELS: groups.setdefault(name, []).append((ddl, tag))
    for name, items in groups.items():
        pairs = [d.split(",")[0].strip() for d, _ in items]; props = ",".join(d.split(",", 1)[1] for d, _ in items if "," in d)
        con.execute(f"CREATE REL TABLE {name}({', '.join(pairs)}{(', ' + props) if props else ''})")
        for ddl, tag in items:
            frm = ddl.split("FROM")[1].split("TO")[0].strip(); to = ddl.split("TO")[1].split(",")[0].strip()
            con.execute(f"COPY {name} FROM '{os.path.join(TMP, f'rel_{tag}.parquet').replace(chr(92), '/')}' (from='{frm}', to='{to}')")
    for label, q in SMOKE:
        try:
            r = con.execute(q); rows = []
            while r.has_next(): rows.append([str(x) for x in r.get_next()])
            stats["smoke"].append({"q": label, "rows": rows}); print(f"  {label}:"); [print("     ", " | ".join(x)) for x in rows]
        except Exception as e:
            stats["smoke"].append({"q": label, "error": str(e)[:200]}); print(f"  {label}: ERROR {str(e)[:160]}")
    con.close(); db.close(); shutil.rmtree(TMP, ignore_errors=True)
    stats["seconds"] = round(time.time() - t0, 1)
    json.dump(stats, open(os.path.join(G, "kuzu_stats.json"), "w", encoding="utf-8"), indent=1)
    print("nodes:", stats["nodes"]); print("rels:", stats["rels"]); print(f"-> {KZ} in {stats['seconds']} s")


if __name__ == "__main__":
    main()
