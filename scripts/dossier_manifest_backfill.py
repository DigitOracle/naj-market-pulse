"""Reconcile data/board/dossier_manifest.json against what the push logs say was actually STORED.

The manifest is written by build_building_dossier.py on each confirmed push, but two things make a reconciliation
necessary rather than optional:

  * a batch started before the manifest existed - or any long run already in memory - pushes without recording, so the
    manifest drifts behind the truth and a resume would rebuild work that is already stored.
  * the only trustworthy evidence a dossier reached KV is the worker's own response, which carries bytes, pages and sha.
    This reads exactly that and nothing else. A PDF on disk is not evidence; that assumption is what let seven district
    uploads read as success this morning while the files never left the machine.

  python scripts/dossier_manifest_backfill.py            once
  python scripts/dossier_manifest_backfill.py --watch    every 120 s, for use beside a long run
"""
import glob, json, os, re, sys, time

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
MAN = os.path.join(ROOT, "data", "board", "dossier_manifest.json")
LINE = re.compile(r"pushed (b_[a-z0-9]+_\d+): (\{.*\})")


def sweep():
    try:
        man = json.load(open(MAN, encoding="utf-8"))
    except Exception:
        man = {}
    added = 0
    for lg in glob.glob(os.path.join(ROOT, "logs", "dossiers_*.log")):
        for ln in open(lg, encoding="utf-8", errors="ignore"):
            m = LINE.search(ln)
            if not m or m.group(1) in man:
                continue
            try:
                j = json.loads(m.group(2))
            except Exception:
                j = {}
            man[m.group(1)] = {"bytes": j.get("bytes"), "pages": j.get("pages"), "sha": j.get("sha"), "at": "from-log"}
            added += 1
    if added:
        tmp = MAN + ".tmp"
        json.dump(man, open(tmp, "w", encoding="utf-8"), ensure_ascii=False)
        os.replace(tmp, MAN)
    return len(man), added


def main():
    while True:
        total, added = sweep()
        print("%s manifest %d entries (+%d)" % (time.strftime("%H:%M"), total, added), flush=True)
        if "--watch" not in sys.argv:
            return 0
        time.sleep(120)


if __name__ == "__main__":
    sys.exit(main())
