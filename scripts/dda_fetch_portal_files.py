"""dda_fetch_portal_files.py -- pull the KML / file-type datasets the governed API can't serve, straight from the public
data.dubai portal (29 Sep 2026).

Why. 19 catalogue datasets (rta_bicycle_tracks, rta_bus_routes_gis, dm_community, ... - see PORTAL_DATASETS below) are
published as KML geometry or a plain text file, not tabular rows. dda_pull_all.py always calls
{DDA_BASE_URL}/secure/ddads/openapi/1.0.0/{entity}/{dataset}, the paginated row-API - and the gateway returns a clean
"Dataset ... not found" for these ids on that path, because they were never provisioned there at all (confirmed 29 Sep
by testing both the row-API path and the catalogue's own listed /open/ endpoint - both 404 the same way).

They ARE public: the data.dubai portal page for each dataset has an ordinary Download button with no login, serving a
JSON manifest of dated snapshots (one .kml.gz per day the source was refreshed) from data.dubai/o/dda/data-services/
dataset-download?datasetId=<id>, each entry a pre-signed S3/CloudFront URL valid ~10 minutes. No DDA bearer token, no
credentials file, nothing from dda_api.py - this is a different, unauthenticated delivery path entirely.

Usage:
    python scripts/dda_fetch_portal_files.py test                  # the one dataset used to prove this out
    python scripts/dda_fetch_portal_files.py <catalogue_id>        # any single dataset by its data.dubai numeric id
    python scripts/dda_fetch_portal_files.py all                   # every dataset in PORTAL_DATASETS

Writes data/raw_downloads/dda/prod/<entity>__<dataset>.kml (or .txt) plus a .meta.json sidecar recording the source
snapshot date, the portal dataset id, and every snapshot date seen (the archive is often stale - bicycle_tracks's
newest available snapshot on 29 Sep 2026 was 2025-11-21, five months old, well before the portal's own "last updated"
label on the page, which tracks something else). Never overwrites a newer local file with an older portal snapshot.
"""
import gzip, io, json, os, sys, time, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
OUT = os.path.join(ROOT, "data", "raw_downloads", "dda", "prod")
META_URL = "https://data.dubai/o/dda/data-services/dataset-download?datasetId={id}&page=1&pageSize=500&sortDir=desc"

# catalogue id -> (entity, dataset, output extension). Ids and dataset keys from data/raw_downloads/dda/api_catalogue.json,
# 29 Sep 2026. All 19 datasets that 404 on the governed row-API because they are KML or plain-text files, not row data.
PORTAL_DATASETS = {
    459305: ("rta", "rta_bicycle_tracks-open-api", "kml"),
    460273: ("rta", "rta_bus_routes_gis-open-api", "kml"),
    460317: ("rta", "rta_bus_stops_gis-open-api", "kml"),
    466389: ("rta", "rta_metro_lines_gis-open-api", "kml"),
    469997: ("rta", "rta_tram_lines_gis-open-api", "kml"),
    470057: ("rta", "rta_tram_stations_gis-open-api", "kml"),
    467998: ("rta", "rta_rail_tracks-open-api", "kml"),
    467990: ("rta", "rta_rail_parking-open-api", "kml"),
    466259: ("rta", "rta_marine_stations_gis-open-api", "kml"),
    465648: ("rta", "rta_major_roads-open-api", "kml"),
    468872: ("rta", "rta_salik_tolling_gates_location-open-api", "kml"),
    466547: ("rta", "rta_nol_machines-open-api", "kml"),
    466551: ("rta", "rta_nol_metro_card_sales_merchant_locations-open-api", "kml"),
    468860: ("rta", "rta_rta_customer_service_centers-open-api", "kml"),
    461494: ("dm", "dm_community-open-api", "kml"),
    469026: ("dm", "dm_sectors-open-api", "kml"),
    462928: ("dm", "dm_dmgisnet_enterances-open-api", "kml"),
    702218851: ("esource", "esource_construction_cost_index_by_central_product_classification_2019_100-open-api", "txt"),
    466403: ("rta", "rta_metro_ridership-open-api", "txt"),
    469979: ("dp", "dp_traffic_incidents-open-api", "csv"),  # tabular in the catalogue but 6x 408 on the row-API 29 Sep; portal fallback
}


def log(*a):
    print(time.strftime("%Y-%m-%d %H:%M:%S"), *a, flush=True)


def find_id(entity, dataset):
    """Look up a dataset's numeric portal id from the catalogue we already pull, so PORTAL_DATASETS can be filled in
    without guessing ids by hand."""
    cat = json.load(open(os.path.join(ROOT, "data", "raw_downloads", "dda", "api_catalogue.json"), encoding="utf-8"))
    for r in cat["rows"]:
        if r.get("entity") == entity and r.get("dataset") == dataset:
            return r["id"]
    return None


def fetch_meta(dataset_id):
    req = urllib.request.Request(META_URL.format(id=dataset_id), headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as h:
        return json.load(h)


def fetch_one(catalogue_id, entity, dataset, ext):
    meta = fetch_meta(catalogue_id)
    if not meta.get("success"):
        log(f"{dataset}: portal metadata call failed: {meta}"); return False
    rows = meta["data"]["metadata"]
    if not rows:
        log(f"{dataset}: portal has no snapshots at all"); return False
    all_dates = sorted(r["file_folder"] for r in rows)
    latest = max(rows, key=lambda r: r["file_folder"])
    file_info = latest["files"][0]
    url = file_info["file_url"]
    fn = file_info["file_name"]
    log(f"{dataset}: {len(rows)} snapshots on the portal, {all_dates[0]} .. {all_dates[-1]}, fetching latest ({fn})")

    out_path = os.path.join(OUT, f"{entity}__{dataset}.{ext}")
    meta_path = out_path + ".meta.json"
    if os.path.exists(meta_path):
        prev = json.load(open(meta_path, encoding="utf-8"))
        if prev.get("snapshot") and prev["snapshot"] >= latest["file_folder"]:
            log(f"{dataset}: local copy ({prev['snapshot']}) is already this snapshot or newer - skipped"); return True

    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=60) as h:
        raw = h.read()
    if fn.endswith(".gz"):
        raw = gzip.decompress(raw)
    os.makedirs(OUT, exist_ok=True)
    tmp = out_path + f".{os.getpid()}.tmp"
    open(tmp, "wb").write(raw)
    os.replace(tmp, out_path)
    json.dump({"portal_dataset_id": catalogue_id, "entity": entity, "dataset": dataset, "snapshot": latest["file_folder"],
               "fetched": time.strftime("%Y-%m-%dT%H:%M:%S"), "bytes": len(raw), "snapshots_available": len(rows),
               "earliest_available": all_dates[0], "latest_available": all_dates[-1],
               "source": "data.dubai public portal download (unauthenticated), not the DDA governed API"},
              open(meta_path, "w", encoding="utf-8"), indent=1)
    log(f"{dataset}: wrote {out_path} ({len(raw):,} bytes, snapshot {latest['file_folder']})")
    return True


def main():
    if len(sys.argv) < 2:
        sys.exit("usage: dda_fetch_portal_files.py test | <catalogue_id> | all")
    arg = sys.argv[1]
    if arg == "test":
        cid, (entity, dataset, ext) = 459305, PORTAL_DATASETS[459305]
        fetch_one(cid, entity, dataset, ext)
    elif arg == "all":
        for cid, (entity, dataset, ext) in PORTAL_DATASETS.items():
            fetch_one(cid, entity, dataset, ext)
    else:
        cid = int(arg)
        if cid not in PORTAL_DATASETS:
            sys.exit(f"{cid} not in PORTAL_DATASETS - add it (entity, dataset, ext) first")
        entity, dataset, ext = PORTAL_DATASETS[cid]
        fetch_one(cid, entity, dataset, ext)


if __name__ == "__main__":
    main()
