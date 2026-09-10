"""dda_api_catalogue.py -- which data.dubai datasets have a live API endpoint, and what to call.

The portal's metadata API carries a `dataAPIEndpoints` field per dataset (e.g.
https://apis.data.dubai/open/smart_dubai/smart_dubai_accomodation_health_condition-open-api). This enumerates every dataset,
keeps that endpoint with the title, entity and update frequency, and writes the catalogue the pipeline reads before pulling.

    python scripts/dda_api_catalogue.py            -> data/raw_downloads/dda/api_catalogue.json (+ a printed summary)
"""
import json, os, re, sys, time, urllib.parse, urllib.request

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
OUT = os.path.join(ROOT, "data", "raw_downloads", "dda"); os.makedirs(OUT, exist_ok=True)
H = {"User-Agent": "najma-catalogue/1.0", "Accept": "application/json"}
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass


def log(*a): print(time.strftime("%H:%M:%S"), *a, flush=True)


def get(u, tries=3):
    for k in range(tries):
        try:
            return json.loads(urllib.request.urlopen(urllib.request.Request(u, headers=H), timeout=120).read())
        except Exception as e:
            if k == tries - 1: raise
            log(f"  retry {k+1}: {str(e)[:60]}"); time.sleep(5)


def enumerate_datasets():
    seen = {}
    page = 1
    while True:
        m = get(f"https://data.dubai/o/c/datasets?pageSize=100&page={page}")
        items = m.get("items") or []
        for it in items: seen[it["id"]] = it
        log(f"page {page}: {len(items)} (total {len(seen)})")
        if len(items) < 100: break
        page += 1
    for q in "abcdefghijklmnopqrstuvwxyz":            # the pager stops early on some tenants; sweep for stragglers
        m = get(f"https://data.dubai/o/c/datasets?search={q}&pageSize=100")
        for it in (m.get("items") or []): seen.setdefault(it["id"], it)
    log(f"datasets listed: {len(seen)}")
    return list(seen.values())


def main():
    rows = []
    for it in enumerate_datasets():
        ep = (it.get("dataAPIEndpointsRawText") or it.get("dataAPIEndpoints") or "").strip()
        urls = re.findall(r"https?://[^\s<>\"']+", ep)
        rows.append({
            "id": it.get("id"), "title": (it.get("title") or "").strip(), "organization": (it.get("organization") or "").strip(),
            "themes": it.get("themes"), "classification": it.get("classification"), "format": it.get("format"),
            "frequency": it.get("frequencyOfUpdateToSDP"), "modified": it.get("dateModified"), "endpoints": urls,
            "entity": (urls[0].split("/")[4] if len(urls) and len(urls[0].split("/")) > 5 else ""),
            "dataset": (urls[0].rstrip("/").split("/")[-1] if urls else ""),
            "access": ("open" if urls and "/open/" in urls[0] else ("secure" if urls else "")),
        })
    with_api = [r for r in rows if r["endpoints"]]
    json.dump({"generated": time.strftime("%Y-%m-%dT%H:%M:%S"), "datasets": len(rows), "with_api": len(with_api), "rows": rows},
              open(os.path.join(OUT, "api_catalogue.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    from collections import Counter
    log(f"datasets {len(rows)}, with an API endpoint {len(with_api)}")
    for k, v in Counter(r["entity"] for r in with_api).most_common(30): log(f"   {k:22s} {v}")
    log("wrote " + os.path.join(OUT, "api_catalogue.json"))


if __name__ == "__main__":
    main()
