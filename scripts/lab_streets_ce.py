"""lab_streets_ce.py -- shared helpers for the LAB streets lane (technique #3: CityEngine street graph + street rule).

Research only. Nothing here pushes, deploys or uploads, and nothing touches a production scene: every CE call in
this lane works in /najma/scenes/lab_streets_<slug>.cej, which only this lane creates.

CityEngine lock: same protocol as scripts/ce_batch_v2.py -- data/ce/.ce_lock holds "<name> pid <pid> <iso time>";
wait while another live process holds it (20 s polls, stale pid cleared), write ours, remove it in `finally` only if it
is still ours. `with ce_lock("step"):` is the only way this lane takes it, so every step releases even on an exception.
"""
import contextlib, datetime, json, os, re, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
CEDIR = os.path.join(ROOT, "data", "ce")
LAB = os.path.join(ROOT, "data", "lab", "streets")
LOCK = os.path.join(CEDIR, ".ce_lock")
WS_ROOT = r"C:\Users\kwils\OneDrive\Documents\CityEngine\Default Workspace"
RULE_DIR_FS = os.path.join(WS_ROOT, "najma", "rules", "lab", "streets")
RULE_WS = "/najma/rules/lab/streets/dubai_street.cga"
os.makedirs(LAB, exist_ok=True)

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

_log_lines = []


def log(*a):
    s = time.strftime("%H:%M:%S ") + " ".join(str(x) for x in a)
    print(s, flush=True)
    _log_lines.append(s)


def dump_log(path):
    with open(path, "a", encoding="utf-8") as f:
        f.write("\n".join(_log_lines) + "\n")


def _pid_dead(txt):
    """True only when the lock names a pid that is provably gone (same conservatism as ce_batch_v2.lock_is_stale)."""
    m = re.search(r"\bpid[= ](\d+)", txt)
    if not m:
        return False
    pid = int(m.group(1))
    try:
        out = subprocess.run(["tasklist", "/FI", "PID eq %d" % pid], capture_output=True, text=True,
                             errors="ignore", timeout=30).stdout
        return str(pid) not in out
    except Exception:
        return False


@contextlib.contextmanager
def ce_lock(step, max_wait=30 * 60, poll=20):
    name = "lab_streets %s (agent #3 streets) pid %d" % (step, os.getpid())
    t0 = time.time()
    while os.path.exists(LOCK):
        try:
            holder = open(LOCK, encoding="utf-8", errors="replace").read().strip()
        except OSError:
            holder = "?"
        if _pid_dead(holder):
            log("  CE lock is STALE (process gone) - clearing: %s" % holder)
            try:
                os.remove(LOCK)
                break
            except OSError as e:
                log("  could not clear stale lock: %s" % e)
        if time.time() - t0 > max_wait:
            raise SystemExit("CE lock held by '%s' for > %d min - giving up, nothing touched" % (holder, max_wait // 60))
        log("  CE lock held by '%s' - waiting %ds (%ds so far)" % (holder, poll, int(time.time() - t0)))
        time.sleep(poll)
    with open(LOCK, "w", encoding="utf-8") as f:
        f.write("%s %s\n" % (name, datetime.datetime.now().isoformat(timespec="seconds")))
    log("  CE lock acquired: %s" % name)
    try:
        yield name
    finally:
        try:
            if os.path.exists(LOCK) and name in open(LOCK, encoding="utf-8", errors="replace").read():
                os.remove(LOCK)
                log("  CE lock released: %s" % step)
        except Exception as e:
            log("  lock release problem: %s" % e)


def idle(ce, fallback=2):
    try:
        ce.waitForUIIdle()
    except Exception:
        time.sleep(fallback)


def jdump(obj, path):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=1, default=str)
