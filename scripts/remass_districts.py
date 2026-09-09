"""Re-mass districts one at a time so new heights show on the twin: CityEngine v3 mass -> pack -> push (gzipped) -> facts.
Then the twin audit is rebuilt and pushed. Designed to run DETACHED (Start-Process) - a tool-driven shell dies at 10 minutes and
this takes longer. Steps already done for a district are skipped when --resume is given (a packed GLB newer than report_v3.csv
counts as packed; a fresh bldgfacts push is always redone because it is cheap).

Usage: python scripts/remass_districts.py [--resume] [--skip-mass] slug [slug ...]
       --skip-mass  reuse the existing sky_<slug>_v3_0.glb (already massed) and only pack/push/facts
Log:   data/board/remass_<date>.log (also stdout)
"""
import os, subprocess, sys, time, datetime as dt
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, ".."))
GLB = os.path.join(ROOT, "data", "ce", "_glb"); LOG = os.path.join(ROOT, "data", "board", f"remass_{dt.date.today():%Y%m%d}.log")

def log(msg):
    line = f"[{dt.datetime.now():%H:%M:%S}] {msg}"; print(line, flush=True)
    open(LOG, "a", encoding="utf-8").write(line + "\n")

def run(cmd, keep=None):
    p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
    out = (p.stdout or "") + (p.stderr or "")
    for ln in out.splitlines():
        if keep is None or any(k in ln for k in keep): log("    " + ln[:180])
    return p.returncode

def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]; resume = "--resume" in sys.argv; skip_mass_first = "--skip-mass" in sys.argv
    if not args: sys.exit(__doc__)
    log(f"remass start: {args} resume={resume}")
    for i, s in enumerate(args):
        glb = os.path.join(GLB, f"sky_{s}_v3_0.glb"); rep = os.path.join(ROOT, "data", "ce", s, "report_v3.csv")
        skip_mass = skip_mass_first and i == 0
        if resume and os.path.exists(rep) and os.path.exists(glb) and os.path.getmtime(rep) > time.time() - 6 * 3600: skip_mass = True
        log(f"=== {s} {'(mass skipped - fresh)' if skip_mass else 'mass'}")
        if not skip_mass:
            rc = run([sys.executable, "scripts/ce_batch_v2.py", "--v3", s] + (["--allow-marina"] if s == "dubaimarina" else []), keep=["heights pushed", "LOD 1", "verify:", "failed", "Error", "Traceback", "lock"])
            if rc != 0 or not os.path.exists(glb): log(f"    !! mass failed for {s} (rc={rc}) - skipping the rest of its chain"); continue
        run(["node", "scripts/glb_pack_v3.mjs", f"data/ce/_glb/sky_{s}_v3_0.glb"], keep=["output"])
        run([sys.executable, "scripts/push_sky_gz.py", s], keep=["sky_"])
        run([sys.executable, "scripts/build_buildingfacts.py", s], keep=["bldgfacts_", "buildings"])
    log("=== twin audit")
    run([sys.executable, "scripts/twin_audit.py"], keep=["districts", "grades"])
    try:
        import json; sys.path.insert(0, HERE)
        from build_avail_index import env_token, push
        d = json.load(open(os.path.join(ROOT, "data", "board", "twin_audit.json"), encoding="utf-8"))
        log(f"    twin_audit -> {push('twin_audit', {'generated': d['generated'], 'districts': d['districts']}, env_token('INGEST_TOKEN')).get('ok')}")
    except Exception as e: log(f"    twin_audit push failed: {e}")
    log("=== DONE")

if __name__ == "__main__":
    main()
