"""walk_heartbeat.py -- tell Najma the UnReal streamer is on. Every 30 s while the game process is alive, POST /walk_status with the
player-page URL (this laptop's LAN address, player port 8080) so the twin's UnReal button goes live; a final live:false when it exits.

    python scripts/walk_heartbeat.py <game_pid> [player_port=8080] [public_url]     (public_url overrides the LAN address, e.g. a tunnel)
"""
import json, os, socket, subprocess, sys, time, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_avail_index import WORKER, env_token

pid = int(sys.argv[1]); port = int(sys.argv[2]) if len(sys.argv) > 2 else 8080
public = sys.argv[3] if len(sys.argv) > 3 else ""
tok = env_token("INGEST_TOKEN")


def lan_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try: s.connect(("8.8.8.8", 80)); return s.getsockname()[0]
    finally: s.close()


def alive(p):
    out = subprocess.run(["tasklist", "/FI", f"PID eq {p}", "/FO", "CSV", "/NH"], capture_output=True, text=True).stdout
    return str(p) in out


def post(live):
    url = public or f"http://{lan_ip()}:{port}/"
    body = json.dumps({"url": url, "live": live, "streamer": "NajmaDubai"}).encode()
    req = urllib.request.Request(WORKER + "/walk_status", data=body, method="POST", headers={"X-Azimuth-Ingest": tok, "Content-Type": "application/json", "User-Agent": "najma-market-pulse/1.0"})
    try:
        r = json.load(urllib.request.urlopen(req, timeout=30)); print(time.strftime("%H:%M:%S"), "heartbeat", live, url, r.get("ok"), flush=True)
    except Exception as ex:
        print(time.strftime("%H:%M:%S"), "heartbeat failed:", str(ex)[:120], flush=True)


while alive(pid):
    post(True); time.sleep(30)
post(False); print("streamer exited; status cleared")
