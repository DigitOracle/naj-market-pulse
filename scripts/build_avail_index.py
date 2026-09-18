"""Developer-availability index for the board strip (KV img_avail_index) + claimed-units merge for the drill pages.

Reads every data/avail/<developer>_<date>[_auto].json (hand-verified beats _auto for the same developer+date; newest
sheet date wins per developer), then:
  1. pushes img_avail_index = {"updated", "sheets":[{"sheet","note","mapped","d"}]}  (board strip, v68)
  2. for each developer with a drill key, merges claimed availability into drill_<key>:
        claimed = {"as_of", "source", "rooms":[{"r","n","from"}], "detail":[{"p","completion","plan","units":[...]}]}
     (drill_<key> base = registered mix from build_avail_drill.py; we read the current KV copy, patch, push back)
Run after extract_avail.py --scan in the daily refresh. Needs INGEST_TOKEN (listener .env) and READ_KEY for the KV read.
"""
import base64, collections, datetime as dt, glob, json, os, re, sys, urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
AVAIL = os.path.join(ROOT, "data", "avail")
WORKER = "https://azimuth-2.digitalchemy.workers.dev"
DRILL_KEY = {"imtiaz": "imtiaz", "arada": "arada", "beyond": "beyond", "fakhruddin": "fakhruddin", "binghatti": "binghatti", "prestigeone": "prestigeone", "select": "select"}
DEV_NAME = {}   # filename slug -> the developer's own name, filled from each sheet as it is read          # developer slug -> drill_<key>; extend as developers join the group


def env_token(name):
    for line in open(r"C:\Dev\azimuth-listener-naj\.env", encoding="utf-8"):
        if line.startswith(name + "="):
            return line.split("=", 1)[1].strip()
    return os.environ.get(name)


def push(name, obj, tok, timeout=900):          # the upstream here is ~16 KB/s: a 900 KB envelope needs a minute
    raw = json.dumps(obj, ensure_ascii=False).encode()
    body = json.dumps({"imageName": name, "image": base64.b64encode(raw).decode(), "contentType": "application/json"}).encode()
    req = urllib.request.Request(WORKER + "/ingest_market", data=body, method="POST",
                                 headers={"X-Azimuth-Ingest": tok, "Content-Type": "application/json", "User-Agent": "najma-market-pulse/1.0"})
    return json.load(urllib.request.urlopen(req, timeout=timeout))


def unit_count(path):
    """Unit rows in a sheet file. A brochure or floor-plan set parses to zero - it is not inventory."""
    try:
        d = json.load(open(path, encoding="utf-8"))
    except Exception:
        return 0
    return sum(len(p.get("units") or []) for p in d.get("projects") or [])


def held_readings():
    """(sheet file, project) pairs the volume check is holding (data/avail/_held.json, written by avail_volume_check.py).

    13 Sep 2026, Data Spine Phase 1: a reading with under half the units of the one it would replace is held until a later
    sheet agrees, so the board keeps the previous count instead of quietly shrinking. Only the newest reading of a project
    is ever active; a missing or unreadable file holds nothing.
    """
    try:
        d = json.load(open(os.path.join(AVAIL, "_held.json"), encoding="utf-8"))
    except Exception:
        return set()
    return {(h["sheet"], h["project"]) for h in d.get("holds") or [] if h.get("active")}


def latest_sheets():
    held = held_readings()
    best = {}
    for p in glob.glob(os.path.join(AVAIL, "*.json")):
        b = os.path.basename(p)
        if b.startswith("_"):
            continue
        m = re.match(r"([a-z0-9]+)_(\d{4}-\d{2}-\d{2})(_auto)?\.json$", b)
        if not m:
            print("  ! SKIPPED %s - name is not <developer>_<date>.json" % b)   # never again in silence
            continue
        dev, date, auto = m.group(1), m.group(2), bool(m.group(3))
        if held:                                          # 13 Sep 2026: a sheet whose every inventory project is held cannot win
            try:
                _projs = [pr.get("p") for pr in json.load(open(p, encoding="utf-8")).get("projects") or [] if pr.get("units") or pr.get("types")]
            except Exception:
                _projs = []
            if _projs and all((b, x) in held for x in _projs):
                continue
        # 11 Sep 2026: units first. The group posts brochures and floor plans to the same thread as inventory,
        # and those parse to zero units. Ranking on date alone let a render booklet dated later REPLACE a real
        # sheet - Imtiaz's 48 units vanished from the board and from drill_imtiaz the day the Archive plans landed.
        rank = (1 if unit_count(p) else 0, date, 0 if auto else 1)          # inventory beats brochure; then newest date; verified beats auto
        if dev not in best or rank > best[dev][0]:
            best[dev] = (rank, p, auto)
    return {dev: (path, auto) for dev, (rank, path, auto) in best.items()}


def latest_projects():
    """Newest sheet PER PROJECT, unioned per developer.

    12 Sep 2026: these developers post ONE PDF PER PROJECT, on different days, so a developer's
    inventory does not live in a single sheet. Picking one sheet per developer let an 11 Sep
    update covering only Inaura stand in for the whole of Arada - 415 units collapsed to 19, and
    fourteen projects disappeared from the board without a word. Same displacement failure as the
    brochure one fixed on 11 Sep, one layer further out.

    Each project takes its newest appearance and carries its own as_of, so a project that has not
    been re-posted reads as stale rather than vanishing. A project absent from a newer sheet is
    NOT treated as sold out - we cannot tell that apart from "not updated today", and dropping
    real inventory is the worse error.

    Returns {dev: {"projects": [...], "meta": {project: {...}}, "as_of", "auto"}}.
    """
    by_dev = {}
    for p in glob.glob(os.path.join(AVAIL, "*.json")):
        b = os.path.basename(p)
        if b.startswith("_"):
            continue
        m = re.match(r"([a-z0-9]+)_(\d{4}-\d{2}-\d{2})(_auto)?\.json$", b)
        try:
            _d = json.load(open(p, encoding="utf-8"))
        except Exception:
            continue
        if not m:
            # Only a file that IS a sheet is worth a warning - group_links.json is not, and a warning
            # that fires on every run teaches people to stop reading it.
            if isinstance(_d, dict) and "projects" in _d:
                print("  ! SKIPPED %s - a sheet whose name is not <developer>_<date>.json" % b)
            continue
        dev, date, auto = m.group(1), m.group(2), bool(m.group(3))
        # The filename carries a slug ("prestigeone"); the strip should say what the developer is called.
        if isinstance(_d, dict) and _d.get("developer"):
            DEV_NAME[dev] = _d["developer"]
        # inventory means unit rows OR a type-level summary (a broker pack's "Prices & Availability"
        # table). A sheet with neither is a brochure or a floor-plan set and carries nothing.
        if not any((pr.get("units") or pr.get("types")) for pr in _d.get("projects") or []):
            continue
        by_dev.setdefault(dev, []).append(((date, 0 if auto else 1), p, auto, date))

    out = {}
    held = held_readings()                       # 13 Sep 2026: a held reading never overwrites the project's previous one
    for dev, sheets in by_dev.items():
        sheets.sort(key=lambda x: x[0])          # oldest first so a newer sheet overwrites its projects
        projects, meta, came_from = collections.OrderedDict(), {}, {}
        for _rank, path, auto, date in sheets:
            d = json.load(open(path, encoding="utf-8"))
            for pr in d.get("projects") or []:
                if not (pr.get("units") or pr.get("types")):
                    continue
                if (os.path.basename(path), pr["p"]) in held:
                    continue
                name = pr["p"]
                if name in projects and came_from.get(name) == path:
                    # SAME sheet listing a project twice - Fakhruddin posts one PDF per project and
                    # they merge into one day's sheet, so "Treppan Tower" appears more than once.
                    # These are additional units, not a newer reading: overwriting loses them.
                    seen = {tuple(u[:2]) for u in projects[name]["units"]}
                    projects[name]["units"].extend(u for u in pr["units"] if tuple(u[:2]) not in seen)
                else:
                    projects[name] = json.loads(json.dumps(pr))     # copy: we mutate units above
                    came_from[name] = path
                meta[name] = {"as_of": d.get("sheet_date") or date, "auto": auto,
                              "received": d.get("received"), "sheet": os.path.basename(path)}
        if projects:
            out[dev] = {"projects": list(projects.values()), "meta": meta,
                        "as_of": max(m["as_of"] for m in meta.values()),
                        "auto": any(m["auto"] for m in meta.values())}
    return out


def claimed_for_dev(dev):
    """Claimed-availability block for drill_<key>, unioned across this developer's sheets (None if none)."""
    devs = latest_projects()
    if dev not in devs:
        return None                              # brochure only: leave the drill page's existing claimed block alone
    info = devs[dev]
    auto = info["auto"]
    d = {"projects": info["projects"], "sheet_date": info["as_of"],
         "received": max((m.get("received") or "") for m in info["meta"].values()) or None,
         "developer": DEV_NAME.get(dev, dev.title())}
    rooms = collections.OrderedDict()
    for p in d["projects"]:
        for u in p["units"]:
            r = rooms.setdefault(u[1], {"r": u[1], "n": 0, "from": None})
            r["n"] += 1
            if u[3]:
                r["from"] = u[3] if r["from"] is None else min(r["from"], u[3])
    return {"as_of": d.get("sheet_date"), "received": d.get("received"),
            "source": d.get("developer", dev.title()) + (" sheets (auto-read; verify before quoting)" if auto else " sheets"),
            "rooms": list(rooms.values()),
            # each project carries the date of the sheet it came from, so a project nobody has
            # re-posted reads as stale in the app instead of silently passing as today's number
            "detail": [{"p": p["p"], "completion": p.get("completion"), "plan": p.get("plan"),
                        "as_of": info["meta"].get(p["p"], {}).get("as_of"),
                        "units": p["units"]} for p in d["projects"]]}


def main():
    tok = env_token("INGEST_TOKEN")
    read_key = env_token("READ_KEY") or os.environ.get("READ_KEY")
    devs, out = latest_projects(), []
    for dev, info in sorted(devs.items()):
        n_units = sum(len(p.get("units") or []) for p in info["projects"])
        tl = [p for p in info["projects"] if p.get("level") == "type"]
        n_type = sum(sum(t.get("n") or 0 for t in p.get("types") or []) for p in tl)
        if not n_units and not n_type:           # nothing but brochures from this developer
            continue
        key = DRILL_KEY.get(dev)
        # say plainly which part is unit-by-unit and which is only a developer type summary, so the
        # strip never implies we hold 463 units we can actually quote
        note = "%d units · %d projects" % (n_units, len(info["projects"]))
        if n_type:
            note += " · +%d in %d type-level" % (n_type, len(tl))
        out.append({"sheet": "%s %s" % (DEV_NAME.get(dev, dev.title()), info["as_of"]),
                    "note": note + (" · auto-read" if info["auto"] else ""),
                    "mapped": bool(key), "d": key})
    idx = {"updated": dt.date.today().isoformat(), "sheets": out}
    r = push("avail_index", idx, tok)
    print("avail_index ->", r.get("ok"), out)


if __name__ == "__main__":
    main()
