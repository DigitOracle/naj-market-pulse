"""Pull open registers straight from data.dubai (Kendall, 7 Sep: "do you have a list of every single hospital in Dubai? if you
don't, this doesn't work").

The portal's own download button calls /o/dda/data-services/dataset-download?datasetId=<id>, which answers with signed CDN links
(valid 10 minutes) to the latest extract. No login, no captcha - the same call the page makes. Each extract is one or more .csv.gz
parts; they are gunzipped into data/registers/<dataset_name>/.

Dataset ids come from the metadata API (/o/c/datasets?search=...); the ones we lean on:
  469182 sheryan_facility_detail          DHA   every licensed health facility, with x/y
  468962 school_search                    KHDA  school search register (private schools)
  463100 dubai_private_schools            KHDA  private schools register (rating, curriculum, location)
  466421 metro_stations                   RTA   Dubai Metro stations with lat/lon
  470037 tram_stations                    RTA   Dubai Tram stations with lat/lon
  467926 public_transportation_stations   RTA   all station types
  463074 dubai_parks_and_beaches_x_and_y  DM    parks and beaches with x/y
  460287 bus_stop_details                 RTA   bus stops (kept for later; not on the map yet)
Usage: python scripts/datadubai_fetch.py [id ...]      (defaults to the list above)
"""
import gzip, io, json, os, shutil, sys, time
import requests
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, ".."))
OUT = os.path.join(ROOT, "data", "registers")
DEFAULT = [469182, 468962, 463100, 466421, 470037, 467926, 463074, 460287]
BASE = "https://data.dubai/o/dda/data-services/dataset-download"


def fetch(ds_id, S):
    r = S.get(BASE, params={"datasetId": ds_id, "page": 1, "pageSize": 5, "sortDir": "desc"}, timeout=120)
    r.raise_for_status()
    j = r.json()
    if not j.get("success"): print(f"  {ds_id}: {j.get('message')}"); return None
    meta = (j.get("data") or {}).get("metadata") or []
    if not meta: print(f"  {ds_id}: no extract files"); return None
    latest = meta[0]                                            # sortDir=desc -> newest folder first
    folder = latest["file_folder"]; name = folder.rsplit("_", 3)[0]
    dest = os.path.join(OUT, name); os.makedirs(dest, exist_ok=True)
    got = []
    for f in latest.get("files", []):
        url = f["file_url"]; fn = url.split("?")[0].rsplit("/", 1)[-1]
        target = os.path.join(dest, fn[:-3] if fn.endswith(".gz") else fn)
        if os.path.exists(target) and os.path.getsize(target) > 0:
            got.append(target); continue
        rr = S.get(url, timeout=600, stream=True); rr.raise_for_status()
        raw = rr.content
        if raw[:2] == bytes([0x1F, 0x8B]):                                  # the CDN often hands the .gz back already inflated
            with gzip.open(io.BytesIO(raw)) as g, open(target, "wb") as o: shutil.copyfileobj(g, o)
        else:
            open(target, "wb").write(raw)
        got.append(target)
    json.dump({"dataset_id": ds_id, "folder": folder, "fetched": time.strftime("%Y-%m-%d %H:%M"), "files": [os.path.basename(g) for g in got]},
              open(os.path.join(dest, "_extract.json"), "w"), indent=1)
    sizes = sum(os.path.getsize(g) for g in got)
    print(f"  {ds_id} {name:<40} {folder.rsplit('_',3)[1]}  {len(got)} file(s)  {sizes//1024:,} KB")
    return dest


def main():
    ids = [int(a) for a in sys.argv[1:]] or DEFAULT
    S = requests.Session(); S.headers["User-Agent"] = "Mozilla/5.0"
    for i in ids:
        try: fetch(i, S)
        except Exception as e: print(f"  {i}: failed {str(e)[:80]}")


if __name__ == "__main__":
    main()
