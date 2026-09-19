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
    if not problems:
        print("feed ok: %d angles, data %s" % (n, gen[:16])); return 0
    line = "Naj's morning feed, %s: %s. Say 'rebuild her feed' to redo today's five." % (today, "; ".join(problems))
    print(line)
    if "--dry" not in sys.argv:
        subprocess.run([sys.executable, os.path.join(HERE, "notify_owner.py"), line], timeout=120)
    return 1


if __name__ == "__main__":
    sys.exit(main())
