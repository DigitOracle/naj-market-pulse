"""Build, gate and push every Najma district in one unattended run.

Written 22 Sep 2026. Replaces remass_reclassed.sh (generate/pack/push as three unconditional steps with nothing
reconciling them) and folds in repush_failed.sh. Three failures on 22 Sep are the reason it exists:

  * 7 of 14 districts generated and packed perfectly, lost the upload to DNS, and the run reported "0 failures"
    because it was counting GENERATE failures. Districts attempted was never reconciled against districts stored.
  * A LOD 3 run reported 654 shapes generated with zero failures and produced 54 addressable buildings. The
    payload looks perfect in a screenshot and cannot be tapped.
  * CityEngine SPLIT that export into sky_businessbay_v4_0.glb (202.6 MB) and _1.glb (154.5 MB). The merge, the
    verify block, the pack and the push all open _0 and nothing else, so the run measured a 202 MB fragment of a
    357 MB district and reported it as the whole thing. Two runs whose geometry differed threefold both came back
    at ~200 MB, which is a ceiling, not a measurement.

So nothing here is trusted because a step "ran". A district is DONE only when the gates pass AND the worker
serves the bytes back. Everything else is a failure with a name.

CityEngine is a single exclusive resource: generates are strictly serial and respect data/ce/.ce_lock. Pack, gate
and push are pipelined onto a worker thread so the next district starts generating immediately - on the 22 Sep
numbers that is ~30-50 min of export per district against seconds of push, so the pipelining is most of the
wall-clock win across 43 districts.

  python scripts/najma_build_all.py --all --ver v4 --tall-h 150
  python scripts/najma_build_all.py businessbay dubaimarina --ver v4 --tall-h 150 --min-tris 400000
  python scripts/najma_build_all.py --all --resume          # skip districts already gated and stored
  python scripts/najma_build_all.py --all --dry-run         # plan and ETA only, touches nothing
  python scripts/najma_build_all.py --push-only <slugs>     # reconcile and retry uploads, no CityEngine

State lives in data/ce/_build_state.json and is written after every district, so the run survives a crash, a
reboot or a stop. --resume never re-generates what already passed.
"""
import gzip, json, os, queue, re, subprocess, sys, threading, time

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
CEDIR = os.path.join(ROOT, "data", "ce")
GLB = os.path.join(CEDIR, "_glb")
LOGS = os.path.join(ROOT, "logs")
STATE = os.path.join(CEDIR, "_build_state.json")
LOCK = os.path.join(CEDIR, ".ce_lock")
CAP = 5 * 1024 * 1024
PY = sys.executable or "python"


# Flags that take a value. The value has to be removed from the positional list as well as the flag itself, or
# "--ver v3" builds a district called "v3" - the same bug push_sky_gz.py had, caught here by --dry-run.
VALUE_FLAGS = ("--ver", "--lod", "--tall-h", "--tall-lod", "--min-tris", "--push-tries", "--push-wait")


def opt(name, default=None, cast=str):
    return cast(sys.argv[sys.argv.index(name) + 1]) if name in sys.argv else default


def flag(name):
    return name in sys.argv


def positionals():
    out, skip = [], False
    for a in sys.argv[1:]:
        if skip:
            skip = False
            continue
        if a in VALUE_FLAGS:
            skip = True
            continue
        if not a.startswith("--"):
            out.append(a)
    return out


def districts_on_disk():
    return sorted(d for d in os.listdir(CEDIR)
                  if os.path.isdir(os.path.join(CEDIR, d)) and not d.startswith("_"))


def load_state():
    if os.path.exists(STATE):
        try:
            return json.load(open(STATE, encoding="utf-8"))
        except Exception:
            pass
    return {"districts": {}}


def save_state(st):
    """Merge-on-write, not overwrite. Two runs can be in flight at once - on 22 Sep a batch was launched while
    an earlier district's push was still finishing, and the second process wrote back the state it had loaded
    at startup, erasing the first district's row. Re-read and merge so a concurrent run only ever ADDS."""
    on_disk = {"districts": {}}
    if os.path.exists(STATE):
        try:
            on_disk = json.load(open(STATE, encoding="utf-8"))
        except Exception:
            pass
    merged = dict(on_disk.get("districts", {}))
    merged.update(st.get("districts", {}))
    out = dict(on_disk)
    out["districts"] = merged
    tmp = STATE + ".tmp"
    json.dump(out, open(tmp, "w", encoding="utf-8"), indent=1)
    os.replace(tmp, STATE)


def log(*a):
    line = " ".join(str(x) for x in a)
    print(time.strftime("%H:%M:%S ") + line, flush=True)
    try:
        open(os.path.join(LOGS, "build_all.log"), "a", encoding="utf-8").write(
            time.strftime("%Y-%m-%d %H:%M:%S ") + line + "\n")
    except Exception:
        pass


def lock_is_stale():
    """True when .ce_lock names a process that is no longer running.

    The lock has no owner check, so a run that dies - a killed session, a reboot, a crashed CityEngine -
    leaves a file that blocks every future run forever. On 22 Sep a stopped session left one held for nearly
    six hours; nothing was running and nothing could start. A lock is only meaningful while its holder lives.
    Deliberately conservative: anything it cannot prove dead is treated as ALIVE, so a live run is never
    stolen from - the cost of being wrong that way is a wait, the other way is two CityEngines in one scene.
    """
    try:
        txt = open(LOCK, encoding="utf-8", errors="ignore").read()
    except OSError:
        return False
    m = re.search(r"\bpid\s+(\d+)", txt)
    if not m:
        return False
    pid = int(m.group(1))
    try:
        if sys.platform == "win32":
            out = subprocess.run(["tasklist", "/FI", "PID eq %d" % pid], capture_output=True,
                                 text=True, errors="ignore", timeout=30).stdout
            return str(pid) not in out
        os.kill(pid, 0)
        return False
    except ProcessLookupError:
        return True
    except Exception:
        return False      # cannot tell -> assume alive


def run(cmd, tail=6, timeout=None):
    """Run a command, return (rc, last lines of combined output)."""
    p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, errors="ignore", timeout=timeout)
    out = (p.stdout or "") + (p.stderr or "")
    return p.returncode, "\n".join(out.strip().splitlines()[-tail:])


# ---------------------------------------------------------------- the gates

def chosen_from_log(path):
    """Pull the last chosen{} dict out of a batch log. None if the run never finished."""
    if not os.path.exists(path):
        return None
    txt = open(path, encoding="utf-8", errors="ignore").read()
    hits = re.findall(r"chosen (\{[^}]*\})", txt)
    if not hits:
        return None
    return json.loads(hits[-1].replace("'", '"').replace("True", "true").replace("False", "false"))


def parts_for(slug, ver):
    """Every GLB part CityEngine wrote. More than one means the export was SPLIT."""
    pre, suf = "sky_%s_%s_" % (slug, ver), ".glb"
    out = []
    for f in sorted(os.listdir(GLB)):
        if f.startswith(pre) and f.endswith(suf) and f[len(pre):-len(suf)].isdigit():
            out.append(f)
    return out


def gate(slug, ver, batch_log, min_tris):
    """The four gates. Nothing is inferred; every number is measured. Returns (ok, [lines])."""
    lines = []
    ch = chosen_from_log(batch_log)
    if ch is None:
        return False, ["GATE 0-3  no chosen{} in %s - the run did not finish" % os.path.basename(batch_log)]

    # GATE 0  PARTS. CityEngine splits an oversized export into _0/_1/_2... and everything downstream - the
    # merge, the verify block, the pack, the push - only ever opens _0. A split export therefore reports a
    # perfectly healthy fragment: right materials, one mesh per building, sane triangle count, and most of the
    # district silently absent. This gate is the one that catches it, and it is first because it is cheapest.
    parts = parts_for(slug, ver)
    g0 = len(parts) == 1
    extra_mb = sum(os.path.getsize(os.path.join(GLB, f)) for f in parts[1:]) / 1048576.0 if len(parts) > 1 else 0
    lines.append("GATE 0  export parts %d%s  ->  %s" % (
        len(parts),
        ("  %s  (%.1f MB never merged, packed or pushed)" % (" ".join(parts), extra_mb)) if not g0 else "",
        "PASS" if g0 else "FAIL - export SPLIT; only _0 reaches the twin"))

    # GATE 1  BUILDINGS. Per-building meshes are how the twin does tapping, the floor stack and the panel.
    b, ok = ch.get("buildings"), ch.get("shapes_ok")
    g1 = bool(b and b == ok)
    lines.append("GATE 1  buildings %s of %s shapes  ->  %s" % (
        b, ok, "PASS" if g1 else "FAIL - payload is short; not addressable"))

    # GATE 2  SIZE. Measured by gzipping the file, never inferred from merged MB - the ratio moves because a
    # LOD 3 payload ships zero texture images.
    glb = os.path.join(GLB, "sky_%s_%s_0.glb" % (slug, ver))
    if not os.path.exists(glb):
        g2 = False
        lines.append("GATE 2  no GLB at %s  ->  FAIL" % os.path.basename(glb))
    else:
        gz = len(gzip.compress(open(glb, "rb").read(), 9))
        g2 = gz <= CAP
        lines.append("GATE 2  gzipped %.2f MB of 5 MB cap  ->  %s" % (
            gz / 1048576.0, "PASS" if g2 else "FAIL - over the KV cap"))

    # GATE 3  THE TIER FIRED. A log line is a claim; the triangle count is the measurement. Reported per
    # building as well as in total, because a truncated run can clear a total floor on its surviving slice
    # alone - Business Bay's 202 MB fragment reported 953,563 triangles, comfortably over any sane floor.
    tris = ch.get("triangles")
    per = (tris / b) if (tris and b) else 0
    g3 = bool(tris and tris >= min_tris) if min_tris else True
    lines.append("GATE 3  %s triangles, %.0f per building, floor %s  ->  %s" % (
        tris, per, min_tris or "off", "PASS" if g3 else "FAIL - the tier did not fire"))

    return bool(g0 and g1 and g2 and g3), lines


# ---------------------------------------------------------------- steps

def generate(slug, ver, tall_h, tall_lod, lod):
    batch_log = os.path.join(LOGS, "build_%s_%s.log" % (ver, slug))
    cmd = [PY, "scripts/ce_batch_v2.py", "--" + ver, slug]
    if lod is not None:
        cmd += ["--lod", str(lod)]
    if tall_h is not None:
        cmd += ["--tall-h", str(tall_h), "--tall-lod", str(tall_lod)]
    t0 = time.time()
    with open(batch_log, "w", encoding="utf-8") as fh:
        rc = subprocess.Popen(cmd, cwd=ROOT, stdout=fh, stderr=subprocess.STDOUT, text=True).wait()
    return rc, batch_log, round(time.time() - t0, 1)


def pack(slug, ver):
    f = os.path.join(GLB, "sky_%s_%s_0.glb" % (slug, ver))
    if not os.path.exists(f):
        return 1, "no GLB to pack"
    return run(["node", "scripts/glb_pack_v3.mjs", f], tail=2)


def push(slug, ver, tries=6, wait=600):
    """Push and CONFIRM. stored=True is the only evidence that counts; a step that merely ran is not evidence.
    Retries the push alone - the generate is the expensive half and it survives a DNS failure."""
    last = ""
    for i in range(1, tries + 1):
        rc, out = run([PY, "scripts/push_sky_gz.py", slug, "--ver", ver], tail=3)
        last = out
        if "stored=True" in out:
            return True, out
        log("    push %s attempt %d/%d failed: %s" % (
            slug, i, tries, out.splitlines()[-1][:120] if out else "no output"))
        if i < tries:
            time.sleep(wait)
    return False, last


# ---------------------------------------------------------------- main

def main():
    args = positionals()
    ver = opt("--ver", "v4")
    lod = opt("--lod", None, int)
    tall_h = opt("--tall-h", None, float)
    tall_lod = opt("--tall-lod", 3, int)
    min_tris = opt("--min-tris", 0, int)
    tries = opt("--push-tries", 6, int)
    wait = opt("--push-wait", 600, int)

    todo = districts_on_disk() if flag("--all") else args
    if not todo:
        print(__doc__)
        return 2

    st = load_state()
    ds = st.setdefault("districts", {})

    if flag("--resume"):
        skip = [d for d in todo if ds.get(d, {}).get("ver") == ver and ds.get(d, {}).get("status") == "DONE"]
        todo = [d for d in todo if d not in skip]
        if skip:
            log("resume: skipping %d already DONE at %s: %s" % (len(skip), ver, " ".join(skip)))

    # --push-only: no CityEngine at all. Reconciles what is on disk against what the worker actually serves.
    if flag("--push-only"):
        log("push-only: %d districts, no CityEngine, lock untouched" % len(todo))
        bad = []
        for d in todo:
            ok, out = push(d, ver, tries, wait)
            log("  %-28s %s" % (d, "stored" if ok else "FAILED"))
            ds.setdefault(d, {})["stored"] = ok
            save_state(st)
            if not ok:
                bad.append(d)
        log("push-only done: %d stored, %d failed%s" % (
            len(todo) - len(bad), len(bad), (": " + " ".join(bad)) if bad else ""))
        return 1 if bad else 0

    if os.path.exists(LOCK) and not flag("--dry-run") and lock_is_stale():
        log("CityEngine lock is STALE (its process is gone) - clearing: %s"
            % open(LOCK, encoding="utf-8", errors="ignore").read().strip())
        try:
            os.remove(LOCK)
        except OSError as e:
            log("  could not remove the stale lock: %s" % e)

    if os.path.exists(LOCK) and not flag("--dry-run"):
        log("CityEngine lock held: %s" % open(LOCK, encoding="utf-8", errors="ignore").read().strip())
        if not flag("--wait-lock"):
            log("refusing to start - another run owns the bridge. Pass --wait-lock to queue behind it.")
            return 1
        while os.path.exists(LOCK):
            time.sleep(30)
        log("lock cleared, starting")

    log("plan: %d districts at %s%s%s" % (
        len(todo), ver,
        (", tall>=%gm at LOD %d" % (tall_h, tall_lod)) if tall_h else "",
        (", floor %d tris" % min_tris) if min_tris else ""))
    for d in todo:
        log("   %s" % d)
    if flag("--dry-run"):
        log("dry run - nothing executed")
        return 0

    # Pack + gate + push run on a worker so the next generate starts immediately.
    work = queue.Queue()
    results = {}

    def worker():
        while True:
            item = work.get()
            if item is None:
                work.task_done()
                return
            slug, batch_log, gen_s = item
            try:
                pack(slug, ver)
                ok, lines = gate(slug, ver, batch_log, min_tris)
                for l in lines:
                    log("  [%s] %s" % (slug, l))
                if not ok:
                    results[slug] = "GATED"
                    ds.setdefault(slug, {}).update(ver=ver, status="GATED", generate_s=gen_s, gates=lines)
                    log("  %s NOT PUSHED - failed a gate" % slug)
                else:
                    stored, out = push(slug, ver, tries, wait)
                    results[slug] = "DONE" if stored else "PUSH_FAILED"
                    ds.setdefault(slug, {}).update(ver=ver, status=results[slug], generate_s=gen_s,
                                                   gates=lines, push=out.splitlines()[-1][:200] if out else "")
                    log("  %s %s" % (slug, "DONE" if stored else "PUSH FAILED after retries"))
                save_state(st)
            except Exception as e:
                results[slug] = "ERROR"
                log("  %s worker error: %s" % (slug, e))
            finally:
                work.task_done()

    threading.Thread(target=worker, daemon=True).start()

    t_start = time.time()
    for n, slug in enumerate(todo, 1):
        log("=== [%d/%d] generate %s" % (n, len(todo), slug))
        rc, batch_log, gen_s = generate(slug, ver, tall_h, tall_lod, lod)
        log("  generate %s in %.1f min (rc %s)" % (slug, gen_s / 60.0, rc))
        if rc != 0:
            results[slug] = "GENERATE_FAILED"
            ds.setdefault(slug, {}).update(ver=ver, status="GENERATE_FAILED", generate_s=gen_s)
            save_state(st)
            continue
        work.put((slug, batch_log, gen_s))
        if n < len(todo):
            eta = (time.time() - t_start) / n * (len(todo) - n)
            log("  elapsed %.1f min, ETA %.1f min for the remaining %d" % (
                (time.time() - t_start) / 60.0, eta / 60.0, len(todo) - n))

    work.put(None)
    work.join()

    # ---------------------------------------------------------------- reconciliation
    # Attempted against stored, by name. The absence of this step is what made a 7-district upload loss read as
    # "0 failures" on 22 Sep. A district is not done because a step ran; it is done because it is served back.
    done = [d for d in todo if results.get(d) == "DONE"]
    bad = [d for d in todo if results.get(d) != "DONE"]
    log("")
    log("=== attempted %d | DONE %d | not done %d" % (len(todo), len(done), len(bad)))
    for d in bad:
        log("   %-28s %s" % (d, results.get(d, "NO RESULT")))
    retry = [d for d in bad if results.get(d) == "PUSH_FAILED"]
    if retry:
        log("")
        log("retry the uploads only (no CityEngine, the generate is preserved):")
        log("   python scripts/najma_build_all.py %s --ver %s --push-only" % (" ".join(retry), ver))
    log("total %.1f min" % ((time.time() - t_start) / 60.0))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
