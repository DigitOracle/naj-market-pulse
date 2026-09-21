"""Morning feed watch: did Naj get five fresh angles on fresh data today? If not, one line to Kendall. Never to Naj.

19 Sep 2026 (Kendall: "make sure this is what happens every day"). That morning she got ONE angle and nobody knew until she
said so: the 06:30 refresh had failed with no network, so the feed read two-day-old data, and the repeat check dropped every
angle but one. This runs at 06:20 GST from the scheduled task Najma_Feed_Watch, after the 06:00 feed, and checks, from the
Worker's own store (wrangler, Kendall's Cloudflare login on this PC):
  1. mktfeed_<today> is "done"                    - the feed ran and succeeded
  2. mkt_briefctx was written today, with 5 angles - she got five, not fewer
  3. mkt_latest.generatedAt is today (UTC date)    - the five were built on this morning's data
Anything short of that is a single WhatsApp line to Kendall through notify_owner.py. It changes nothing and sends nothing
to Naj; the fix is a human decision (rebuild today's five by hand, as on 19 Sep, or let tomorrow run).

Usage: python scripts/feed_watch.py [--dry]     (--dry prints the verdict and does not alert)
"""
import datetime as dt, json, os, subprocess, sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
WORKER_DIR = r"C:\Dev\azimuth-worker-dewa"
GST = dt.timezone(dt.timedelta(hours=4))


def kv(key):
    r = subprocess.run("npx wrangler kv key get %s --binding=MEETINGS --env=azimuth2 --text" % key, cwd=WORKER_DIR, shell=True,
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180)
    return (r.stdout or "").strip()


def main():
    now = dt.datetime.now(GST); today = now.strftime("%Y-%m-%d")
    problems = []
    # v186 (21 Sep): a morning can be HELD because her 24-hour WhatsApp window is shut. That is not a failure -
    # it flushes on her next message - but Kendall should know it is waiting, so it is reported on its own.
    pending = kv("mkt_feed_pending")
    if pending:
        line = "Naj's morning feed, %s: HELD - her 24-hour WhatsApp window is shut, so it waits for her next message (v186 nudge sent)." % today
        print(line)
        if "--dry" not in sys.argv:
            subprocess.run([sys.executable, os.path.join(HERE, "notify_owner.py"), line], timeout=120)
        return 0
    marker = kv("mktfeed_" + today)
    if marker != "done":
        problems.append("the feed did not complete (marker %r)" % (marker or "none"))
    try:
        ctx = json.loads(kv("mkt_briefctx") or "null") or {}
    except Exception:
        ctx = {}
    n = len(ctx.get("angles") or [])
    at = dt.datetime.fromtimestamp((ctx.get("at") or 0) / 1000, GST).strftime("%Y-%m-%d") if ctx.get("at") else "never"
    if at != today:
        problems.append("no feed was written today (last %s)" % at)
    elif n < 5:
        problems.append("she got %d angle%s, not 5" % (n, "" if n == 1 else "s"))
    try:
        gen = (json.loads(kv("mkt_latest") or "null") or {}).get("generatedAt") or ""
    except Exception:
        gen = ""
    if gen[:10] != now.astimezone(dt.timezone.utc).strftime("%Y-%m-%d"):
        problems.append("market data is from %s, not today (did the 05:00 refresh run?)" % (gen[:10] or "unknown"))
    # v184/v185 (Azimuth Rings, 19 Sep): the QA note ends "five-floor: N sent (P plan, R real estate)" and feed_scenes_last
    # counts the scene cards queued. Read both when present; older workers simply lack them.
    try:
        qa = (json.loads(kv("mkt_feed_qa") or "null") or {}).get("note") or ""
    except Exception:
        qa = ""
    if "five-floor:" in qa:
        tail = qa.split("five-floor:", 1)[1].strip()
        try:
            sent = int(tail.split()[0])
            if sent < 5:
                problems.append("QA says only %d sent (%s)" % (sent, tail[:60]))
        except ValueError:
            pass
    if "CHECK FAILED" in qa:
        problems.append("the feed's own check failed (%s)" % qa.split("CHECK FAILED", 1)[1][:80].strip(": "))
    try:
        audit = json.loads(kv("mkt_feed_audit") or "null") or {}
    except Exception:
        audit = {}
    for f in (audit.get("failures") or audit.get("problems") or [])[:3]:
        problems.append("morning audit: %s" % str(f)[:80])
    # v186: pictures are no longer made automatically - the morning ends with "Make all five / I'll choose",
    # so zero scene jobs is normal. feed_scenes_last is read for the record only, never as a fault.
    if not problems:
        print("feed ok: %d angles, data %s%s" % (n, gen[:16], (" | " + qa[-60:]) if qa else "")); return 0
    line = "Naj's morning feed, %s: %s. Say 'rebuild her feed' to redo today's five." % (today, "; ".join(problems))
    print(line)
    if "--dry" not in sys.argv:
        subprocess.run([sys.executable, os.path.join(HERE, "notify_owner.py"), line], timeout=120)
    return 1


if __name__ == "__main__":
    sys.exit(main())
