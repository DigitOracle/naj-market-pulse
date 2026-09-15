"""Contract on the data.dubai portal downloads: a register is complete only when every part the portal publishes is on disk.

Data Spine Phase 1 (13 Sep 2026). The portal splits big registers into parts (units_<stamp>_0001, _0002, _0003) and the first
pull on 9 Sep took one link per dataset, so MANIFEST.json marks several registers "ok" that are a fraction of themselves:
DLD units "ok" at 792,168 rows of three parts, transactions "ok" at one part. Rent contracts failed with a 403 half way and
left a file behind. Nothing downstream could tell a whole register from a third of one.

For every dataset with a file this asks the portal's download endpoint what the NEWEST extract contains (metadata only,
nothing is downloaded) and compares it with what the manifest says is on disk:

  complete     every published part is on disk, and every file on disk ends whole
  partial      fewer parts on disk than the extract publishes, the pull errored after writing a file, or a file is cut
               short (a round download cap, a KML or JSON that never closes, a CSV whose last line has no end)
  behind       complete for the extract it took, but the portal has published a newer one since
  missing      the manifest names files that are not on disk
  unverified   the portal did not answer

Writes data/raw_downloads/dd/CONTRACT.json (MANIFEST.json is left as the pull wrote it). Portal answers are cached for 7 days.
Usage: python scripts/portal_manifest_check.py [--refresh] [--only name,name]
Exit 0 = nothing newly partial or missing; 4 = new partial/missing registers (printed); 1 = error.
"""
import argparse, concurrent.futures as cf, datetime as dt, json, os, re, sys, time, urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
DD = os.path.join(ROOT, "data", "raw_downloads", "dd")
MANIFEST = os.path.join(DD, "MANIFEST.json")
CONTRACT = os.path.join(DD, "CONTRACT.json")
H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) DigitAlchemy-Najma", "Accept": "application/json"}
CACHE_DAYS = 7
STAMP_RX = re.compile(r"(\d{4}-\d{2}-\d{2})")


def published(did, tries=3):
    """Newest extract on the portal: {'stamp', 'date', 'parts', 'csv_bytes'} - parts counted by folder, one per part."""
    url = "https://data.dubai/o/dda/data-services/dataset-download?datasetId=%s&page=1&pageSize=50&sortDir=desc" % did
    for k in range(tries):
        try:
            d = json.load(urllib.request.urlopen(urllib.request.Request(url, headers=H), timeout=90))
            break
        except Exception:
            if k == tries - 1:
                return None
            time.sleep(3 * (k + 1))
    md = ((d.get("data") or {}).get("metadata") or []) if isinstance(d, dict) else []
    folders = {}
    for e in md:
        fo = e.get("file_folder") or ""
        data_files = [f for f in e.get("files") or [] if "schema" not in str(f.get("file_name") or "").lower()]
        if fo and data_files:
            folders[fo] = sum(int(f.get("file_size") or 0) for f in data_files if str(f.get("file_name")).lower().endswith(".csv.gz"))
    if not folders:
        return {"stamp": None, "date": None, "parts": 0, "csv_bytes": 0}
    stamps = sorted({re.sub(r"_\d{4}$", "", fo) for fo in folders}, reverse=True)
    newest = [fo for fo in folders if re.sub(r"_\d{4}$", "", fo) == stamps[0]]
    m = STAMP_RX.search(stamps[0])
    return {"stamp": stamps[0], "date": m.group(1) if m else None, "parts": len(newest),
            "csv_bytes": sum(folders[fo] for fo in newest)}


CAPS = {m * 2**20 for m in (64, 128, 256, 512, 1024, 2048, 4096)}


def cut_short(path):
    """Why a downloaded file looks cut off, or '' when it ends whole. Parts can all be present and one still be a fragment:
    the DM entrances KML of 9 Sep stops at exactly 256 MiB in the middle of a record and was judged complete (found 13 Sep).
    Checked against all 776 files on disk that day: this one file, and no false alarms."""
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as f:
            f.seek(max(0, size - 4096))
            tail = f.read()
    except OSError as e:
        return "unreadable (%s)" % str(e)[:60]
    low, end = path.lower(), tail.rstrip()
    if size in CAPS:
        return "exactly %d MiB, a download cap" % (size // 2**20)
    if low.endswith(".kml") and not end.lower().endswith(b"</kml>"):
        return "the KML never closes"
    if low.endswith(".json") and not end.endswith((b"]", b"}")):
        return "the JSON never closes"
    if low.endswith(".csv") and size and not tail.endswith((b"\n", b"\r")):
        return "the last CSV line has no end"
    if low.endswith(".xlsx") and b"PK\x05\x06" not in tail:
        return "the workbook has no end record"
    return ""


def judge(name, rec, pub):
    files = rec.get("files") or ([rec["file"]] if rec.get("file") else [])
    on_disk = [f for f in files if os.path.exists(os.path.join(ROOT, f))]
    cut = [(os.path.basename(f), why) for f in on_disk for why in [cut_short(os.path.join(ROOT, f))] if why]
    csv_parts = len([f for f in on_disk if f.lower().endswith(".csv")]) or len(on_disk)
    fetched = str(rec.get("fetched") or "")[:10]
    out = {"id": rec.get("id"), "entity": rec.get("entity"), "manifest_status": rec.get("status"), "fetched": fetched,
           "rows_on_disk": rec.get("rows"), "files_listed": len(files), "parts_on_disk": csv_parts}
    if files and not on_disk:
        out.update(status="missing", reason="the manifest lists %d file(s), none is on disk" % len(files))
    elif pub is None:
        out.update(status="partial" if cut else "unverified",
                   reason=("cut short: " + "; ".join("%s (%s)" % c for c in cut[:3])) if cut else "the portal did not answer")
    else:
        out.update(parts_published=pub["parts"], extract=pub["stamp"], extract_date=pub["date"])
        if str(rec.get("status", "")).startswith("error"):
            out.update(status="partial", reason="the pull failed (%s) after writing a file" % rec.get("status"))
        elif cut:
            out.update(status="partial", reason="cut short: " + "; ".join("%s (%s)" % c for c in cut[:3]))
        elif pub["parts"] and csv_parts < pub["parts"]:
            out.update(status="partial", reason="%d of %d parts on disk (%s rows)" % (csv_parts, pub["parts"], f"{rec.get('rows') or 0:,}"))
        elif pub["date"] and fetched and pub["date"] > fetched:
            out.update(status="behind", reason="complete for %s; the portal published %s" % (fetched, pub["date"]))
        else:
            out.update(status="complete", reason="")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true", help="ignore cached portal answers")
    ap.add_argument("--only", default="")
    a = ap.parse_args()
    man = json.load(open(MANIFEST, encoding="utf-8"))
    prev = {}
    if os.path.exists(CONTRACT):
        try:
            prev = json.load(open(CONTRACT, encoding="utf-8")).get("datasets", {})
        except Exception:
            prev = {}
    only = {x.strip() for x in a.only.split(",") if x.strip()}
    todo = {n: r for n, r in man.items() if r.get("id") and (r.get("file") or r.get("files")) and (not only or n in only)}
    today = dt.date.today()

    def fetch(item):
        n, r = item
        p = prev.get(n) or {}
        try:
            fresh = (today - dt.date.fromisoformat(p.get("checked", "")[:10])).days <= CACHE_DAYS
        except Exception:
            fresh = False
        if fresh and not a.refresh and p.get("status") != "unverified" and "parts_published" in p:
            return n, {"stamp": p.get("extract"), "date": p.get("extract_date"), "parts": p.get("parts_published"), "csv_bytes": None}
        return n, published(r["id"])

    pubs = {}
    with cf.ThreadPoolExecutor(max_workers=4) as ex:
        for n, pub in ex.map(fetch, todo.items()):
            pubs[n] = pub

    datasets = dict(prev) if only else {}
    now = dt.datetime.now().isoformat(timespec="seconds")
    for n, r in todo.items():
        j = judge(n, r, pubs.get(n))
        j["checked"] = now if (pubs.get(n) is None or pubs[n].get("csv_bytes") is not None) else (prev.get(n) or {}).get("checked", now)
        datasets[n] = j

    summary = {}
    for j in datasets.values():
        summary[j["status"]] = summary.get(j["status"], 0) + 1
    json.dump({"checked": now, "summary": summary, "datasets": datasets}, open(CONTRACT, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)

    bad = [(n, j) for n, j in sorted(datasets.items()) if j["status"] in ("partial", "missing")]
    new = [(n, j) for n, j in bad if (prev.get(n) or {}).get("status") not in ("partial", "missing")]
    for n, j in bad:
        print("%s %s: %s" % ("PARTIAL" if (n, j) in new else "still partial", n, j["reason"]))
    print("portal contract: %d registers - %s" % (len(datasets), ", ".join("%d %s" % (v, k) for k, v in sorted(summary.items()))))
    return 4 if new else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception as e:
        print("portal contract error:", e)
        sys.exit(1)
