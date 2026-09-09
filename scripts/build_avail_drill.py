"""Per-project drill data for the availability strip -> KV drill_<slug>.
Registered sales mix by rooms + prices, straight from DuckDB. Developer-claimed
availability joins the same JSON when PDF extraction lands (kept separate)."""
import base64, datetime as dt, json, os, re, sys, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_avail_index import claimed_for_dev   # claimed units from the newest developer sheet (extract_avail.py)

HERE = os.path.dirname(os.path.abspath(__file__))
slug = lambda s: re.sub(r"[^a-z0-9]", "", str(s).lower())

TARGETS = [
    ("treppantower",     "PROJECT_EN = 'TREPPAN TOWER'",                       "Treppan Tower"),
    ("treppanserenique", "PROJECT_EN = 'TREPPAN SERENIQUE RESIDENCES'",        "Treppan Serenique"),
    ("maimoongardens",   "PROJECT_EN = 'Maimoon Gardens'",                     "Maimoon Gardens"),
    ("hatimiresidences", "PROJECT_EN = 'HATIMI RESIDENCES BY FAKHRUDDIN'",     "Hatimi Residences"),
    ("imtiaz",           "lower(PROJECT_EN) LIKE '%imtiaz%'",                  "Imtiaz (all projects)"),
    # 8 Sep 2026: the developer group now carries Arada and Beyond sheets; /avail?d=<dev> read drill_<dev> and found nothing
    ("arada",            "(lower(PROJECT_EN) LIKE '%inaura%' OR lower(PROJECT_EN) LIKE '%akala%' OR lower(PROJECT_EN) LIKE '%w residences at dubai harbour%')", "Arada (Dubai projects)"),
    ("beyond",           "(lower(PROJECT_EN) LIKE '%soulever%' OR lower(PROJECT_EN) LIKE '%kanyon%' OR lower(PROJECT_EN) LIKE '%talea%' OR lower(PROJECT_EN) LIKE '%hado%' OR lower(PROJECT_EN) LIKE '%passo%' OR lower(PROJECT_EN) LIKE '%le chateau%')", "Beyond (all projects)"),
    ("fakhruddin",       "(PROJECT_EN IN ('TREPPAN TOWER','TREPPAN SERENIQUE RESIDENCES','Maimoon Gardens','HATIMI RESIDENCES BY FAKHRUDDIN'))", "Fakhruddin (all projects)"),
]

def main():
    import duckdb
    con = duckdb.connect(os.path.join(HERE, "..", "naj.duckdb"), read_only=True)
    tok = next(l.split("=",1)[1].strip() for l in open(r"C:\Dev\azimuth-listener-naj\.env") if l.startswith("INGEST_TOKEN="))
    for key, where, title in TARGETS:
        rooms = con.execute(f"""
            SELECT COALESCE(NULLIF(TRIM(ROOMS_EN),''),'Other') r, COUNT(*) n,
                   MEDIAN(TRY_CAST(TRANS_VALUE AS DOUBLE)) med,
                   MEDIAN(TRY_CAST(TRANS_VALUE AS DOUBLE)/NULLIF(TRY_CAST(ACTUAL_AREA AS DOUBLE),0)) psm
            FROM transactions WHERE {where} AND PROCEDURE_EN LIKE 'Sell%'
            GROUP BY 1 ORDER BY n DESC""").fetchall()
        latest = con.execute(f"""
            SELECT substr(INSTANCE_DATE,1,10), ROOMS_EN, TRY_CAST(ACTUAL_AREA AS DOUBLE),
                   TRY_CAST(TRANS_VALUE AS DOUBLE), PROJECT_EN, AREA_EN
            FROM transactions WHERE {where} AND PROCEDURE_EN LIKE 'Sell%'
            ORDER BY INSTANCE_DATE DESC LIMIT 4""").fetchall()
        district = latest[0][5] if latest else ""
        d = {"title": title, "district": district, "updated": "2026-09-01",
             "rooms": [{"r": r, "n": n, "med": round(med) if med else None,
                        "psm": round(psm) if psm else None} for r, n, med, psm in rooms if n > 0],
             "latest": [{"d": a, "r": b, "m2": round(c,1) if c else None, "aed": round(e) if e else None,
                         "p": f} for a, b, c, e, f, _ in latest],
             "sheet": {"received": "2026-09-01", "status": "sheet on file — unit availability after extraction"}}
        d["updated"] = dt.date.today().isoformat()
        cl = claimed_for_dev(key)
        if cl:
            d["claimed"] = cl
            d["sheet"] = {"received": cl.get("received"), "status": "claimed units merged from %s" % cl["source"]}
        raw = json.dumps(d, ensure_ascii=False).encode()
        body = json.dumps({"imageName": "drill_" + key, "image": base64.b64encode(raw).decode(),
                           "contentType": "application/json"}).encode()
        req = urllib.request.Request("https://azimuth-2.digitalchemy.workers.dev/ingest_market", data=body,
            headers={"X-Azimuth-Ingest": tok, "Content-Type": "application/json",
                     "User-Agent": "najma-market-pulse/1.0"}, method="POST")
        r = json.load(urllib.request.urlopen(req, timeout=60))
        print(key, "->", r.get("ok"), f"({sum(x['n'] for x in d['rooms'])} sales, {len(d['rooms'])} room types)")

if __name__ == "__main__":
    main()
