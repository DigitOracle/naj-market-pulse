"""Cross-source dedupe of rental adverts into UNITS: advertised supply across portals, deduplicated (research use only, 1 Oct 2026).

What it measures. For one run_date, every lst_listing_snapshot row (all portals: propertyfinder, allsopp, fam, bhomes, espace) is
clustered into units; a unit is the same flat advertised by one or several agencies. This is advertised supply, not vacancy.

Rules (in this order):
  1. same non-null permit_token (the DLD advertising permit number)  -> one cluster, whatever else differs
  2. else same bound register key (or, unbound, the same normalised building name) + same beds_band
     + size within max(3 %, 25 sqft) + price within max(2 %, AED 2,000) + furnished equal where both are present -> one cluster
     (when the building is missing on both sides: lat/lon within 150 m stands in for the building, same other tests)
Clusters are the connected components of those pairwise links (union-find), so A~B and B~C puts A, B, C together.

Writes (lake, one short transaction via lake.retry; refused while the daily chain runs - exit 4, nothing written):
  lst_unit_cluster(run_date, cluster_id, "key", dld_project, building_name, beds_band, n_adverts, n_sources, sources, permits,
                   min_price, max_price, canonical_listing, size_sqft, merged_on)       one row per unit per run_date
  lst_unit_member(run_date, cluster_id, portal, listing_id)                               audit: which advert sits in which unit
  v_lst_supply(run_date, "key", dld_project, building_name, beds_band, units, adverts, sources, adverts_per_unit, median_price,
               median_days_listed)                                                         units = clusters
  data/listings/supply_<district>.json for the districts given (--district, repeatable; default jumeirahvillagecircle, businessbay)

Usage:
  python scripts/lst_dedupe.py [--date YYYY-MM-DD] [--district jumeirahvillagecircle --district businessbay] [--dry]
"""
import argparse, datetime as dt, json, math, os, re, statistics, sys, time

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
import pf_listings as pf  # noqa: E402  (read-only reuse: norm_name, lake_connect, write_lake, chain guard)

OUT = os.path.join(ROOT, "data", "listings")
LOG = os.path.join(ROOT, "logs", "lst_sources.log")
MEASURE = "advertised supply - live rental adverts across N sites, deduplicated to units; not vacancy; research only"
DISTRICT_WORDS = {"jumeirahvillagecircle": ("jumeirah village circle", "jvc"), "businessbay": ("business bay",)}

DDL = [
    """create table if not exists lst_unit_cluster (
        run_date date, cluster_id varchar, "key" varchar, dld_project varchar, building_name varchar, beds_band varchar,
        n_adverts integer, n_sources integer, sources varchar[], permits varchar[], min_price double, max_price double,
        canonical_listing varchar, size_sqft double, merged_on varchar)""",
    """create table if not exists lst_unit_member (run_date date, cluster_id varchar, portal varchar, listing_id varchar)""",
]
VIEW = """create or replace view v_lst_supply as
    select c.run_date, c."key", c.dld_project, c.building_name, c.beds_band,
           count(distinct c.cluster_id) units,
           count(*) adverts,
           count(distinct m.portal) sources,
           round(count(*) * 1.0 / count(distinct c.cluster_id), 2) adverts_per_unit,
           median(s.price) median_price,
           median(c.run_date - cast(s.listed_date as date)) median_days_listed
    from lst_unit_cluster c
    join lst_unit_member m on m.run_date = c.run_date and m.cluster_id = c.cluster_id
    join lst_listing_snapshot s on s.run_date = m.run_date and s.portal = m.portal and s.listing_id = m.listing_id
    group by c.run_date, c."key", c.dld_project, c.building_name, c.beds_band"""


def log(msg):
    line = "%s [dedupe] %s" % (dt.datetime.now().isoformat(timespec="seconds"), msg)
    print(line)
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def district_of(key, community):
    if key and ":" in key and key.split(":")[0] in DISTRICT_WORDS:
        return key.split(":")[0]                               # 'dld:<name>' keys carry no district - fall through to the community text
    low = (community or "").lower().replace("-", " ")
    for d, words in DISTRICT_WORDS.items():
        if any(w in low for w in words):
            return d
    return None


def haversine_m(a, b):
    if None in (a[0], a[1], b[0], b[1]):
        return None
    r = 6371000.0
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dphi, dl = p2 - p1, math.radians(b[1] - a[1])
    h = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def close(a, b, pct, floor):
    if a is None or b is None:
        return False
    return abs(a - b) <= max(pct * max(abs(a), abs(b)), floor)


def composite_match(x, y):
    """Rule 2 for two adverts already in the same (building-or-geo, beds_band) bucket."""
    if not close(x["size_sqft"], y["size_sqft"], 0.03, 25.0):
        return False
    if not close(x["price"], y["price"], 0.02, 2000.0):
        return False
    fx, fy = x["furnished"], y["furnished"]
    if fx and fy and fx.lower() != fy.lower():
        return False
    return True


class UF:
    def __init__(self, n):
        self.p = list(range(n))
        self.why = {}

    def find(self, i):
        while self.p[i] != i:
            self.p[i] = self.p[self.p[i]]
            i = self.p[i]
        return i

    def union(self, i, j, why):
        a, b = self.find(i), self.find(j)
        if a != b:
            self.p[b] = a
            self.why[a] = self.why.get(a) or why
            self.why.pop(b, None) if self.why.get(b) == why else None


def load_rows(con, run_date):
    sql = """select s.portal, s.listing_id, s.building_slug, s.building_name, s.community, s.beds_band, s.price, s.size_sqft,
                    s.furnished, s.lat, s.lon, s.listed_date, s.permit_token, a."key", a.dld_project, l.first_seen
             from lst_listing_snapshot s
             left join lst_building_alias a on a.portal = s.portal and a.building_slug = s.building_slug
             left join lst_listing l on l.portal = s.portal and l.listing_id = s.listing_id
             where s.run_date = ?"""
    cols = ["portal", "listing_id", "building_slug", "building_name", "community", "beds_band", "price", "size_sqft", "furnished",
            "lat", "lon", "listed_date", "permit_token", "key", "dld_project", "first_seen"]
    rows = [dict(zip(cols, r)) for r in con.execute(sql, [run_date]).fetchall()]
    for r in rows:
        r["bkey"] = r["key"] or (("name:" + pf.norm_name(r["building_name"])) if r["building_name"] and pf.norm_name(r["building_name"]) else None)
        r["furnished"] = None if r["furnished"] in (None, "", "None", "null") else str(r["furnished"])
    return rows


def load_spills(run_date):
    """Lake-free rows: every data/listings/<source>/pending_<date>.json (or .written) spilled by lst_sources; buildings bound in
    pure Python (lst_sources.bind_rows). Property Finder rows live only in the lake, so they are absent in this mode."""
    import lst_sources as L
    rows = []
    for src in sorted(os.listdir(OUT)):
        d = os.path.join(OUT, src)
        if not os.path.isdir(d):
            continue
        for fn in ("pending_%s.json" % run_date.isoformat(), "pending_%s.json.written" % run_date.isoformat()):
            p = os.path.join(d, fn)
            if not os.path.exists(p):
                continue
            data = json.load(open(p, encoding="utf-8"))
            snap = data.get("rows", [])
            alias = {a[1]: a for a in L.bind_rows(data.get("portal", src), snap)}
            for r in snap:
                a = alias.get(r.get("building_slug"))
                rows.append({"portal": r["portal"], "listing_id": r["listing_id"], "building_slug": r.get("building_slug"), "building_name": r.get("building_name"),
                             "community": r.get("community"), "beds_band": r.get("beds_band"), "price": r.get("price"), "size_sqft": r.get("size_sqft"),
                             "furnished": r.get("furnished"), "lat": r.get("lat"), "lon": r.get("lon"),
                             "listed_date": dt.datetime.fromisoformat(r["listed_date"]) if r.get("listed_date") else None,
                             "permit_token": r.get("permit_token"), "key": a[7] if a else None, "dld_project": a[5] if a else None, "first_seen": None})
            log("offline: %d rows from %s" % (len(snap), p))
            break
    for r in rows:
        r["bkey"] = r["key"] or (("name:" + pf.norm_name(r["building_name"])) if r["building_name"] and pf.norm_name(r["building_name"]) else None)
        r["furnished"] = None if r["furnished"] in (None, "", "None", "null") else str(r["furnished"])
    return rows


def cluster(rows):
    n = len(rows)
    uf = UF(n)
    # rule 1: permit number
    by_permit = {}
    for i, r in enumerate(rows):
        if r["permit_token"]:
            by_permit.setdefault(r["permit_token"], []).append(i)
    for idxs in by_permit.values():
        for j in idxs[1:]:
            uf.union(idxs[0], j, "permit")
    # rule 2: building (or geo) + beds + size + price + furnished. ANCHORED, not transitive: inside a bucket the adverts are
    # taken oldest first, and a newcomer joins the first existing cluster whose ANCHOR (its oldest advert) it matches on every
    # test. Transitive chaining let 85 same-layout adverts span AED 68k-82k in one "unit" (seen 1 Oct 2026); anchoring keeps
    # every member within 2 % / 3 % of one real advert. Permit links (rule 1) stay transitive - a permit is the unit.
    def when(r):
        v = r["listed_date"] or (dt.datetime.combine(r["first_seen"], dt.time()) if r["first_seen"] else None)
        return v if isinstance(v, dt.datetime) else dt.datetime.max
    buckets = {}
    geo_bucket = {}
    for i, r in enumerate(rows):
        if r["bkey"]:
            buckets.setdefault((r["bkey"], r["beds_band"]), []).append(i)
        else:
            geo_bucket.setdefault(r["beds_band"], []).append(i)

    def anchor_merge(idxs, geo, why):
        idxs = sorted(idxs, key=lambda i: (when(rows[i]), rows[i]["portal"], rows[i]["listing_id"]))
        anchors = []                                           # indexes of cluster anchors in this bucket, oldest first
        for i in idxs:
            x = rows[i]
            joined = False
            for a in anchors:
                if uf.find(a) == uf.find(i):
                    joined = True                              # already together through a permit
                    break
                y = rows[a]
                if geo:
                    d = haversine_m((x["lat"], x["lon"]), (y["lat"], y["lon"]))
                    if d is None or d > 150.0:
                        continue
                if composite_match(x, y):
                    uf.union(a, i, why)
                    joined = True
                    break
            if not joined:
                anchors.append(i)
    for idxs in buckets.values():
        anchor_merge(idxs, False, "composite")
    for idxs in geo_bucket.values():
        anchor_merge(idxs, True, "composite_geo")
    groups = {}
    for i in range(n):
        groups.setdefault(uf.find(i), []).append(i)
    return groups, uf


def build_clusters(rows, run_date):
    groups, uf = cluster(rows)
    clusters, members = [], []
    for root, idxs in groups.items():
        mem = [rows[i] for i in idxs]
        permits = sorted({m["permit_token"] for m in mem if m["permit_token"]})
        # a mixed cluster (permit link + composite link) is labelled by the stronger evidence it contains
        merged_on = "single" if len(mem) == 1 else ("permit" if len(permits) >= 1 and any(
            sum(1 for m in mem if m["permit_token"] == p) > 1 for p in permits) else uf.why.get(root, "composite"))
        canon = sorted(mem, key=lambda m: (m["listed_date"] or m["first_seen"] or dt.datetime.max if isinstance(m["listed_date"] or m["first_seen"], dt.datetime)
                                            else dt.datetime.combine(m["first_seen"], dt.time()) if m["first_seen"] else dt.datetime.max, m["portal"], m["listing_id"]))[0]
        keyed = next((m for m in mem if m["key"]), mem[0])
        prices = [m["price"] for m in mem if m["price"] is not None]
        sizes = [m["size_sqft"] for m in mem if m["size_sqft"] is not None]
        cid = "%s:%s:%s" % (run_date.isoformat(), canon["portal"], canon["listing_id"])
        clusters.append({"run_date": run_date, "cluster_id": cid, "key": keyed["key"], "dld_project": keyed["dld_project"],
                         "building_name": keyed["building_name"] or canon["building_name"], "beds_band": canon["beds_band"],
                         "n_adverts": len(mem), "n_sources": len({m["portal"] for m in mem}), "sources": sorted({m["portal"] for m in mem}),
                         "permits": permits, "min_price": min(prices) if prices else None, "max_price": max(prices) if prices else None,
                         "canonical_listing": "%s:%s" % (canon["portal"], canon["listing_id"]),
                         "size_sqft": statistics.median(sizes) if sizes else None, "merged_on": merged_on,
                         "_district": district_of(keyed["key"], keyed["community"] or canon["community"]), "_members": mem})
        for m in mem:
            members.append((run_date, cid, m["portal"], m["listing_id"]))
    return clusters, members


def supply_rows(clusters, run_date, district):
    groups = {}
    for c in clusters:
        if c["_district"] != district:
            continue
        g = groups.setdefault((c["key"], c["dld_project"], c["building_name"], c["beds_band"]), {"units": 0, "adverts": 0, "by_source": {}, "prices": [], "days": []})
        g["units"] += 1
        g["adverts"] += c["n_adverts"]
        for m in c["_members"]:
            g["by_source"][m["portal"]] = g["by_source"].get(m["portal"], 0) + 1
            if m["price"] is not None:
                g["prices"].append(m["price"])
            if m["listed_date"]:
                ld = m["listed_date"].date() if isinstance(m["listed_date"], dt.datetime) else m["listed_date"]
                g["days"].append((run_date - ld).days)
    out = []
    for (key, proj, bname, band), g in groups.items():
        out.append({"key": key, "dld_project": proj, "building_name": bname, "beds_band": band, "units": g["units"], "adverts": g["adverts"],
                    "by_source": dict(sorted(g["by_source"].items())),
                    "median_price": statistics.median(g["prices"]) if g["prices"] else None,
                    "median_days_listed": statistics.median(g["days"]) if g["days"] else None})
    out.sort(key=lambda r: (-(r["units"]), r["building_name"] or "", r["beds_band"]))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--date", help="run_date (default today)")
    ap.add_argument("--district", action="append", help="our district slug(s) for supply_<district>.json")
    ap.add_argument("--dry", action="store_true", help="cluster and print, write nothing (lake read only)")
    ap.add_argument("--offline", action="store_true", help="no lake at all: rows from data/listings/<source>/pending_<date>.json[.written]; "
                                                            "clusters spilled to data/listings/lst_unit_cluster_pending_<date>.json; supply files written")
    a = ap.parse_args()
    run_date = dt.date.fromisoformat(a.date) if a.date else dt.date.today()
    districts = a.district or ["jumeirahvillagecircle", "businessbay"]
    t0 = time.time()
    if a.offline:
        rows = load_spills(run_date)
    else:
        try:
            con = pf.lake_connect(read_only=True)
        except pf.LakeUnavailable as e:
            log("%s - nothing read or written; re-run after '=== daily done'" % e)
            return 4
        try:
            rows = load_rows(con, run_date)
        finally:
            con.close()
    if not rows:
        log("no lst_listing_snapshot rows for %s" % run_date)
        return 1
    clusters, members = build_clusters(rows, run_date)
    by_portal = {}
    for r in rows:
        by_portal[r["portal"]] = by_portal.get(r["portal"], 0) + 1
    multi = [c for c in clusters if c["n_adverts"] > 1]
    stats = {"run_date": str(run_date), "adverts": len(rows), "by_portal": by_portal, "clusters": len(clusters),
             "clusters_multi_advert": len(multi), "clusters_2plus_sources": sum(1 for c in clusters if c["n_sources"] >= 2),
             "merged_on": {k: sum(1 for c in multi if c["merged_on"] == k) for k in ("permit", "composite", "composite_geo")},
             "adverts_with_permit": sum(1 for r in rows if r["permit_token"]),
             "seconds": round(time.time() - t0, 1)}
    log("dedupe %s: %s" % (run_date, json.dumps(stats)))
    for c in sorted(multi, key=lambda c: -c["n_sources"])[:15]:
        print("  %-40s %-6s n=%d sources=%s permits=%s price %s-%s merged_on=%s" % ((c["building_name"] or "")[:40], c["beds_band"], c["n_adverts"],
              ",".join(c["sources"]), c["permits"], c["min_price"], c["max_price"], c["merged_on"]))
    files = {}
    for d in districts:
        rws = supply_rows(clusters, run_date, d)
        files[d] = {"as_of": str(run_date), "district": d, "measure": MEASURE.replace("N sites", "%d sites" % len(by_portal)),
                    "sources": sorted(by_portal), "n_rows": len(rws),
                    "totals": {"units": sum(r["units"] for r in rws), "adverts": sum(r["adverts"] for r in rws)}, "rows": rws}
    if a.dry:
        for d, f in files.items():
            print(d, json.dumps(f["totals"]), "rows", f["n_rows"])
        return 0
    if a.offline:
        # no lake: clusters and members spilled for a later lake replay; supply files written from memory
        os.makedirs(OUT, exist_ok=True)
        p = os.path.join(OUT, "lst_unit_cluster_pending_%s.json" % run_date.isoformat())
        with open(p, "w", encoding="utf-8") as fh:
            json.dump({"run_date": str(run_date), "stats": stats, "note": "offline dedupe over spill files; Property Finder rows absent (lake only)",
                       "clusters": [{k: v for k, v in c.items() if not k.startswith("_")} for c in clusters],
                       "members": [list(m) for m in members]}, fh, default=str)
        log("offline: %d clusters / %d members spilled to %s (no lake touched)" % (len(clusters), len(members), p))
        for d, f in files.items():
            f["note"] = "offline build from crawl spill files; Property Finder adverts not included until the lake dedupe runs"
            sp = os.path.join(OUT, "supply_%s.json" % d)
            with open(sp, "w", encoding="utf-8") as fh:
                json.dump(f, fh, indent=1, ensure_ascii=False, default=str)
            log("wrote %s: %s" % (sp, json.dumps(f["totals"])))
        return 0
    try:
        con = pf.lake_connect(read_only=False)
    except pf.LakeUnavailable as e:
        log("%s - clusters not written" % e)
        return 4
    try:
        def body():
            for d in DDL:
                con.execute(d)
            con.execute("delete from lst_unit_cluster where run_date = ?", [run_date])
            con.execute("delete from lst_unit_member where run_date = ?", [run_date])
            con.executemany("insert into lst_unit_cluster values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                            [(c["run_date"], c["cluster_id"], c["key"], c["dld_project"], c["building_name"], c["beds_band"], c["n_adverts"], c["n_sources"],
                              c["sources"], c["permits"], c["min_price"], c["max_price"], c["canonical_listing"], c["size_sqft"], c["merged_on"]) for c in clusters])
            con.executemany("insert into lst_unit_member values (?,?,?,?)", members)
            con.execute(VIEW)
        pf.write_lake(con, body, "lst_unit_cluster")
        n = con.execute("select count(*), sum(adverts) from v_lst_supply where run_date = ?", [run_date]).fetchone()
        log("written: %d clusters, %d members; v_lst_supply has %s building-band rows / %s adverts for %s" % (len(clusters), len(members), n[0], n[1], run_date))
    finally:
        con.close()
    os.makedirs(OUT, exist_ok=True)
    for d, f in files.items():
        p = os.path.join(OUT, "supply_%s.json" % d)
        with open(p, "w", encoding="utf-8") as fh:
            json.dump(f, fh, indent=1, ensure_ascii=False, default=str)
        log("wrote %s: %s" % (p, json.dumps(f["totals"])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
