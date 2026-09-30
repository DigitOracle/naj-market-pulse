"""LAB (register thread, research only): compile najma_v4_register.cga and package it as an .rpk for PyPRT.

The one step that needs CityEngine. Same lock protocol as scripts/export_najma_rpk.py: WAIT for data/ce/.ce_lock
(20 s polls, give up after an hour), write our own lock line, export, remove the lock only if it is still ours
(in a finally). No scene is opened, created or saved - getRuleFileInfo and exportRPK work on the rule file alone.

  python scripts/lab_register_rpk.py            compile check + export data/lab/register/najma_v4_register.rpk
  python scripts/lab_register_rpk.py --check    compile check only
  python scripts/lab_register_rpk.py --tables alyufrah1,alhebiahfifth
        also copy data/lab/register/register_<slug>.csv to /najma/rules/lab/register/tables/ and PACK them into the
        .rpk (RPKExportSettings.addFile) - readStringTable in PyPRT cannot reach a file outside the package
        (measured: absolute path, file:/// URI and backslash path all give nRows = 0)
"""
import json
import os
import shutil
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
LOCK = os.path.join(ROOT, "data", "ce", ".ce_lock")
OUT = os.path.join(ROOT, "data", "lab", "register")
RULE_WS = "/najma/rules/lab/register/najma_v4_register.cga"
TAG = "lab_register_rpk pid %d" % os.getpid()
WS_DIR = os.path.join(os.path.expanduser("~"), "OneDrive", "Documents", "CityEngine", "Default Workspace",
                      "najma", "rules", "lab", "register")


def take_lock(max_wait_s=3600):
    t0 = time.time()
    while os.path.exists(LOCK):
        held = open(LOCK, encoding="utf-8", errors="ignore").read().strip()
        waited = time.time() - t0
        if waited > max_wait_s:
            sys.exit("gave up after %.0f s: CE lock still held by '%s'" % (waited, held))
        print("  CE lock held by '%s' - waiting (%.0f s so far)" % (held, waited), flush=True)
        time.sleep(20)
    with open(LOCK, "w", encoding="utf-8") as fh:
        fh.write("%s %s" % (TAG, time.strftime("%Y-%m-%dT%H:%M:%S")))


def release_lock():
    try:
        if open(LOCK, encoding="utf-8").read().startswith(TAG):
            os.remove(LOCK)
    except OSError:
        pass


def plain(o):
    if isinstance(o, dict):
        return {str(k): plain(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [plain(v) for v in o]
    if isinstance(o, (str, int, float, bool)) or o is None:
        return o
    for f in (dict, list):
        try:
            return plain(f(o))
        except Exception:
            pass
    return str(o)


def main():
    check_only = "--check" in sys.argv
    os.makedirs(OUT, exist_ok=True)
    rpk = os.path.join(OUT, "najma_v4_register.rpk")
    info, took = {}, None
    tables = [t for t in (sys.argv[sys.argv.index("--tables") + 1].split(",") if "--tables" in sys.argv else []) if t]
    for t in tables:
        os.makedirs(os.path.join(WS_DIR, "tables"), exist_ok=True)
        shutil.copy2(os.path.join(OUT, "register_%s.csv" % t), os.path.join(WS_DIR, "tables", "register_%s.csv" % t))
    take_lock()
    try:
        from cityengine import CE, RPKExportSettings  # bridge connects on first call
        ce = CE()
        try:
            ce.refreshFolder("/najma/rules/lab/register/")   # the lab .cga was written from outside CityEngine
            if tables:
                ce.refreshFolder("/najma/rules/lab/register/tables/")
        except Exception as e:
            print("  refreshFolder: %s" % str(e)[:200])
        try:
            info = {"ok": True, "info": plain(ce.getRuleFileInfo(RULE_WS))}
        except Exception as e:
            info = {"ok": False, "error": str(e)[:3000]}
        if not check_only and info["ok"]:
            s = RPKExportSettings()
            s.setRuleFile(RULE_WS)
            s.setAddFilesAutomatically()
            s.setIncludeSourceFiles(True)
            for t in tables:
                s.addFile("/najma/rules/lab/register/tables/register_%s.csv" % t)
            s.setFile(rpk)
            t = time.time()
            ce.exportRPK(s)
            took = round(time.time() - t, 1)
            try:
                info["files"] = plain(s.listFiles())
            except Exception as e:
                info["files"] = str(e)[:200]
    finally:
        release_lock()
    json.dump({"rule": RULE_WS, "compile": info, "export_s": took, "when": time.strftime("%Y-%m-%dT%H:%M:%S")},
              open(os.path.join(OUT, "rule_info.json"), "w", encoding="utf-8"), indent=1)
    print("  %s %s" % (RULE_WS, "compiled" if info.get("ok") else "FAILED: " + info.get("error", "")[:600]))
    if not check_only and info.get("ok"):
        if not os.path.exists(rpk) or os.path.getsize(rpk) == 0:
            sys.exit("no .rpk written")
        print("  wrote %s  %.2f MB  in %s s" % (os.path.relpath(rpk, ROOT), os.path.getsize(rpk) / 1048576.0, took))
    return 0 if info.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
