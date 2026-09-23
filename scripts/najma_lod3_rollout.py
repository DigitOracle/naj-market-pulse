"""Roll LOD 3 out across every district, letting each district's own measurement pick its architecture.

Two districts, measured today, wanted opposite things:

  businessbay   654 buildings,  8,974 storeys   17 towers alone = 6.49 MB gz   -> per-building payloads
  damachills  1,006 buildings,  4,231 storeys   ALL 1006 = 4.80 MB gz          -> LOD 3 in the tile

The cost is STOREYS, not buildings. So there is no single right threshold, and guessing one from a single
measurement is how the first cost model went wrong. Instead: build every district at LOD 3 once, measure the
gzipped size, and let that decide.

  fits the 5 MB cap  ->  promote to the live tile (sky_<slug>), whole district at LOD 3
  over the cap       ->  leave the live LOD 1 tile alone and split the heavy buildings out of the SAME build
                         as bld3_<slug>_<bid> payloads plus a bld3_index_<slug>

One generate serves both routes, so nothing is rebuilt to change its mind.

Districts run cheapest-first by storey count, so results stream early and the five expensive ones land last.
State in data/ce/_lod3_state.json; --resume skips districts already decided.

  python scripts/najma_lod3_rollout.py --all
  python scripts/najma_lod3_rollout.py --all --resume
  python scripts/najma_lod3_rollout.py --all --dry-run
  python scripts/najma_lod3_rollout.py businessbay dubaimarina --min-tris 5000
"""
import glob
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import najma_build_all as B  # noqa: E402

ROOT = B.ROOT
STATE = os.path.join(ROOT, "data", "ce", "_lod3_state.json")
PY = sys.executable or "python"


def flag(n):
    return n in sys.argv


def opt(n, d=None, cast=str):
    return cast(sys.argv[sys.argv.index(n) + 1]) if n in sys.argv else d


def storeys(slug):
    p = os.path.join(ROOT, "data", "ce", slug, "report_v3.json")
    try:
        return sum(int(r.get("storeys") or 0) for r in json.load(open(p, encoding="utf-8"))["rows"])
    except Exception:
        return 10 ** 9      # unknown cost sorts last rather than pretending it is cheap


def load():
    try:
        return json.load(open(STATE, encoding="utf-8"))
    except Exception:
        return {}


def save(st):
    tmp = STATE + ".tmp"
    json.dump(st, open(tmp, "w", encoding="utf-8"), indent=1)
    os.replace(tmp, STATE)


def run(cmd, timeout=None):
    p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, errors="ignore", timeout=timeout)
    return p.returncode, ((p.stdout or "") + (p.stderr or "")).strip()


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    min_tris = opt("--min-tris", 5000, int)
    if flag("--all"):
        todo = sorted({p.split(os.sep)[-2] for p in glob.glob(os.path.join(ROOT, "data", "ce", "*", "report_v3.json"))})
    else:
        todo = args
    if not todo:
        print(__doc__)
        return 2
    todo.sort(key=storeys)

    st = load()
    if flag("--resume"):
        skip = [d for d in todo if st.get(d, {}).get("route")]
        todo = [d for d in todo if d not in skip]
        if skip:
            B.log("resume: skipping %d already decided" % len(skip))

    B.log("LOD 3 rollout: %d districts, cheapest first" % len(todo))
    for d in todo:
        B.log("   %-28s %7d storeys" % (d, storeys(d)))
    if flag("--dry-run"):
        B.log("dry run - nothing executed")
        return 0

    t0 = time.time()
    tile, hero, failed = [], [], []
    for n, slug in enumerate(todo, 1):
        B.log("=== [%d/%d] %s (%d storeys)" % (n, len(todo), slug, storeys(slug)))
        log_path = os.path.join(ROOT, "logs", "lod3_%s.log" % slug)
        t = time.time()
        with open(log_path, "w", encoding="utf-8") as fh:
            rc = subprocess.Popen([PY, "scripts/ce_batch_v2.py", "--v4", slug, "--lod", "3"],
                                  cwd=ROOT, stdout=fh, stderr=subprocess.STDOUT, text=True).wait()
        gen_min = (time.time() - t) / 60.0
        if rc != 0:
            B.log("  generate FAILED rc %s after %.1f min" % (rc, gen_min))
            st[slug] = {"route": None, "error": "generate rc %s" % rc}
            save(st)
            failed.append(slug)
            continue

        ok, lines = B.gate(slug, "v4", log_path, 0)
        for l in lines:
            B.log("  [%s] %s" % (slug, l))
        ch = B.chosen_from_log(log_path) or {}
        # GATE 0/1 are correctness and must hold whatever route we take. GATE 2 is the ROUTER, not a failure:
        # over the cap means this district wants per-building payloads, not that the build is bad.
        g0g1 = ("GATE 0" in lines[0] and "PASS" in lines[0]) and ("PASS" in lines[1])
        if not g0g1:
            B.log("  %s REJECTED - failed a correctness gate, no push" % slug)
            st[slug] = {"route": None, "error": "gate 0/1", "gates": lines}
            save(st)
            failed.append(slug)
            continue

        fits = "GATE 2" in lines[2] and "PASS" in lines[2]
        if fits:
            rc, out = run([PY, "scripts/push_sky_gz.py", slug, "--ver", "v4", "--live"], timeout=1800)
            served = "stored=True" in out and "served-as-gzip-glb=True" in out
            B.log("  TILE  %s  %s" % (slug, out.splitlines()[-1][:110] if out else "no output"))
            st[slug] = {"route": "tile", "buildings": ch.get("buildings"), "triangles": ch.get("triangles"),
                        "generate_min": round(gen_min, 1), "served": served}
            (tile if served else failed).append(slug)
        else:
            rc, out = run([PY, "scripts/glb_split_buildings.py",
                           os.path.join("data", "ce", "_glb", "sky_%s_v4_0.glb" % slug),
                           "--min-tris", str(min_tris)], timeout=3600)
            tail = out.splitlines()[-2:] if out else []
            for l in tail:
                B.log("  [%s] %s" % (slug, l[:110]))
            rc, out = run([PY, "scripts/push_buildings_gz.py", slug], timeout=3600)
            last = out.splitlines()[-1] if out else ""
            B.log("  HERO  %s  %s" % (slug, last[:110]))
            st[slug] = {"route": "hero", "buildings": ch.get("buildings"), "triangles": ch.get("triangles"),
                        "generate_min": round(gen_min, 1), "push": last}
            (hero if "failed 0" in last else failed).append(slug)
        save(st)
        done = n
        eta = (time.time() - t0) / done * (len(todo) - done)
        B.log("  %.1f min elapsed, ETA %.1f min for %d more" % ((time.time() - t0) / 60.0, eta / 60.0, len(todo) - done))

    B.log("")
    B.log("=== LOD 3 IN THE TILE (%d): %s" % (len(tile), " ".join(tile)))
    B.log("=== PER-BUILDING PAYLOADS (%d): %s" % (len(hero), " ".join(hero)))
    B.log("=== FAILED (%d): %s" % (len(failed), " ".join(failed)))
    B.log("total %.1f min" % ((time.time() - t0) / 60.0))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
