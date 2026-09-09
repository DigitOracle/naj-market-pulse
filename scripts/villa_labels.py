"""Villas and townhouses are places, not names — Kendall's rule, 9 Sep 2026.

A low-rise building (three storeys or under, or below 12 m) gets a KIND (villa / townhouse, from footprint area) and a PLACE LABEL:
  1. inside a DLD sub-community cluster (same district, within the cluster's radius)  ->  "Juniper villa, Damac Hills 2"      (basis: cluster)
  2. otherwise the official Dubai Municipality community it stands in              ->  "Al Hebiah Third villa"             (basis: community)
  3. the plot number joins when DM's parcel layer arrives (data.dubai request)      ->  "plot 313, Juniper"                 (not yet)
Nothing is written onto the building's name. The label is evidence (attribute place_label, role LOCATION, source resolver_villa_rule) and a
table (villa_label) in the truth store, plus one JSON per district (data/names/villa_labels_<slug>.json) that apply_identity.py carries onto
the anchors as {kind, place_label, cluster} so the twin and the cards can show it.
Usage: python scripts/villa_labels.py [slug ...]
"""
import glob, hashlib, json, os, re, sys, time
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
import duckdb
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, ".."))
DB = os.path.join(ROOT, "data", "graph", "najma.duckdb"); BOARD = os.path.join(ROOT, "data", "board"); NAMES = os.path.join(ROOT, "data", "names")
NOW = time.strftime("%Y-%m-%dT%H:%M:%S"); RUN = time.strftime("%Y%m%d-%H%M%S") + "-villa"; SCHEMA = "1.2"; RESOLVER = "villa-rule-2026-09-09"
TOWNHOUSE_M2 = 160          # footprint under this = townhouse (terraced plots); over = villa
LOW_STOREYS = 3; LOW_M = 12
MARKET = {"damachills": "Damac Hills", "dubaihills": "Dubai Hills", "alyufrah1": "The Valley", "madinatalmataar": "Expo City side", "meydanone": "Meydan", "wadialsafa4": "Arabian Ranches 2 side", "wadialsafa5": "Arabian Ranches 3 side"}


def eid(entity_id, attribute, value, source, rec):
    return hashlib.sha1(f"{entity_id}|{attribute}|{value}|{source}|{rec}".encode("utf-8")).hexdigest()[:24]


def clean_cluster(name):
    """'DAMAC HILLS (2) - JUNIPER' -> ('Juniper', 'Damac Hills 2'); 'Villa Lantana 1' -> ('Villa Lantana 1', None)."""
    n = re.sub(r"\s+", " ", (name or "").strip())
    m = re.match(r"^(.*?)\s*[-–]\s*(.+)$", n)
    master, part = (m.group(1), m.group(2)) if m else (None, n)
    def title(s):
        s = re.sub(r"\((\d)\)", r"\1", s); s = " ".join(w if (w.isupper() and len(w) <= 3 and w.isalpha() and w not in ("THE",)) else w.capitalize() for w in s.split())
        return s.replace("Ii", "II").replace("Iii", "III")
    return title(part), (title(master) if master else None)


def main():
    con = duckdb.connect(DB); slugs = sys.argv[1:] or [r[0] for r in con.execute("select distinct district from building order by 1").fetchall()]
    con.execute("create or replace table villa_label (duid varchar, district varchar, footprint_i integer, kind varchar, label varchar, cluster_sub_id varchar, cluster varchar, comm_num varchar, community varchar, basis varchar, confidence double)")
    dm_name = {r[0]: r[1] for r in con.execute("select comm_num, name_en from dm_community").fetchall()} if con.execute("select count(*) from duckdb_tables() where table_name='dm_community'").fetchone()[0] else {}
    dist_name = {r[0]: r[1] for r in con.execute("select slug, name from district").fetchall()}
    tot = {"villa": 0, "townhouse": 0, "cluster": 0, "community": 0}
    ev = []
    for slug in slugs:
        facts = {}
        fp = os.path.join(BOARD, f"bldgfacts_{slug}.json")
        if os.path.exists(fp):
            j = json.load(open(fp, encoding="utf-8"))
            src = j.get("b") or j.get("facts") or j.get("items") or j
            if isinstance(src, list):
                for v in src:
                    if isinstance(v, dict) and v.get("i") is not None: facts[int(v["i"])] = v
            else:
                for k, v in src.items():
                    if isinstance(v, dict) and (str(k).isdigit() or v.get("i") is not None): facts[int(v.get("i", k))] = v
        # footprint area from the district's own footprints (data/ce/<slug>/buildings.geojson, feature order = footprint index) when the facts file has none
        gj = os.path.join(ROOT, "data", "ce", slug, "buildings.geojson")
        if os.path.exists(gj) and not facts:
            import math
            feats = json.load(open(gj, encoding="utf-8")).get("features", [])
            for idx, ft in enumerate(feats):
                g = ft.get("geometry") or {}; rings = [g["coordinates"][0]] if g.get("type") == "Polygon" else ([pg[0] for pg in g.get("coordinates", [])] if g.get("type") == "MultiPolygon" else [])
                area = 0.0
                for ring in rings:
                    if len(ring) < 4: continue
                    lat0 = sum(pt[1] for pt in ring) / len(ring); kx = 111320 * math.cos(math.radians(lat0)); ky = 111320
                    xs = [pt[0] * kx for pt in ring]; ys = [pt[1] * ky for pt in ring]
                    area += abs(sum(xs[k] * ys[(k + 1) % len(ring)] - xs[(k + 1) % len(ring)] * ys[k] for k in range(len(ring)))) / 2
                facts[idx] = {"footprint_m2": round(area)}
        subs = con.execute("select sub_id, name, lon, lat, coalesce(radius_m, 250) from sub_community where district=? and lon is not null", [slug]).fetchall()
        rows = con.execute("""select b.duid, b.footprint_i, b.lon, b.lat, b.height_m, b.storeys, c.comm_num
                               from building b left join building_dm_community c on c.duid=b.duid
                               where b.district=? and b.display_name is null and (coalesce(b.storeys,0) <= ? or coalesce(b.height_m,0) < ?)""", [slug, LOW_STOREYS, LOW_M]).fetchall()
        out = {}; recs = []
        for duid, i, lon, lat, h, st, comm in rows:
            f = facts.get(i) or {}; area = f.get("footprint_m2") or 0
            kind = "townhouse" if 0 < area < TOWNHOUSE_M2 else "villa"
            best = None
            for sid, nm, slon, slat, rad in subs:
                d = ((lat - slat) * 111320) ** 2 + ((lon - slon) * 100800) ** 2
                if d <= rad * rad and (best is None or d < best[0]): best = (d, sid, nm)
            if best:
                part, master = clean_cluster(best[2]); place = master or MARKET.get(slug) or dist_name.get(slug) or slug
                label = f"{part} {kind}, {place}"; basis = "cluster"; conf = 0.8; cl_id, cl = best[1], best[2]
            else:
                community = (dm_name.get(comm) or "").title() or (MARKET.get(slug) or dist_name.get(slug) or slug)
                label = f"{community} {kind}"; basis = "community"; conf = 0.6; cl_id, cl = None, None
            tot[kind] += 1; tot[basis] += 1
            recs.append((duid, slug, i, kind, label, cl_id, cl, comm, dm_name.get(comm), basis, conf))
            out[str(i)] = {"kind": kind, "place_label": label, "cluster": cl, "sub_id": cl_id, "comm": comm, "basis": basis}
            ev.append((eid(duid, "place_label", label, "resolver_villa_rule", basis), RUN, "building", duid, "place_label", label, "LOCATION", "resolver_villa_rule", cl_id or comm, f"low-rise {kind} placed by {basis}", conf, None, None, None, NOW, "ACCEPTED", SCHEMA, RESOLVER, NOW, None))
            ev.append((eid(duid, "kind", kind, "resolver_villa_rule", str(int(area))), RUN, "building", duid, "kind", kind, "CLASS", "resolver_villa_rule", str(int(area)), f"footprint {int(area)} m2, storeys {st}", 0.7, None, None, None, NOW, "ACCEPTED", SCHEMA, RESOLVER, NOW, None))
        if recs: con.executemany("insert into villa_label values (?,?,?,?,?,?,?,?,?,?,?)", recs)
        json.dump({"district": slug, "generated": NOW, "rule": "villa/townhouse place labels (villa_labels.py)", "labels": out}, open(os.path.join(NAMES, f"villa_labels_{slug}.json"), "w", encoding="utf-8"), ensure_ascii=False)
        print(f"  {slug:26s} low-rise unnamed {len(recs):6,d} · by cluster {sum(1 for r in recs if r[9]=='cluster'):6,d} · by community {sum(1 for r in recs if r[9]=='community'):6,d}")
    con.execute("create or replace temp table ev_new as select * from evidence limit 0")
    if ev: con.executemany("insert into ev_new values (" + ",".join("?" * 20) + ")", ev)
    added = con.execute("insert into evidence select n.* from ev_new n where not exists (select 1 from evidence e where e.evidence_id = n.evidence_id)").fetchone()[0]
    con.execute("create or replace view v_villa_label as select v.*, b.lon, b.lat, b.height_m from villa_label v join building b on b.duid=v.duid")
    con.execute("insert into run values (?,?,?,?,?)", [RUN, NOW, SCHEMA, RESOLVER, f"villa labels: {sum(tot[k] for k in ('villa','townhouse'))} low-rise labelled ({tot['cluster']} by cluster, {tot['community']} by community); {added} evidence rows"])
    con.close()
    print(f"villas {tot['villa']:,} · townhouses {tot['townhouse']:,} · by cluster {tot['cluster']:,} · by community {tot['community']:,} · evidence rows appended {added:,}")


if __name__ == "__main__":
    main()
