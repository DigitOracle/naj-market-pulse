"""Was the developer-availability capture actually alive since the last refresh? Answer it every morning, in writing.

The listener (C:\\Dev\\azimuth-listener-naj) is a live WhatsApp socket: it captures a sheet only if it is running at the moment
the sheet is posted. A dead listener therefore fails silently - the morning scan simply finds nothing new, which looks exactly
like a quiet day. This check runs first in the daily refresh and turns "nothing new" into one of two honest statements:
"nothing was posted" or "we were not listening". It writes the verdict to the refresh log, to data/avail/listener_health.json,
and to the Worker (KV listener_health, shown on /health) so the gap is visible from the phone.

Checks: node process alive (matched on the script path in its command line, never a folder name) - launcher exits and
restarts in listener.log over the window - hours of coverage lost - PDFs captured into docs/ over the window - last connect.
Exit code 0 = listening the whole window, 2 = some coverage lost, 3 = not listening now.
Usage: python scripts/listener_health.py [--hours 24] [--no-push]
"""
import argparse, datetime as dt, glob, json, os, re, subprocess, sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
LISTENER = r"C:\Dev\azimuth-listener-naj"
SCRIPT = os.path.join(LISTENER, "src", "index.js")
OUT = os.path.join(ROOT, "data", "avail", "listener_health.json")


def alive_pids():
    """PIDs of node processes running THIS listener's script (command line match, as the launcher's own guard does)."""
    ps = ("Get-CimInstance Win32_Process -Filter \"name='node.exe'\" | Where-Object { $_.CommandLine -match [regex]::Escape('%s') } "
          "| ForEach-Object { '{0}|{1}' -f $_.ProcessId, $_.CreationDate.ToString('s') }" % SCRIPT)
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps], capture_output=True, text=True, timeout=60)
        return [ln.strip() for ln in r.stdout.splitlines() if ln.strip()]
    except Exception:
        return []


def read_text(path):
    for enc in ("utf-8-sig", "utf-16", "utf-8"):
        try:
            t = open(path, encoding=enc).read()
            if "\x00" not in t: return t
        except Exception:
            continue
    try:
        return open(path, "rb").read().decode("utf-8", "ignore").replace("\x00", "")
    except Exception:
        return ""


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--hours", type=float, default=24); ap.add_argument("--no-push", action="store_true")
    a = ap.parse_args()
    now = dt.datetime.now(); since = now - dt.timedelta(hours=a.hours)
    pids = alive_pids()
    # launcher lines carry ISO timestamps: "[2026-09-03T18:02:45] launcher: starting listener" / "... exited with code 1"
    log = read_text(os.path.join(LISTENER, "listener.log"))
    events = []
    for m in re.finditer(r"\[(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})\]\s*launcher:\s*(starting listener|listener exited with code (-?\d+)|already running)", log):
        t = dt.datetime.fromisoformat(m.group(1))
        if t >= since: events.append((t, m.group(2)))
    starts = [t for t, e in events if e == "starting listener"]; exits = [(t, e) for t, e in events if e.startswith("listener exited")]
    # coverage lost inside the window: from each exit to the next start (or to now if none, and not alive)
    lost = dt.timedelta(0)
    for t, e in exits:
        nxt = min([s for s in starts if s > t], default=None)
        lost += ((nxt or now) - t) if (nxt or not pids) else dt.timedelta(0)
    # if the listener is dead now and there was no exit line in the window, the whole window is lost
    if not pids and not exits: lost = dt.timedelta(hours=a.hours)
    docs = [p for p in glob.glob(os.path.join(LISTENER, "docs", "**", "*.pdf"), recursive=True) if dt.datetime.fromtimestamp(os.path.getmtime(p)) >= since]
    out = read_text(os.path.join(LISTENER, "listener.out.log"))
    connected = "[wa] connected" in out
    verdict = ("listening" if pids and lost.total_seconds() < 60 else ("gap" if pids else "down"))
    rec = {"checked": now.isoformat(timespec="seconds"), "window_hours": a.hours, "alive": bool(pids), "pids": pids,
           "connected_in_current_log": connected, "starts_in_window": len(starts), "exits_in_window": len(exits),
           "coverage_lost_hours": round(lost.total_seconds() / 3600, 2), "pdfs_captured_in_window": len(docs),
           "pdfs": [os.path.relpath(p, LISTENER) for p in docs][:20], "verdict": verdict,
           "meaning": {"listening": "the listener was up for the whole window - if nothing new was scanned, nothing was posted",
                       "gap": "the listener restarted during the window - sheets posted in the lost hours were NOT captured",
                       "down": "the listener is NOT running - nothing posted since it died has been captured"}[verdict]}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(rec, open(OUT, "w", encoding="utf-8"), indent=1)
    print(f"listener health: {verdict.upper()} | alive={bool(pids)} | lost {rec['coverage_lost_hours']} h of {a.hours} | "
          f"restarts {len(starts)} exits {len(exits)} | PDFs captured {len(docs)}")
    print("  " + rec["meaning"])
    if not a.no_push:
        try:
            from build_avail_index import env_token, push
            print("  listener_health ->", push("listener_health", rec, env_token("INGEST_TOKEN")).get("ok"))
        except Exception as e:
            print("  push failed:", e)
    return {"listening": 0, "gap": 2, "down": 3}[verdict]


if __name__ == "__main__":
    sys.exit(main())
