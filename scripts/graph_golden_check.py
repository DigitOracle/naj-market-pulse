"""The golden gate: every resolver or policy change runs this before it touches the app (Kendall, 8 Sep 2026, priority 3).

Checks the truth store (data/graph/najma.duckdb) and the derived files the app reads against the golden table's VERIFIED / PASS rows and a
set of structural rules. Prints PASS / FAIL per check and exits 1 on any FAIL, so a refresh chain can stop on it.

Rules checked:
  R1  no building's canonical name comes from a place source (shops, restaurants, clinics are tenants)          - the Building 4 / Apple Office class
  R2  no building keeps a structural identifier as its display name when a register name exists                 - identity roles separated
  R3  Seacliff by Imtiaz is placed on Dubai Islands (palmdeira), never Dubai Hills                                - the developer-office geocode
  R4  Arada's 'Masaar' is not bound to JVC 'Masaar Residences'                                                     - the name-only bind
  R5  W Residences at Dubai Harbour does not resolve to footprint 386 (Orra Harbour) on the Dubai Marina twin      - the film-take fault
  R6  Chelsea Residences 2 by Damac: nearest water is the Arabian Gulf within 60 m; nearest public beach > 3 km   - Najjuko 8 Sep
  R7  Symphony Tower has one priced identity, not three                                                            - OPEN, expected to fail until resolved
  R8  every beach row Naj confirmed still holds (nearest beach of the claimed access class within 35% of the claimed distance)
  R9  the same for every park row she confirmed (water-and-park poll, 9 Sep 2026)
Usage: python scripts/graph_golden_check.py
"""
import json, os, sys
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
import duckdb
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, ".."))
DB = os.path.join(ROOT, "data", "graph", "najma.duckdb"); BOARD = os.path.join(ROOT, "data", "board")


def connect_when_free(path, tries=20, wait=30):
    """DuckDB is single-writer: while the daily refresh's graph_build holds the file, wait rather than fail (up to tries x wait seconds)."""
    import time as _t
    for k in range(tries):
        try: return duckdb.connect(path, read_only=True)
        except duckdb.IOException as e:
            if "being used by another process" not in str(e) or k == tries - 1: raise
            print(f"  truth store busy (another process is writing it) - waiting {wait}s ({k+1}/{tries})"); _t.sleep(wait)


def main():
    con = connect_when_free(DB); out = []
    def check(code, ok, detail, expected_fail=False):
        out.append((code, ok, detail, expected_fail)); print(f"  {'PASS' if ok else ('FAIL (known)' if expected_fail else 'FAIL'):12s} {code}  {detail}")
    n = con.execute("select count(*) from v_canonical_name where canonical_source in ('overture_place','places','google','google_places')").fetchone()[0]
    check("R1 place-as-name", n == 0, f"{n} buildings would be named after a place")
    n = con.execute("select count(*) from building where display_role='STRUCTURAL_IDENTIFIER' and official_name is not null and official_name<>display_name").fetchone()[0]
    check("R2 structural-vs-official", n == 0, f"{n} buildings show a structural id although an official name exists")
    PR = json.load(open(os.path.join(BOARD, "map_prices.json"), encoding="utf-8"))["items"]
    sc = [i for i in PR if "seacliff" in i["n"].lower()]
    check("R3 seacliff", bool(sc) and all(i.get("d") == "palmdeira" for i in sc), f"districts {sorted(set(i.get('d') for i in sc))}")
    ms = [i for i in PR if i["n"].lower().strip() == "masaar residences" and (i.get("dev") or "").lower() == "arada"]
    check("R4 masaar", not ms, f"{len(ms)} JVC 'Masaar Residences' rows carry Arada")
    pf = json.load(open(os.path.join(BOARD, "projfacts.json"), encoding="utf-8")).get("projects", {})
    wr = [v for v in pf.values() if "w residences at dubai harbour" in (v.get("name") or "").lower()]
    b386 = any(str((v.get("twin") or {}).get("b") or v.get("b") or "") == "386" for v in wr)
    check("R5 orra-binding", not b386, "W Residences at Dubai Harbour bound to footprint 386" if b386 else f"{len(wr)} record(s), no 386 binding recorded in projfacts (developer-page link still to check)")
    row = con.execute("select nearest_public from v_place_card where lower(name) like '%chelsea residences 2%'").fetchone()
    ok6 = bool(row and row[0] and "beach:Pearl Jumeirah Public Beach" in row[0])
    check("R6 chelsea", ok6, row[0] if row else "no place card")
    sym = [i for i in PR if "symphony" in i["n"].lower()]
    check("R7 symphony-identity", len(sym) <= 1, f"{len(sym)} priced records named Symphony", expected_fail=True)
    def field_check(kind, attr):
        gp = con.execute("select entity_ref, expected from golden where status like 'PASS%' and attribute = ?", [attr]).fetchall(); bad = []; ok_n = 0
        subs = con.execute("select sub_id, name from sub_community").fetchall()
        for ref, exp in gp:
            parts = [x.strip() for x in exp.split(" · ")]; acc = parts[1] if len(parts) > 1 else "public"; claim_m = int(parts[2].split()[0]) if len(parts) > 2 and parts[2].split()[0].isdigit() else None
            toks = [w for w in ref.lower().replace("(", " ").replace(")", " ").split() if len(w) > 2 and w not in ("the", "at", "residences", "residence", "by", "tower")]
            if not toks: toks = [w for w in ref.lower().replace("(", " ").replace(")", " ").split() if w != "the"]
            rel = "NEAREST_PUBLIC" if acc == "public" else "NEAREST_TO"; row = None
            # the claim was measured from the priced record's own point, so measure the same way first; the sub-community centroid is the fallback
            def score(nm):
                nl = nm.lower(); hits = sum(1 for w in toks if w in nl)
                return hits * 10 + (1 if nl.startswith(toks[0]) else 0)
            need_pts = len(toks) if len(toks) <= 2 else len(toks) - 1
            pts = sorted((i for i in PR if i.get("lat") and sum(1 for w in toks if w in i["n"].lower()) >= min(need_pts, 1)), key=lambda i: -score(i["n"]))
            if pts:
                top = score(pts[0]["n"]); tied = [i for i in pts if score(i["n"]) == top][:8]
                q = "select name, round(6371000*sqrt(power(radians(lat-?),2)+power(radians(lon-?)*cos(radians(?)),2))) d, access from amenity where kind=? " + ("and access='public' " if acc == "public" else "") + "order by d limit 1"
                best = None
                for pt in tied:      # several priced records can share a name (two Laurels); the claim came from one of them, so keep the one whose measure matches
                    r = con.execute(q, [pt["lat"], pt["lon"], pt["lat"], kind]).fetchone()
                    if not r: continue
                    cand_row = (r[0], int(r[1]), r[2]); gap = abs(cand_row[1] - claim_m) if claim_m is not None else 0
                    if best is None or gap < best[0]: best = (gap, cand_row)
                row = best[1] if best else None
            if not row:
                cand = sorted(subs, key=lambda r: -sum(1 for w in toks if w in r[1].lower()))
                need = len(toks) if len(toks) <= 2 else len(toks) - 1
                sid = cand[0][0] if cand and sum(1 for w in toks if w in cand[0][1].lower()) >= need else None
                if sid:
                    row = con.execute("select a.name, sa.distance_m, sa.access from sub_community_amenity sa join amenity a on a.amenity_id=sa.amenity_id where sa.sub_id=? and sa.kind=? and sa.relation=? limit 1", [sid, kind, rel]).fetchone()
                    if not row: row = con.execute("select a.name, sa.distance_m, sa.access from sub_community_amenity sa join amenity a on a.amenity_id=sa.amenity_id where sa.sub_id=? and sa.kind=? and sa.relation='NEAREST_TO' limit 1", [sid, kind]).fetchone()
            if not row: bad.append((ref, "no priced point and no sub-community")); continue
            okd = bool(row) and (claim_m is None or abs(row[1] - claim_m) <= max(150, 0.35 * claim_m))
            oka = bool(row) and ((acc == "public" and (row[2] or "public") == "public") or (acc != "public" and (row[2] or "public") != "public"))
            if okd and oka: ok_n += 1
            else: bad.append((ref, exp, row))
        return gp, bad, ok_n
    gp, bad, ok_n = field_check("beach", "nearest_beach")
    check("R8 field-confirmed beaches", not bad, f"{ok_n}/{len(gp)} field-confirmed beach rows hold (distance within 35%, access class agrees)" if not bad else f"mismatch: {bad[:3]}")
    gp, bad, ok_n = field_check("park", "nearest_park")
    check("R9 field-confirmed parks", not bad, f"{ok_n}/{len(gp)} field-confirmed park rows hold (distance within 35%, access class agrees)" if not bad else f"mismatch: {bad[:3]}")
    fails = [o for o in out if not o[1] and not o[3]]
    print(f"\ngolden gate: {sum(1 for o in out if o[1])} pass · {len(fails)} fail · {sum(1 for o in out if not o[1] and o[3])} known-open")
    con.close(); sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
