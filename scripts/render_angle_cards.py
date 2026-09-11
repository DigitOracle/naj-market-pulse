"""Render the day's angle cards to PNG on this machine and push them into the store (the Worker has no browser renderer).

Every run: ask the Worker which angles of the current brief lack a card (/angle_pending), render each with Edge headless from
/angle_svg (1080x1080), push as img angle_<ctxAt>_<n>, then call /send_card so anyone who asked for it while it was rendering
receives it. Runs from the scheduled task Najma_Angle_Cards every 5 minutes, 06:55-21:00 GST - the FALLBACK since v105 (the Worker renders through its Browser Rendering binding first). Both sizes: keys ending _s are 1080x1920. Idempotent; quiet when nothing is
pending. Log: data/board/angle_cards.log

Usage: python scripts/render_angle_cards.py [--once]
"""
import base64, json, os, subprocess, sys, time, urllib.parse, urllib.request, datetime as dt
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
from build_avail_index import env_token, WORKER  # noqa: E402
EDGE = next((p for p in (r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe", r"C:\Program Files\Microsoft\Edge\Application\msedge.exe") if os.path.exists(p)), None)
OUT = os.path.join(ROOT, "data", "board", "angle_cards"); LOG = os.path.join(ROOT, "data", "board", "angle_cards.log")
UA = {"User-Agent": "najma-market-pulse/1.0 (angle cards)"}

def log(m):
    line = f"[{dt.datetime.now():%Y-%m-%d %H:%M:%S}] {m}"; print(line, flush=True)
    open(LOG, "a", encoding="utf-8").write(line + "\n")

def get(path, key, timeout=60):
    return urllib.request.urlopen(urllib.request.Request(WORKER + path + ("&" if "?" in path else "?") + "key=" + urllib.parse.quote(key), headers=UA), timeout=timeout)

def main():
    key = env_token("READ_KEY"); tok = env_token("INGEST_TOKEN")
    if not key or not tok or not EDGE: log(f"missing: key={bool(key)} token={bool(tok)} edge={bool(EDGE)}"); return
    os.makedirs(OUT, exist_ok=True)
    # v123 (11 Sep 2026) - finish any picture she asked for that the Worker did not live long enough to send.
    # A deploy landed on top of her Lobby request this morning: plate made, cards rendered, nothing sent.
    # This runs every five minutes, so five minutes is now the worst she waits with no one watching.
    try:
        rs = json.load(get("/pic_resume?min_age=90", key, timeout=280))
        for j in rs.get("jobs", []):
            if j.get("done"): log(f"pic_resume finished {j.get('job')}")
            elif j.get("why"): log(f"pic_resume {j.get('job')}: {str(j.get('why'))[:80]}")
    except Exception as e: log(f"pic_resume failed: {str(e)[:80]}")
    try: pend = json.load(get("/angle_pending", key))
    except Exception as e: log(f"angle_pending failed: {str(e)[:80]}"); return
    if not pend.get("pending"): return
    log(f"brief {pend.get('ctxAt')}: {len(pend['pending'])} card(s) to render, wanted {pend.get('wanted')}")
    for it in pend["pending"]:
        n, k = it["n"], it["key"]; png = os.path.join(OUT, k + ".png")
        story = k.endswith("_s"); wh = "1080,1920" if story else "1080,1080"                       # v105 - "_s" keys are the 9:16 card
        url = f"{WORKER}/angle_svg?n={n}&size={'story' if story else 'square'}&key={urllib.parse.quote(key)}"
        prof = os.path.join(OUT, "_edge_profile")                      # own profile: a headless run on the user's live profile is handed to the open browser and never returns
        log(f"  {k}: rendering")
        try:
            subprocess.run([EDGE, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run", "--no-default-browser-check", "--disable-extensions", f"--user-data-dir={prof}", f"--window-size={wh}", "--force-device-scale-factor=1", "--virtual-time-budget=8000", f"--screenshot={png}", url], capture_output=True, timeout=75)
        except subprocess.TimeoutExpired: log(f"  {k}: edge timed out"); continue
        except Exception as e: log(f"  {k}: edge failed {str(e)[:60]}"); continue
        if not os.path.exists(png) or os.path.getsize(png) < 20000: log(f"  {k}: no usable screenshot"); continue
        raw = open(png, "rb").read()
        body = json.dumps({"imageName": k, "image": base64.b64encode(raw).decode(), "contentType": "image/png"}).encode()
        try:
            r = json.load(urllib.request.urlopen(urllib.request.Request(WORKER + "/ingest_market", data=body, method="POST", headers={"X-Azimuth-Ingest": tok, "Content-Type": "application/json", **UA}), timeout=120))
            log(f"  {k}: {len(raw)//1024} KB -> stored={r.get('ok')}")
        except Exception as e: log(f"  {k}: push failed {str(e)[:60]}"); continue
        if n in (pend.get("wanted") or []):
            try: log("  " + get(f"/send_card?k={k}", key).read().decode()[:80])
            except Exception as e: log(f"  send_card failed {str(e)[:60]}")

if __name__ == "__main__":
    main()
