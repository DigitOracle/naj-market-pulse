"""File PDFs that were supplied by hand into the developer-group pipeline.

The listener's size cap meant some documents never reached disk. Kendall scrolls the group, sends
the file to himself and it lands in Downloads; this puts it where the pipeline already looks, marks
how it got there, extracts it, and reloads the truth store.

Provenance is the point. A file that arrives this way is real data with a different chain of custody
from a listener capture, and dev_doc.supplied_by says which - so an answer can always be traced back
to how the document was obtained.

  python scripts/ingest_dropped.py --list                       what is waiting in Downloads
  python scripts/ingest_dropped.py "Treppan*.pdf"               file every match, extract, reload
  python scripts/ingest_dropped.py "x.pdf" --posted 2026-09-09T15:17:43+04:00
"""
import argparse, datetime as dt, glob, hashlib, io, json, os, shutil, subprocess, sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
DROP = os.path.join(os.path.expanduser("~"), "Downloads")
CAPTURE = r"C:\Dev\azimuth-listener-naj\docs\developer_availability"
GROUP = "DEVELOPER AVAILABILITY"


def sha1(p):
    h = hashlib.sha1()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def known():
    """sha1 of everything already in the capture folder, so a re-drop is a no-op."""
    out = {}
    for f in os.listdir(CAPTURE) if os.path.isdir(CAPTURE) else []:
        if f.lower().endswith(".pdf"):
            out[sha1(os.path.join(CAPTURE, f))] = f
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pattern", nargs="*", help="glob(s) under Downloads, e.g. \"Serenia*.pdf\"")
    ap.add_argument("--posted", help="when it was posted to the group (ISO). Defaults to the file's own mtime.")
    ap.add_argument("--sender", default="", help="who posted it in the group")
    ap.add_argument("--note", default="", help="anything worth recording about where it came from")
    ap.add_argument("--list", action="store_true", help="show candidate PDFs in Downloads and stop")
    ap.add_argument("--no-extract", action="store_true", help="file it, but do not run the extractor or reload")
    a = ap.parse_args()

    if a.list or not a.pattern:
        cands = sorted(glob.glob(os.path.join(DROP, "*.pdf")), key=os.path.getmtime, reverse=True)
        if not cands:
            print("nothing in", DROP)
            return
        have = known()
        for p in cands[:25]:
            mark = "already filed" if sha1(p) in have else "new"
            print("  %-13s %8.1f MB  %s" % (mark, os.path.getsize(p) / 1e6, os.path.basename(p)))
        return

    have = known()
    filed = 0
    for pat in a.pattern:
        matches = glob.glob(pat if os.path.isabs(pat) else os.path.join(DROP, pat))
        if not matches:
            print("no match:", pat)
        for src in matches:
            if not src.lower().endswith(".pdf"):
                print("  skip (not a pdf):", os.path.basename(src))
                continue
            h = sha1(src)
            if h in have:
                print("  already filed:", os.path.basename(src), "->", have[h])
                continue
            when = dt.datetime.fromisoformat(a.posted) if a.posted else dt.datetime.fromtimestamp(os.path.getmtime(src))
            name = os.path.basename(src).replace("/", "_")
            dest = os.path.join(CAPTURE, "%d_%s" % (int(when.timestamp() * 1000), name))
            shutil.copy2(src, dest)
            rec = {"ts": when.astimezone(dt.timezone.utc).isoformat() if when.tzinfo else when.isoformat(),
                   "msg_id": "", "group": GROUP, "sender_name": a.sender, "file_name": name,
                   "bytes": os.path.getsize(dest), "sha1": h,
                   "source": "supplied by hand" + (" - " + a.note if a.note else ""),
                   "captured_at": dt.datetime.now().isoformat(timespec="seconds")}
            io.open(os.path.join(CAPTURE, "manual.jsonl"), "a", encoding="utf-8").write(json.dumps(rec) + "\n")
            have[h] = os.path.basename(dest)
            filed += 1
            print("  filed  %8.1f MB  %s" % (rec["bytes"] / 1e6, os.path.basename(dest)))

    if not filed:
        print("nothing new to file")
        return
    if a.no_extract:
        print("filed only (--no-extract); run extract_avail.py --scan and load_dev_group.py when ready")
        return
    for step in (["extract_avail.py", "--scan"], ["load_dev_group.py"]):
        print("\n$", step[0], *step[1:])
        subprocess.run([sys.executable, os.path.join(HERE, step[0])] + step[1:], cwd=ROOT)


if __name__ == "__main__":
    main()
