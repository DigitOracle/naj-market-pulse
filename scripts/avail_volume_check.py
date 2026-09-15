"""Hold a developer sheet whose unit count collapses, until a second sheet agrees.

Data Spine Phase 1 (13 Sep 2026). A project's newest reading replaces its previous one on the board (latest_projects in
build_avail_index.py). Twice this month a reading that was not inventory replaced one that was, and nothing errored: a render
brochure parsed to zero units and pushed Imtiaz's 48 off the board (11 Sep), and a one-project update stood in for a whole
developer, 415 units becoming 19 (12 Sep). Both were found by hand, days later. The loaders were fixed for those two shapes;
this check catches the class.

Rule: when a project's reading has fewer than half the units of the reading it would replace, and that reading had at least
ten, the new reading is HELD in data/avail/_held.json. build_avail_index.py skips held readings, so the board keeps the
previous count. A hold releases itself when a later reading of the same project agrees with it (within 25%): two sheets
saying the same thing is inventory selling, not a parse. Units are unit rows, or the type-level counts of a broker pack.

Release by hand:  python scripts/avail_volume_check.py --release <sheet file> "<project>"
Exit 0 = no new hold; 4 = new hold(s) placed, printed as HELD lines for the run ledger; 1 = error.
"""
import argparse, collections, datetime as dt, glob, json, os, re, sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
AVAIL = os.path.join(ROOT, "data", "avail")
HELD = os.path.join(AVAIL, "_held.json")
SHEET_RX = re.compile(r"([a-z0-9]+)_(\d{4}-\d{2}-\d{2})(_auto)?\.json$")

SHRINK = 0.5      # a reading under half the previous one is suspect...
FLOOR = 10        # ...when the previous one was real inventory
AGREE = 0.25      # a later reading within 25% of the held one confirms it


def inventory(pr):
    units = pr.get("units") or []
    if units:
        return len(units)
    return sum(int(t.get("n") or 0) for t in (pr.get("types") or []))


def readings():
    """{(developer, project): [(rank, sheet_file, units), ...]} oldest first, same ranking as latest_projects.

    One sheet can list a project more than once (Fakhruddin posts one PDF per project and a day's PDFs merge into one
    sheet). latest_projects treats the repeats as additional units of the same reading, so they are merged here too:
    distinct unit rows (id, type) plus type-level counts, per (sheet, project).
    """
    merged = {}
    for p in glob.glob(os.path.join(AVAIL, "*.json")):
        b = os.path.basename(p)
        if b.startswith("_"):
            continue
        m = SHEET_RX.match(b)
        if not m:
            continue
        dev, date, auto = m.group(1), m.group(2), bool(m.group(3))
        try:
            d = json.load(open(p, encoding="utf-8"))
        except Exception:
            continue
        for pr in d.get("projects") or []:
            if not pr.get("p") or inventory(pr) <= 0:
                continue                                    # brochures carry nothing; latest_projects ignores them too
            key = (dev, pr["p"], b)
            slot = merged.setdefault(key, {"rank": (date, 0 if auto else 1), "units": set(), "types": 0})
            for u in pr.get("units") or []:
                slot["units"].add(tuple(u[:2]) if isinstance(u, (list, tuple)) else json.dumps(u, sort_keys=True))
            slot["types"] += sum(int(t.get("n") or 0) for t in (pr.get("types") or []))
    out = collections.defaultdict(list)
    for (dev, proj, sheet), slot in merged.items():
        out[(dev, proj)].append((slot["rank"], sheet, len(slot["units"]) or slot["types"]))
    for k in out:
        out[k].sort(key=lambda x: x[0])
    return out


def load_state():
    try:
        return json.load(open(HELD, encoding="utf-8"))
    except Exception:
        return {"holds": [], "released": []}


def evaluate(state):
    released = {(r["sheet"], r["project"]) for r in state.get("released") or []}
    holds = []
    for (dev, proj), rs in readings().items():
        accepted = None
        for i, (rank, sheet, n) in enumerate(rs):
            if accepted is None or (sheet, proj) in released:
                accepted = (rank, sheet, n)
                continue
            prev_n = accepted[2]
            if prev_n >= FLOOR and n < SHRINK * prev_n:
                later = rs[i + 1:]
                if any(abs(l[2] - n) <= AGREE * max(n, 1) for l in later):
                    accepted = (rank, sheet, n)             # a later sheet agrees: this was selling, not a parse
                    continue
                holds.append({"developer": dev, "project": proj, "sheet": sheet, "units": n,
                              "previous_sheet": accepted[1], "previous_units": prev_n,
                              "active": i == len(rs) - 1,     # only the newest reading changes what the board shows
                              "reason": "%s: %s has %d units vs %d in %s" % (proj, sheet, n, prev_n, accepted[1])})
            else:
                accepted = (rank, sheet, n)
    return holds


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--release", nargs=2, metavar=("SHEET", "PROJECT"))
    ap.add_argument("--dry", action="store_true", help="report, do not write _held.json")
    a = ap.parse_args()
    state = load_state()
    now = dt.datetime.now().isoformat(timespec="seconds")

    if a.release:
        sheet, proj = os.path.basename(a.release[0]), a.release[1]
        state.setdefault("released", []).append({"sheet": sheet, "project": proj, "at": now, "by": "hand"})
        state["holds"] = [h for h in state.get("holds") or [] if not (h["sheet"] == sheet and h["project"] == proj)]
        json.dump(state, open(HELD, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print("released %s / %s" % (sheet, proj))
        return 0

    before = {(h["sheet"], h["project"]) for h in state.get("holds") or []}
    holds = evaluate(state)
    for h in holds:
        prior = next((x for x in state.get("holds") or [] if x["sheet"] == h["sheet"] and x["project"] == h["project"]), None)
        h["since"] = prior.get("since", now) if prior else now
    new = [h for h in holds if (h["sheet"], h["project"]) not in before and h["active"]]

    for h in holds:
        print("%s %s/%s" % ("HELD" if h["active"] else "held (superseded)", h["developer"], h["reason"]))
    if not holds:
        print("volume check: no sheet shrank past the threshold")
    if not a.dry:
        state["holds"] = holds
        state["updated"] = now
        state["rule"] = "hold a reading under %d%% of the previous one when that had >= %d units; release when a later reading agrees within %d%%" % (SHRINK * 100, FLOOR, AGREE * 100)
        json.dump(state, open(HELD, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return 4 if new else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception as e:
        print("volume check error:", e)
        sys.exit(1)
