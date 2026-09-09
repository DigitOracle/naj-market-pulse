"""The truth store: one DuckDB database with node tables, edge tables and an append-only evidence ledger, loaded from every file the
pipeline already produces (Kendall, 8 Sep 2026: "Make DuckDB the truth store now ... every script writes to the same place").

  data/graph/najma.duckdb
    NODES   source, district, sub_community, plot, building, project, developer, sheet_project, amenity, water_body
    EDGES   building_in_district, building_waterfront, building_developer, project_developer, sheet_project_register,
            sub_community_amenity (nearest of each kind, with the measurement), amenity_in_district
    LEDGER  evidence (append-only: never updated, never deleted; new runs append with a new run_id; status marks supersession)
    POLICY  source_authority (per attribute, per source: the matrix, not a ranking), golden (the test set every resolver change must pass)
    VIEWS   v_building_identity, v_unresolved_towers, v_conflicting_names, v_place_card

Inputs (all existing): data/identity/resolved/<slug>.json (buildings + evidence), data/board/{districts_geo,subs,plots,unitmix_projects_slim,
map_prices,remaining,amenities,water_register,beaches,parks,beach_poll_08sep2026,park_poll_DRAFT_08sep2026,amenity_truth_audit}.json,
data/enrich/waterfront.json, data/board/board_devs.json. Nothing is modified; this only reads them.

Every run: nodes/edges are rebuilt (they are derived); the ledger is appended (it is history). schema_version and run_id stamp every row.
Usage: python scripts/graph_build.py [--fresh]   (--fresh deletes the database first, ledger included - only for a schema change)
"""
import glob, json, math, os, sys, time, uuid
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
import duckdb
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, ".."))
BOARD = os.path.join(ROOT, "data", "board"); IDENT = os.path.join(ROOT, "data", "identity", "resolved"); ENRICH = os.path.join(ROOT, "data", "enrich")
GDIR = os.path.join(ROOT, "data", "graph"); DB = os.path.join(GDIR, "najma.duckdb")
SCHEMA = "1.1"; RESOLVER = "identity-2026-09-08-rolerule"
PLACE_SOURCES = {"overture_place", "places", "google", "google_places"}   # businesses: tenants and amenities, never a building name
RUN = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]; NOW = time.strftime("%Y-%m-%dT%H:%M:%S")

# ---- the source registry and the authority MATRIX (attribute x source, 0-100; higher wins, ties by spatial quality) --------------------
SOURCES = [
    ("dld_unit", "Dubai Land Department", "units register (Oqood)", "authority", "AE-DU"),
    ("dld_project", "Dubai Land Department", "projects register", "authority", "AE-DU"),
    ("dld_land", "Dubai Land Department", "land registry (parcels)", "authority", "AE-DU"),
    ("dld_transactions", "Dubai Land Department", "transactions", "authority", "AE-DU"),
    ("dm_building", "Dubai Municipality", "building register / Makani", "authority", "AE-DU"),
    ("dm_project", "Dubai Municipality", "project information (permits, contractors)", "authority", "AE-DU"),
    ("khda", "KHDA", "private school register", "authority", "AE-DU"),
    ("ese", "Emirates Schools Establishment", "government schools", "authority", "AE"),
    ("dha", "Dubai Health Authority", "facility licences", "authority", "AE-DU"),
    ("rta", "RTA", "metro and tram stations", "authority", "AE-DU"),
    ("dsc", "Dubai Statistics Centre", "population by community", "authority", "AE-DU"),
    ("developer_sheet", "developer (via WhatsApp group)", "availability sheets", "primary", "project"),
    ("developer_site", "developer website", "portfolio pages", "primary", "project"),
    ("meed", "MEED Projects", "pipeline corpus", "commercial", "GCC"),
    ("osm", "OpenStreetMap", "buildings, names, land use, water, beaches", "open", "world"),
    ("overture", "Overture Maps", "buildings, land, water (largely OSM)", "open", "world"),
    ("overture_place", "Overture Maps places", "points of interest (businesses, tenants)", "open", "world"),
    ("wikidata", "Wikidata", "notable structures", "open", "world"),
    ("google_places", "Google Places", "businesses, geocodes", "commercial", "world"),
    ("inferred", "Najma resolver", "derived (bindings, nearest, corridors)", "derived", "internal"),
    ("field", "Najjuko / ground truth", "poll answers, site knowledge", "primary", "AE-DU"),
]
ATTRS = ["name", "height", "storeys", "footprint", "plot", "address", "tenant", "amenity_name", "developer", "project", "units", "price", "rent", "geocode", "water_name", "beach_access", "park_access"]
MATRIX = {  # rows: source; columns: ATTRS in order
    "dld_unit":         [100, 40, 60, 0, 100, 90, 20, 0, 90, 100, 100, 0, 0, 0, 0, 0, 0],
    "dld_project":      [95, 0, 0, 0, 90, 60, 0, 0, 100, 100, 95, 0, 0, 0, 0, 0, 0],
    "dld_land":         [70, 0, 0, 90, 100, 50, 0, 0, 60, 90, 0, 0, 0, 80, 0, 0, 0],
    "dld_transactions": [60, 0, 30, 0, 90, 40, 0, 0, 50, 80, 60, 100, 0, 0, 0, 0, 0],
    "dm_building":      [98, 90, 95, 100, 100, 100, 10, 0, 40, 60, 80, 0, 0, 95, 0, 0, 0],
    "dm_project":       [80, 60, 70, 0, 100, 60, 0, 0, 70, 90, 60, 0, 0, 0, 0, 0, 0],
    "khda":             [0, 0, 0, 0, 0, 60, 0, 100, 0, 0, 0, 0, 0, 90, 0, 0, 0],
    "ese":              [0, 0, 0, 0, 0, 60, 0, 100, 0, 0, 0, 0, 0, 90, 0, 0, 0],
    "dha":              [0, 0, 0, 0, 0, 60, 0, 100, 0, 0, 0, 0, 0, 70, 0, 0, 0],
    "rta":              [0, 0, 0, 0, 0, 0, 0, 100, 0, 0, 0, 0, 0, 100, 0, 0, 0],
    "dsc":              [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
    "developer_sheet":  [70, 0, 50, 0, 0, 0, 0, 0, 100, 95, 90, 90, 0, 0, 0, 0, 0],
    "developer_site":   [75, 40, 60, 0, 0, 40, 0, 0, 100, 95, 70, 30, 0, 30, 0, 0, 0],
    "meed":             [50, 30, 40, 0, 0, 0, 0, 0, 80, 85, 50, 0, 0, 0, 0, 0, 0],
    "osm":              [90, 75, 70, 80, 40, 80, 30, 70, 20, 30, 0, 0, 0, 70, 85, 60, 60],
    "overture":         [85, 80, 70, 80, 30, 65, 10, 70, 10, 20, 0, 0, 0, 65, 85, 50, 50],
    "wikidata":         [80, 85, 80, 0, 0, 20, 0, 0, 40, 40, 0, 0, 0, 40, 60, 0, 0],
    "google_places":    [25, 0, 0, 0, 0, 70, 95, 80, 10, 10, 0, 0, 0, 55, 20, 40, 30],
    "overture_place":   [25, 0, 0, 0, 0, 60, 95, 80, 10, 10, 0, 0, 0, 50, 20, 40, 30],
    "inferred":         [10, 20, 20, 0, 30, 10, 0, 0, 30, 30, 0, 0, 0, 40, 50, 70, 70],
    "field":            [95, 0, 0, 0, 0, 70, 90, 90, 90, 90, 0, 0, 0, 0, 90, 100, 100],
}


def jload(p, default=None):
    try: return json.load(open(p, encoding="utf-8"))
    except Exception: return default


def m(a, b):
    return math.hypot((a[0] - b[0]) * 111320 * math.cos(a[1] * math.pi / 180), (a[1] - b[1]) * 111320)


def main():
    os.makedirs(GDIR, exist_ok=True)
    if "--fresh" in sys.argv and os.path.exists(DB): os.remove(DB)
    con = duckdb.connect(DB)
    con.execute("create table if not exists run (run_id varchar primary key, started varchar, schema_version varchar, resolver_version varchar, note varchar)")
    con.execute("insert into run values (?, ?, ?, ?, ?)", [RUN, NOW, SCHEMA, RESOLVER, "graph_build.py"])
    # ---- policy tables -----------------------------------------------------------------------------------------------------------------
    con.execute("create or replace table source (source_id varchar primary key, publisher varchar, dataset varchar, authority_level varchar, scope varchar)")
    con.executemany("insert into source values (?,?,?,?,?)", SOURCES)
    con.execute("create or replace table source_authority (source_id varchar, attribute varchar, weight integer)")
    con.executemany("insert into source_authority values (?,?,?)", [(s, a, w) for s, ws in MATRIX.items() for a, w in zip(ATTRS, ws)])
    # ---- districts, sub-communities, plots ------------------------------------------------------------------------------------------------
    D = jload(os.path.join(BOARD, "districts_geo.json"), {"districts": []})["districts"]
    con.execute("create or replace table district (slug varchar primary key, name varchar, corridor varchar, lon double, lat double, bbox_w double, bbox_s double, bbox_e double, bbox_n double, subs integer, plots integer, named integer)")
    con.executemany("insert into district values (?,?,?,?,?,?,?,?,?,?,?,?)", [(d["slug"], d["name"], d.get("corridor"), d["centre"][0], d["centre"][1], *d["bbox"], d.get("subs"), d.get("plots"), d.get("named")) for d in D])
    S = jload(os.path.join(BOARD, "subs.json"), {"features": []}); S = S.get("features", S)
    con.execute("create or replace table sub_community (sub_id varchar primary key, name varchar, district varchar, lon double, lat double, radius_m double, plots integer, units integer, buildings integer)")
    rows = []
    for k, f in enumerate(S):
        p = f["properties"]; g = f["geometry"]["coordinates"]; c = g if isinstance(g[0], (int, float)) else g[0][0]
        rows.append((f"SUB-{p.get('district','')}-{k}", p.get("name"), p.get("district"), c[0], c[1], p.get("radius_m"), p.get("plots"), p.get("units"), p.get("buildings")))
    con.executemany("insert into sub_community values (?,?,?,?,?,?,?,?,?)", rows)
    P = jload(os.path.join(BOARD, "plots.json"), {"features": []}); P = P.get("features", P)
    con.execute("create or replace table plot (plot_no varchar, name varchar, district varchar, master varchar, parcel_id varchar, units integer, area_sqm double, lon double, lat double)")
    prow = []
    for f in P:
        p = f.get("properties", f); g = (f.get("geometry") or {}).get("coordinates"); c = (g if g and isinstance(g[0], (int, float)) else (g[0][0] if g else [None, None]))
        prow.append((p.get("plot"), p.get("name"), p.get("district"), p.get("master"), p.get("parcel"), p.get("units"), p.get("area_sqm"), c[0], c[1]))
    con.executemany("insert into plot values (?,?,?,?,?,?,?,?,?)", prow)
    # ---- developers, projects, sheet projects ------------------------------------------------------------------------------------------
    BD = jload(os.path.join(BOARD, "board_devs.json"), {"developers": []})["developers"]
    con.execute("create or replace table developer (dev_key varchar primary key, name varchar, segment varchar, tier varchar, portfolio_count integer)")
    con.executemany("insert into developer values (?,?,?,?,?)", [(d["key"], d["name"], d.get("segment"), d.get("tier"), d.get("portfolio_count")) for d in BD])
    U = jload(os.path.join(BOARD, "unitmix_projects_slim.json"), {"projects": {}})["projects"]
    con.execute("create or replace table project (project_key varchar primary key, name varchar, district varchar, footprint_i integer, status varchar, total_units integer, floors integer, car_parks integer, developer varchar, master_project varchar, register_aed_sqm double, rows_json varchar)")
    con.executemany("insert into project values (?,?,?,?,?,?,?,?,?,?,?,?)", [(k, v.get("name"), v.get("district"), v.get("i"), v.get("status"), v.get("total_units"), v.get("floors"), v.get("car_parks"), v.get("developer"), v.get("master_project"), v.get("register_aed_sqm"), json.dumps(v.get("rows") or [], ensure_ascii=False)) for k, v in U.items()])
    R = jload(os.path.join(BOARD, "remaining.json"), {"projects": {}})["projects"]
    con.execute("create or replace table sheet_project (sheet_key varchar primary key, name varchar, developer varchar, sheet_date varchar, launched integer, sold integer, on_sheet integer, remaining integer, register_names varchar, registry_json varchar, by_type_json varchar)")
    con.executemany("insert into sheet_project values (?,?,?,?,?,?,?,?,?,?,?)", [(k, v.get("name"), v.get("developer"), v.get("sheet_date"), (v.get("totals") or {}).get("launched"), (v.get("totals") or {}).get("sold"), (v.get("totals") or {}).get("sheet"), (v.get("totals") or {}).get("remaining"), json.dumps(v.get("register_names") or []), json.dumps(v.get("registry") or {}, ensure_ascii=False), json.dumps(v.get("by_type") or {}, ensure_ascii=False)) for k, v in R.items()])
    # ---- amenities (with access), water bodies -----------------------------------------------------------------------------------------
    A = jload(os.path.join(BOARD, "amenities.json"), {"items": []})["items"]
    con.execute("create or replace table amenity (amenity_id varchar primary key, kind varchar, name varchar, lon double, lat double, source varchar, access varchar, detail varchar, district varchar, tel varchar, web varchar, addr varchar, approx boolean)")
    con.executemany("insert into amenity values (?,?,?,?,?,?,?,?,?,?,?,?,?)", [(f"AM-{i}", a.get("k"), a.get("n"), a.get("lon"), a.get("lat"), a.get("src"), a.get("acc"), a.get("x"), a.get("d"), a.get("tel"), a.get("web"), a.get("ad") or a.get("addr"), bool(a.get("ap"))) for i, a in enumerate(A)])
    W = jload(os.path.join(BOARD, "water_register.json"), {"bodies": []})["bodies"]
    con.execute("create or replace table water_body (body_id integer primary key, name varchar, named boolean, cls varchar, overture_class varchar, area_ha double, lon double, lat double, district varchar)")
    con.executemany("insert into water_body values (?,?,?,?,?,?,?,?,?)", [(b["id"], b["name"], b["named"], b["cls"], b["overture_class"], b["area_ha"], b["centroid"][0], b["centroid"][1], b.get("district")) for b in W])
    # ---- buildings + the evidence ledger (from the resolver's own records) ---------------------------------------------------------------
    con.execute("create or replace table building (duid varchar primary key, district varchar, footprint_i integer, lon double, lat double, height_m double, storeys integer, display_name varchar, display_role varchar, official_name varchar, structural_identifier varchar, project_name varchar, plot_id varchar, address varchar, grade varchar, name_source varchar, confidence double, developer varchar, tenants integer, amenities integer, kind varchar)")
    con.execute("""create table if not exists evidence (evidence_id varchar, run_id varchar, entity_type varchar, entity_id varchar, attribute varchar, value varchar, role varchar,
                   source varchar, source_record_id varchar, method varchar, confidence double, score double, dist_m double, inside boolean, captured_at varchar, status varchar,
                   schema_version varchar, resolver_version varchar, valid_from varchar, valid_to varchar)""")
    seen_ev = set(r[0] for r in con.execute("select evidence_id from evidence").fetchall())
    brows = []; erows = []
    for f in sorted(glob.glob(os.path.join(IDENT, "*.json"))):
        j = jload(f, {}); d = j.get("district")
        for r in j.get("rows", []):
            st = r.get("storeys") or 0; h = r.get("height_m") or 0
            kind = "tower" if (st >= 6 or h >= 20) else ("midrise" if (st >= 3 or h >= 10) else "low")
            brows.append((r["duid"], d, r.get("i"), r.get("lon"), r.get("lat"), r.get("height_m"), r.get("storeys"), r.get("display_name") or r.get("current_name"), r.get("display_role"), r.get("official_building_name"), r.get("structural_identifier"), r.get("project_name"), r.get("plot_id"), r.get("address"), r.get("grade"), r.get("name_source"), r.get("confidence"), r.get("developer"), len(r.get("tenant_names") or []), len(r.get("amenity_names") or []), kind))
            for e in r.get("evidence") or []:
                eid = f"{e.get('duid')}|{e.get('attribute')}|{e.get('source')}|{e.get('source_record_id')}|{str(e.get('value'))[:80]}|{e.get('captured_at')}"
                if eid in seen_ev: continue
                seen_ev.add(eid)
                role = e.get("role"); status = "ACCEPTED" if e.get("canonical_eligible") else "DISCOVERED"
                if e.get("attribute") == "name" and e.get("source") in PLACE_SOURCES and role == "BUILDING_NAME": role = "TENANT"; status = "DISCOVERED"   # the role rule
                erows.append((eid, RUN, "building", e.get("duid"), e.get("attribute"), str(e.get("value")) if e.get("value") is not None else None, role, e.get("source"), str(e.get("source_record_id")) if e.get("source_record_id") is not None else None, e.get("method"), e.get("confidence"), e.get("score"), e.get("dist_m"), e.get("inside"), e.get("captured_at"), status, SCHEMA, RESOLVER, e.get("captured_at"), None))
    con.executemany("insert into building values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", brows)
    # waterfront, beach/park access and water names as evidence too
    WF = jload(os.path.join(ENRICH, "waterfront.json"), {"buildings": {}})["buildings"]
    for duid, v in WF.items():
        eid = f"{duid}|waterfront|overture_water|{v.get('source_record_id')}|{v.get('value')}|{v.get('captured_at')}"
        if eid in seen_ev: continue
        seen_ev.add(eid); erows.append((eid, RUN, "building", duid, "waterfront", v.get("value"), None, "overture", str(v.get("source_record_id")), v.get("method"), v.get("confidence"), None, v.get("distance_m"), None, v.get("captured_at"), "ACCEPTED", SCHEMA, RESOLVER, v.get("captured_at"), None))
    for nm, kind, attr in (("beaches.json", "beach", "beach_access"), ("parks.json", "park", "park_access")):
        for i, it in enumerate(jload(os.path.join(BOARD, nm), {"items": []})["items"]):
            eid = f"{kind}-{i}|{attr}|inferred|{it.get('why')}|{it.get('acc')}|{NOW[:10]}"
            if eid in seen_ev: continue
            seen_ev.add(eid); erows.append((eid, RUN, "amenity", f"{kind}:{it.get('n')}@{it.get('lon')},{it.get('lat')}", attr, it.get("acc"), None, "inferred", it.get("src"), it.get("why"), 0.9 if it.get("acc") == "public" else 0.6, None, None, None, NOW, "DISCOVERED", SCHEMA, RESOLVER, NOW, None))
    for b in W:
        eid = f"water-{b['id']}|water_name|overture|{b['overture_class']}|{b['name']}|{NOW[:10]}"
        if eid in seen_ev: continue
        seen_ev.add(eid); erows.append((eid, RUN, "water_body", str(b["id"]), "water_name", b["name"], None, "overture", b["overture_class"], "coastline.py v2 (english common name, corridor relabel)", 0.9 if b["named"] else 0.4, None, None, None, NOW, "ACCEPTED" if b["named"] else "DISCOVERED", SCHEMA, RESOLVER, NOW, None))
    if erows: con.executemany("insert into evidence values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", erows)
    # ---- edges -----------------------------------------------------------------------------------------------------------------------
    con.execute("create or replace table building_waterfront as select duid, body_id, cls, distance_m, body from (select entity_id duid, cast(source_record_id as integer) body_id, null::varchar cls, dist_m distance_m, value body from evidence where attribute='waterfront' and status='ACCEPTED')")
    con.execute("create or replace table project_developer as select project_key, lower(developer) dev_name, (select dev_key from developer d where lower(d.name)=lower(p.developer) or lower(d.dev_key)=lower(p.developer) limit 1) dev_key from project p where developer is not null")
    con.execute("create or replace table sheet_project_register as select sheet_key, name, developer, register_names, (registry_json != '{}') has_registry from sheet_project")
    # nearest amenity of each kind per sub-community, with the measurement (the relationship type is NEAREST_TO)
    AMS = con.execute("select amenity_id, kind, name, lon, lat, access from amenity").fetchall(); bykind = {}
    for a in AMS: bykind.setdefault(a[1], []).append(a)
    subs = con.execute("select sub_id, lon, lat from sub_community").fetchall(); nrows = []
    for sid, lon, lat in subs:
        for kind, lst in bykind.items():
            best = None; bestpub = None
            for a in lst:
                d = m((lon, lat), (a[3], a[4]))
                if best is None or d < best[0]: best = (d, a)
                if (a[5] in (None, "public", "community")) and (bestpub is None or d < bestpub[0]): bestpub = (d, a)
            if best: nrows.append((sid, best[1][0], kind, "NEAREST_TO", round(best[0]), best[1][5]))
            if bestpub and (best is None or bestpub[1][0] != best[1][0]): nrows.append((sid, bestpub[1][0], kind, "NEAREST_PUBLIC", round(bestpub[0]), bestpub[1][5]))
    con.execute("create or replace table sub_community_amenity (sub_id varchar, amenity_id varchar, kind varchar, relation varchar, distance_m integer, access varchar)")
    con.executemany("insert into sub_community_amenity values (?,?,?,?,?,?)", nrows)
    # ---- golden set (the test every resolver change must pass) ----------------------------------------------------------------------------
    con.execute("create or replace table golden (golden_id varchar, entity_type varchar, entity_ref varchar, attribute varchar, expected varchar, basis varchar, status varchar, added varchar)")
    g = []
    bp = jload(os.path.join(BOARD, "beach_poll_08sep2026.json"), {"questions": []})
    fa = (jload(os.path.join(BOARD, "beach01_answers.json"), {}) or {}).get("answers", {})
    fa.setdefault("7", {"ans": "not sure"})    # Azizi Mina: answered 08:50, lost from the store by a stale write-back, read before it vanished
    for qn in bp["questions"]:
        a = (fa.get(str(qn["n"])) or {}).get("ans"); st = "PASS (field: yes)" if a == "yes" else ("FAIL (field: no)" if a == "no" else ("FIELD: not sure" if a else "PENDING_FIELD"))
        g.append((f"beach01-{qn['n']}", "place", qn["prop"], "nearest_beach", f"{qn['claim_beach']} · {qn['claim_access']} · {qn['claim_m']} m", "map claim, put to Najjuko 8 Sep 2026", st, NOW))
    wp = jload(os.path.join(BOARD, "waterpark_poll_09sep2026.json"), {"questions": []})       # water + parks poll, sent 9 Sep 2026 with Kendall's approval
    wa = (jload(os.path.join(BOARD, "waterpark01_answers.json"), {}) or {}).get("answers", {})
    for qn in wp["questions"]:
        a = (wa.get(str(qn["n"])) or {}).get("ans"); st = "PASS (field: yes)" if a == "yes" else ("FAIL (field: no)" if a == "no" else ("FIELD: not sure" if a else "PENDING_FIELD"))
        attr = {"beach": "nearest_beach", "park": "nearest_park", "water": "nearest_water"}.get(qn.get("kind"), "nearest_" + str(qn.get("kind")))
        g.append((f"waterpark01-{qn['n']}", "place", qn["prop"], attr, f"{qn['claim']} · {qn['claim_access']} · {qn['claim_m']} m", "map claim, put to Najjuko 9 Sep 2026", st, NOW))
    pp = jload(os.path.join(BOARD, "park_poll_DRAFT_08sep2026.json"), {"questions": []})
    for qn in pp["questions"]:
        if qn.get("claim_park"): g.append((f"park01-{qn['n']}", "place", qn["prop"], "nearest_park", f"{qn['claim_park']} · {qn.get('claim_access','')} · {qn.get('claim_m','')} m", "map claim, draft poll 8 Sep 2026", "DRAFT", NOW))
    au = jload(os.path.join(BOARD, "amenity_truth_audit.json"), {"flags": {}})
    for flag, rows_ in au.get("flags", {}).items():
        for r in rows_[:40]: g.append((f"aud-{flag}-{r['name']}", "place", r["name"], flag, json.dumps({k: r.get(k) for k in ("sea_m", "beach", "school", "mall", "park") if r.get(k) is not None}, ensure_ascii=False)[:300], "DA-AUD-004 flag", "OBSERVED", NOW))
    g += [("err-seacliff", "project", "Seacliff by Imtiaz", "geocode", "Dubai Islands (Palm Deira), parcel 1010453 - NOT Dubai Hills (developer office)", "8 Sep 2026 correction", "VERIFIED", NOW),
          ("err-orra", "project", "W Residences at Dubai Harbour", "twin_binding", "must not resolve to footprint 386 (Orra Harbour Residences)", "8 Sep 2026 film take rejected", "VERIFIED", NOW),
          ("err-masaar", "project", "Masaar (Arada)", "geocode", "Sharjah - NOT JVC 'Masaar Residences'", "8 Sep 2026 correction", "VERIFIED", NOW),
          ("err-symphony", "project", "Symphony Tower (Imtiaz)", "identity", "one record, not three (businessbay footprint 641 / goldensymphony / Nad Al Sheba geocode)", "8 Sep 2026 audit", "OPEN", NOW),
          ("err-apple", "building", "Building 4 (JLT)", "name", "structural identifier stays; 'Apple Office' is a TENANT", "resolver rule 4 Sep 2026", "VERIFIED", NOW),
          ("err-chelsea", "place", "Chelsea Residences 2 by Damac", "waterfront", "Arabian Gulf ~21 m; nearest public beach Pearl Jumeirah ~3.8 km", "Najjuko 8 Sep 2026 11:40", "VERIFIED", NOW)]
    con.executemany("insert into golden values (?,?,?,?,?,?,?,?)", g)
    # ---- views -----------------------------------------------------------------------------------------------------------------------------
    con.execute("""create or replace view v_building_identity as select b.duid, b.district, b.display_name, b.display_role, b.grade, b.name_source, b.confidence, b.kind,
                   (select count(*) from evidence e where e.entity_id=b.duid and e.attribute='name') name_evidence_n,
                   (select string_agg(distinct e.source, ',') from evidence e where e.entity_id=b.duid and e.attribute='name') name_sources,
                   w.body waterfront from building b left join building_waterfront w on w.duid=b.duid""")
    con.execute("create or replace view v_unresolved_towers as select duid, district, footprint_i, height_m, storeys, structural_identifier, plot_id from building where display_name is null and kind='tower' order by height_m desc")
    con.execute("""create or replace view v_conflicting_names as select entity_id as duid, count(distinct value) as n_names, string_agg(distinct value || ' [' || source || ']', ' | ') as claims
                   from evidence where attribute='name' and role='BUILDING_NAME' group by entity_id having count(distinct value) > 1""")
    con.execute("""create or replace view v_place_card as select s.sub_id, s.name, s.district, s.units, s.plots,
                   (select string_agg(a.kind || ':' || a.name || ' ' || sa.distance_m || 'm', ' | ') from sub_community_amenity sa join amenity a on a.amenity_id=sa.amenity_id where sa.sub_id=s.sub_id and sa.relation='NEAREST_PUBLIC') nearest_public
                   from sub_community s""")
    con.execute("""create or replace view v_name_by_matrix as
      with c as (select e.entity_id duid, e.value, e.source, coalesce(sa.weight,0) w, e.confidence, e.dist_m
                 from evidence e left join source_authority sa on sa.source_id = case when e.source in ('dld','dld_unit') then 'dld_unit' when e.source in ('osm','osm_en') then 'osm'
                      when e.source='overture_place' then 'overture_place' when e.source in ('places','google') then 'google_places' when e.source='register' then 'dld_project' else e.source end and sa.attribute='name'
                 where e.attribute='name' and e.role='BUILDING_NAME' and e.status='ACCEPTED'),
      r as (select *, row_number() over (partition by duid order by w desc, confidence desc, coalesce(dist_m,999)) rn from c)
      select r.duid, r.value as matrix_name, r.source as matrix_source, r.w as matrix_weight, b.display_name as current_name, b.name_source as current_source,
             (lower(r.value) is distinct from lower(b.display_name)) as differs from r join building b on b.duid=r.duid where rn=1""")
    # the role rule on history: place claims accepted as BUILDING_NAME are rejected as names (the rows stay in the ledger)
    con.execute("update evidence set status='REJECTED', role='TENANT' where attribute='name' and role='BUILDING_NAME' and source in ('overture_place','places','google','google_places') and status<>'REJECTED'")
    # aliases: every other name a good source calls the building; bilingual water names from Overture's own name list
    con.execute("create or replace table alias (entity_type varchar, entity_id varchar, value varchar, lang varchar, source varchar, kind varchar)")
    con.execute("""insert into alias select 'building', e.entity_id, e.value, case when regexp_matches(e.value, '__AR__') then 'ar' else 'en' end, e.source, 'register_variant'
                   from evidence e join building b on b.duid=e.entity_id where e.attribute='name' and e.role='BUILDING_NAME' and e.status<>'REJECTED'
                   and e.source in ('dld','dld_unit','osm','osm_en','wikidata','register','overture') and lower(e.value) is distinct from lower(b.display_name) group by all""".replace("__AR__", "[\u0600-\u06FF]"))
    wraw = jload(os.path.join(ROOT, "data", "names", "overture_raw", "dubai_water.geojson"), {"features": []})["features"]
    wnames = {}
    for f in wraw:
        n = f["properties"].get("names") or {}
        if n.get("primary"): wnames.setdefault(n["primary"], set()).update([(lang, v) for lang, v in (n.get("common") or [])] + [("primary", n["primary"])])
    arows = []
    for b in W:
        for prim, pairs in wnames.items():
            if any(v == b["name"] for _, v in pairs):
                for lang, v in pairs:
                    if lang != "primary" and v != b["name"]: arows.append(("water_body", str(b["id"]), v, lang, "overture", "name_common"))
    if arows: con.executemany("insert into alias values (?,?,?,?,?,?)", arows)
    con.execute("""create or replace view v_canonical_name as
      with c as (select e.entity_id duid, e.value, e.source, coalesce(sa.weight,0) w, e.confidence, e.dist_m
                 from evidence e left join source_authority sa on sa.source_id = case when e.source in ('dld','dld_unit') then 'dld_unit' when e.source in ('osm','osm_en') then 'osm'
                      when e.source='overture_place' then 'overture_place' when e.source in ('places','google') then 'google_places' when e.source='register' then 'dld_project' else e.source end and sa.attribute='name'
                 where e.attribute='name' and e.role='BUILDING_NAME' and e.status in ('ACCEPTED','MANUALLY_VERIFIED')),
      r as (select *, row_number() over (partition by duid order by w desc, confidence desc, coalesce(dist_m,999)) rn from c)
      select r.duid, r.value as canonical_name, r.source as canonical_source, r.w as weight, b.display_name as current_name, b.name_source as current_source,
             (lower(r.value) is distinct from lower(b.display_name)) as differs from r join building b on b.duid=r.duid where rn=1""")
    # ---- report ------------------------------------------------------------------------------------------------------------------------------
    def n(t): return con.execute(f"select count(*) from {t}").fetchone()[0]
    print(f"najma.duckdb · run {RUN} · schema {SCHEMA}")
    for t in ("source", "source_authority", "district", "sub_community", "plot", "developer", "project", "sheet_project", "amenity", "water_body", "building", "evidence", "building_waterfront", "sub_community_amenity", "golden"): print(f"  {t:24s} {n(t):>9,}")
    print("  evidence appended this run:", len(erows))
    print("  unresolved towers:", con.execute("select count(*) from v_unresolved_towers").fetchone()[0], "| buildings with conflicting names:", con.execute("select count(*) from v_conflicting_names").fetchone()[0])
    print("  canonical (matrix + role rule) would change:", con.execute("select count(*) from v_canonical_name where differs").fetchone()[0], "of", con.execute("select count(*) from v_canonical_name").fetchone()[0], "| aliases:", con.execute("select count(*) from alias").fetchone()[0], "| rejected place-names:", con.execute("select count(*) from evidence where status='REJECTED'").fetchone()[0])
    print("  ->", DB, f"{os.path.getsize(DB) // 1048576} MB")
    con.close()


if __name__ == "__main__":
    main()
