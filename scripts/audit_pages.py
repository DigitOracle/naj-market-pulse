"""Score a district's building pages against the Symphony template (docs/BUILDING_PAGE_TEMPLATE.md).

Kendall, 21 Sep 2026: "these kind of things should not be ad hoc ... that needs to be the template as you roll this out across
all of Dubai." So every district is measured against the one fully-worked building instead of being fixed when something is
noticed missing.

The scoring itself runs in the worker checkout, because it calls the page's own buildingData() - the audit cannot drift from
what the page renders. This wrapper finds that checkout, runs it, and keeps the result with the rest of the district's board
files. If node or the worker checkout is not on this machine the audit is skipped, never fatal: the roll-out carries on.

  python scripts/audit_pages.py businessbay damachills
  python scripts/audit_pages.py --all          every district with a stack on disk
"""
import json, os, subprocess, sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
BOARD = os.path.join(ROOT, "data", "board")
WORKER = os.environ.get("AZIMUTH_WORKER") or r"C:\Dev\azimuth-worker-stack"
AUDIT = os.path.join(WORKER, "test", "audit_building_pages.mjs")

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def run(districts):
    if not os.path.exists(AUDIT):
        return None, "no worker checkout at %s (set AZIMUTH_WORKER)" % WORKER
    env = dict(os.environ, NAJ_DATA=os.path.join(ROOT, "data").replace("\\", "/"))
    try:
        p = subprocess.run(["node", AUDIT] + list(districts), cwd=WORKER, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=30 * 60, env=env)
    except (OSError, subprocess.TimeoutExpired) as e:
        return None, "node: %s" % e
    print((p.stdout or "").strip())
    if p.returncode:
        return None, ((p.stderr or "").strip().splitlines() or ["exit %d" % p.returncode])[-1]
    return True, ""


def table(districts):
    """One line per district, so the roll-out's progress is a coverage figure and not a feeling."""
    rows = []
    for d in districts:
        f = os.path.join(BOARD, "audit_%s.json" % d)
        if not os.path.exists(f):
            continue
        a = json.load(open(f, encoding="utf-8"))
        rows.append((d, a["buildings"], a["median"], a["sections"],
                     sorted(((v["pct"], v["label"]) for v in a["cover"].values()))[:3]))
    if not rows:
        return
    print("\ndistrict                     buildings  median  the three thinnest sections")
    for d, n, med, tot, thin in sorted(rows, key=lambda r: -r[2]):
        print("%-28s %6d   %2d/%d   %s" % (d, n, med, tot, ", ".join("%s %d%%" % (l, p) for p, l in thin)))


def main():
    argv = [a for a in sys.argv[1:] if not a.startswith("--")]
    if "--all" in sys.argv:
        argv = sorted(f[6:-5] for f in os.listdir(BOARD) if f.startswith("stack_") and f.endswith(".json"))
    ds = argv or ["businessbay", "damachills"]
    ok, err = run(ds)
    if not ok:
        print("audit skipped: %s" % err)
    table(ds)
    return 0 if ok else 0   # never fatal: a missing audit must not stop a roll-out


if __name__ == "__main__":
    sys.exit(main())
