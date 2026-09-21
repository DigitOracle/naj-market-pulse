"""Roll the building page out across Dubai, district by district (Kendall, 21 Sep 2026: "this needs to be implemented for all of
Dubai, district by district ... a roadmap that will run continuously").

Every district on the twin's rail already has what the chain needs: unitmix, footprints, anchors and Ejari. The extra cuts the
DDA session made for Business Bay and DAMAC Hills (schools, projects, land registry, Makani, permits, id-derived names) are read
where they exist and skipped where they do not, so a district ships with whatever is true for it today and gains the rest when
its cut lands.

The order matters and is not per district: the two registers are scanned ONCE for every district in the run, because each scan
reads gigabytes.

  1  stack        scripts/build_floor_stack.py <all>     the DM floor register, one pass
  2  views        scripts/build_view_openness.py <all>   open sides, merged into the stack
  3  links        scripts/build_scheme_links.py <all>    rents, projects, plot, Makani, sales, permits, names, schools
  4  units        scripts/build_unit_level.py <all>      the DLD units register, one pass over 3.1 GB
  5  plates       scripts/build_floor_plates.py <one>    per district (shapely, slower, so it is chunked)
  6  publish      stacks + units + plates to the app

State is kept in data/board/_rollout_state.json: a district that finished a step is not redone, so the run resumes where it
stopped. A step that fails is recorded with its error and the run CONTINUES to the next district - a roadblock never stops the
roll-out, it becomes a line in the state file and in the roadmap's table.

  python scripts/rollout_districts.py                 every district on the rail, resuming
  python scripts/rollout_districts.py --only a,b      just these
  python scripts/rollout_districts.py --from plates   start at a step
  python scripts/rollout_districts.py --dry           say what it would do
"""
import json, os, re, subprocess, sys, time, urllib.request

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
BOARD = os.path.join(ROOT, "data", "board")
SCRIPTS = os.path.join(ROOT, "scripts")
STATE = os.path.join(BOARD, "_rollout_state.json")
LOG = os.path.join(ROOT, "logs", "rollout_%s.log" % time.strftime("%Y%m%d_%H%M"))
APP = os.environ.get("AZIMUTH_URL", "https://azimuth-2.digitalchemy.workers.dev")
STEPS = ["stack", "views", "links", "units", "plates", "publish", "audit"]
UNITS_FILE = os.path.join(ROOT, "data", "raw_downloads", "dda", "prod", "dld__dld_units-open-api.ndjson")

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def say(*a):
    line = " ".join(str(x) for x in a)
    print(line, flush=True)
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(time.strftime("%H:%M:%S ") + line + "\n")


def state():
    if os.path.exists(STATE):
        try:
            return json.load(open(STATE, encoding="utf-8"))
        except ValueError:
            pass
    return {"districts": {}, "started": time.strftime("%Y-%m-%d %H:%M")}


def save(st):
    st["updated"] = time.strftime("%Y-%m-%d %H:%M")
    json.dump(st, open(STATE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def rail():
    """Every district the twin can draw, from the rail the skyline page builds - there is no point plating a district with no model."""
    sys.path.insert(0, SCRIPTS)
    import demo_capture as dc
    h = urllib.request.urlopen(urllib.request.Request(APP + "/skyline/businessbay?key=" + dc.key(),
                                                      headers={"User-Agent": "najma-market-pulse/1.0"}), timeout=120).read().decode("utf-8", "replace")
    m = re.search(r"var RAIL=(\[.*?\]),CUR=", h, re.S)
    return sorted({x["s"] for x in json.loads(m.group(1))}) if m else []


def run(cmd, tag, minutes=90):
    t0 = time.time()
    say("  ->", tag)
    try:
        p = subprocess.run([sys.executable] + cmd, cwd=ROOT, capture_output=True, text=True, timeout=minutes * 60)
    except subprocess.TimeoutExpired:
        say("     TIMEOUT after %d min" % minutes)
        return False, "timeout"
    out = (p.stdout or "").strip().splitlines()
    for line in out[-6:]:
        say("     " + line)
    if p.returncode != 0:
        err = (p.stderr or "").strip().splitlines()
        for line in err[-4:]:
            say("     ! " + line)
        return False, (err[-1] if err else "exit %d" % p.returncode)
    say("     done in %.0fs" % (time.time() - t0))
    return True, ""


def ready(d):
    return (os.path.exists(os.path.join(BOARD, "unitmix_%s.json" % d))
            and os.path.exists(os.path.join(ROOT, "data", "ce", d, "buildings.geojson"))
            and os.path.exists(os.path.join(ROOT, "data", "names", "anchors_%s.json" % d)))


def main():
    argv = sys.argv[1:]
    dry = "--dry" in argv
    only = None
    if "--only" in argv:
        only = [x.strip() for x in argv[argv.index("--only") + 1].split(",") if x.strip()]
    first = argv[argv.index("--from") + 1] if "--from" in argv else STEPS[0]
    st = state()
    ds = only or rail()
    todo = [d for d in ds if ready(d)]
    skip = [d for d in ds if d not in todo]
    say("rollout: %d districts on the rail, %d ready, %d without inputs%s"
        % (len(ds), len(todo), len(skip), (" (%s)" % ", ".join(skip[:6])) if skip else ""))
    if dry:
        for d in todo:
            say("   ", d, st["districts"].get(d, {}).get("steps", {}))
        return

    # --- the two heavy registers, scanned once for everything in this run -------------------------------------------------
    stage = STEPS.index(first)
    batch = [d for d in todo if "stack" not in (st["districts"].get(d, {}).get("steps") or {})] if stage == 0 else []
    if stage <= 0 and batch:
        ok, err = run([os.path.join(SCRIPTS, "build_floor_stack.py")] + batch, "stack x%d" % len(batch), 120)
        for d in batch:
            st["districts"].setdefault(d, {}).setdefault("steps", {})["stack"] = "ok" if ok else err
        save(st)
    if stage <= 1:
        b = [d for d in todo if os.path.exists(os.path.join(BOARD, "stack_%s.json" % d))]
        if b:
            ok, err = run([os.path.join(SCRIPTS, "build_view_openness.py")] + b, "views x%d" % len(b), 60)
            for d in b:
                st["districts"].setdefault(d, {}).setdefault("steps", {})["views"] = "ok" if ok else err
            save(st)
    if stage <= 2:
        b = [d for d in todo if os.path.exists(os.path.join(BOARD, "stack_%s.json" % d))]
        if b:
            ok, err = run([os.path.join(SCRIPTS, "build_scheme_links.py")] + b, "links x%d" % len(b), 60)
            for d in b:
                st["districts"].setdefault(d, {}).setdefault("steps", {})["links"] = "ok" if ok else err
            save(st)
    if stage <= 3 and os.path.exists(UNITS_FILE):
        b = [d for d in todo if os.path.exists(os.path.join(BOARD, "stack_%s.json" % d))]
        if b:
            ok, err = run([os.path.join(SCRIPTS, "build_unit_level.py"), UNITS_FILE] + b, "units x%d" % len(b), 120)
            for d in b:
                st["districts"].setdefault(d, {}).setdefault("steps", {})["units"] = "ok" if ok else err
            save(st)

    # --- per district from here: shapely is slow, and one district failing must not take the rest with it ------------------
    for d in todo:
        sd = st["districts"].setdefault(d, {}).setdefault("steps", {})
        if stage <= 4 and sd.get("plates") != "ok":
            ok, err = run([os.path.join(SCRIPTS, "build_floor_plates.py"), d], "plates %s" % d, 60)
            sd["plates"] = "ok" if ok else err
            save(st)
        if stage <= 5 and sd.get("publish") != "ok":
            ok1, e1 = run([os.path.join(SCRIPTS, "build_view_openness.py"), d, "--push"], "publish stack %s" % d, 30)
            ok2, e2 = (True, "")
            if os.path.exists(os.path.join(BOARD, "units_%s.json" % d)):
                ok2, e2 = run([os.path.join(SCRIPTS, "push_units.py"), d, "--push"], "publish units %s" % d, 30) if os.path.exists(os.path.join(SCRIPTS, "push_units.py")) else (True, "")
            ok3, e3 = run([os.path.join(SCRIPTS, "push_plates.py"), d, "--push"], "publish plates %s" % d, 60)
            sd["publish"] = "ok" if (ok1 and ok2 and ok3) else "; ".join(x for x in (e1, e2, e3) if x)
            save(st)
        # the district is scored against the Symphony template, so what is thin is reported rather than noticed later
        if stage <= 6 and sd.get("audit") != "ok":
            ok, err = run([os.path.join(SCRIPTS, "audit_pages.py"), d], "audit %s" % d, 30)
            a = os.path.join(BOARD, "audit_%s.json" % d)
            if ok and os.path.exists(a):
                try:
                    j = json.load(open(a, encoding="utf-8"))
                    sd["audit"] = "ok"
                    sd["score"] = "%d/%d over %d buildings" % (j["median"], j["sections"], j["buildings"])
                    sd["thin"] = [v["label"] for v in sorted(j["cover"].values(), key=lambda v: v["pct"])[:3] if v["pct"] < 60]
                    if j.get("drift"):
                        sd["drift"] = j["drift"][:3]
                except (ValueError, KeyError) as e:
                    sd["audit"] = "unreadable audit: %s" % e
            else:
                sd["audit"] = err or "no audit written"
            save(st)
        say("%-26s %s" % (d, json.dumps(sd)))
    done = sum(1 for d in todo if (st["districts"].get(d, {}).get("steps") or {}).get("publish") == "ok")
    say("rollout: %d of %d districts published" % (done, len(todo)))
    save(st)


if __name__ == "__main__":
    main()
