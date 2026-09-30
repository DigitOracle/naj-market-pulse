"""CityEngine 2026.1 startup script: run the production textured (v3) build for one district in the lab workspace,
unattended, then close CityEngine. Output: C:\\Dev\\ce2026_lab\\data_ce\\_glb and out\\run_lab.json."""
import json
import os
import sys
import time
import traceback

LAB = r"C:\Dev\ce2026_lab"
SLUG = os.environ.get("CE2026_SLUG", "burjkhalifa")
R = {"slug": SLUG, "started": time.strftime("%Y-%m-%dT%H:%M:%S")}
sys.argv = ["ce2026_batch.py", "--v3", SLUG]
os.environ["CE2026_UNATTENDED"] = "1"
sys.path.insert(0, LAB)
t0 = time.time()
try:
    import ce2026_batch
    ce2026_batch.main()                 # exits CityEngine itself on success (CE2026_UNATTENDED)
    R["ok"] = True
except SystemExit as e:
    R["ok"] = False; R["error"] = "SystemExit: %s" % e
except Exception as e:
    R["ok"] = False; R["error"] = repr(e)[:500]; R["trace"] = traceback.format_exc()[-3000:]
finally:
    R["seconds"] = round(time.time() - t0, 1)
    R["finished"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    json.dump(R, open(os.path.join(LAB, "out", "run_lab.json"), "w", encoding="utf-8"), indent=1)
    if not R.get("ok"):
        try:
            from cityengine import CE
            CE().exit(False)
        except Exception:
            pass
