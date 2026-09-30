"""LAB (landmarks, research only): the whole landmark lane in order, once the CityEngine Python bridge is up.

  1. wait (bounded) until CityEngine's py4j bridge listens on 127.0.0.1:25333 - it is the only sanctioned way to
     compile a .cga, and on 30 Sep 06:36 it had stopped listening with CityEngine itself still running
  2. scripts/lab_landmarks_rpk.py     compile + package, under the data/ce/.ce_lock protocol
  3. scripts/lab_landmarks_build.py   PyPRT before / after GLBs + checks -> build_report.json
  4. scripts/lab_landmarks_render.py  before / after PNGs

Nothing is pushed, deployed or uploaded.   python scripts/lab_landmarks_run.py [--wait-bridge-s 2700]
"""
import os
import socket
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))


def bridge_up():
    try:
        with socket.create_connection(("127.0.0.1", 25333), timeout=3):
            return True
    except OSError:
        return False


def main():
    wait = float(sys.argv[sys.argv.index("--wait-bridge-s") + 1]) if "--wait-bridge-s" in sys.argv else 2700
    t0 = time.time()
    while not bridge_up():
        if time.time() - t0 > wait:
            print("BRIDGE DOWN: CityEngine's Python bridge (127.0.0.1:25333) did not come back in %.0f s" % wait, flush=True)
            return 3
        time.sleep(30)
    print("bridge up after %.0f s" % (time.time() - t0), flush=True)
    for step in (["lab_landmarks_rpk.py", "--max-wait", "5400"], ["lab_landmarks_build.py"], ["lab_landmarks_render.py"]):
        print("== %s" % " ".join(step), flush=True)
        r = subprocess.run([sys.executable, os.path.join(HERE, step[0])] + step[1:], cwd=ROOT)
        if r.returncode != 0:
            print("STEP FAILED: %s (exit %d)" % (step[0], r.returncode), flush=True)
            return r.returncode
    print("ALL DONE", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
