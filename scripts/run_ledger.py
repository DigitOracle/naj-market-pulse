"""Run ledger: every scheduled chain writes down what each step did, so a quiet morning can be told apart from a broken one.

Data Spine Phase 1 (13 Sep 2026). Before this, daily_refresh.ps1 ran top to bottom with ErrorActionPreference Continue and
ignored every exit code except the listener check. A failed fetch still rebuilt the pulse from the previous file and pushed
it, a failed build left yesterday's cards in place, and nothing anywhere recorded that either had happened. Eight silent
failures in the 8-12 Sep handovers came from that shape.

Each run now leaves:
  data/runs/<yyyy-mm-dd>/<chain>_<HHMMSS>.json   every step: status, exit code, seconds, note; plus the holds contracts placed
  data/runs/runs.jsonl                            one summary line per run, newest last

Step statuses:
  ok          exit code accepted by the step
  warn        accepted, but worth a line to Kendall (the listener lost coverage, a sheet parsed to zero units)
  held        a contract refused to publish a feed; the chain carries on with the last good version
  failed      exit code outside the accepted set, a timeout, or an exception
  skipped     a step it depends on did not succeed, so running it would publish from stale or broken inputs
  not-needed  its condition was false (the sweep found no new sheet)
data/ is git-ignored, so the ledger never reaches GitHub.
"""
import collections, datetime as dt, json, os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
RUNS = os.path.join(ROOT, "data", "runs")

ALERT = ("failed", "held", "warn")


class Run:
    def __init__(self, chain):
        self.chain = chain
        self.started = dt.datetime.now()
        self.id = "%s_%s" % (chain, self.started.strftime("%Y%m%d_%H%M%S"))
        self.steps = []
        self.holds = []
        self.path = None

    def record(self, step, status, code=None, seconds=None, note=""):
        self.steps.append({"step": step, "status": status, "exit": code,
                           "seconds": None if seconds is None else round(seconds, 1), "note": (note or "")[:400]})

    def status_of(self, step):
        for s in reversed(self.steps):
            if s["step"] == step:
                return s["status"]
        return None

    def hold(self, feed, reason):
        self.holds.append({"feed": feed, "reason": (reason or "")[:400]})

    def counts(self):
        return dict(collections.Counter(s["status"] for s in self.steps))

    def needs_alert(self):
        return bool(self.holds) or any(s["status"] in ALERT for s in self.steps)

    def headline(self):
        """One line for Kendall. Names what broke first, because that is what he acts on."""
        when = self.started.strftime("%d %b %H:%M")
        bad = [s for s in self.steps if s["status"] == "failed"]
        warn = [s for s in self.steps if s["status"] == "warn"]
        skipped = [s for s in self.steps if s["status"] == "skipped"]
        parts = []
        if bad:
            parts.append("%d failed (%s)" % (len(bad), "; ".join("%s exit %s" % (s["step"], s["exit"]) for s in bad[:3])))
        if skipped:
            parts.append("%d skipped after it" % len(skipped))
        if self.holds:
            parts.append("%d held (%s)" % (len(self.holds), "; ".join(h["reason"][:90] for h in self.holds[:2])))
        if warn:
            parts.append("%d warning (%s)" % (len(warn), "; ".join((s["note"] or s["step"])[:90] for s in warn[:2])))
        if not parts:
            parts.append("all %d steps ok" % len(self.steps))
        rel = os.path.relpath(self.path, ROOT) if self.path else "data/runs"
        return "Najma %s %s: %s. Ledger %s" % (self.chain, when, ", ".join(parts), rel.replace("\\", "/"))

    def finish(self):
        day = os.path.join(RUNS, self.started.strftime("%Y-%m-%d"))
        os.makedirs(day, exist_ok=True)
        self.path = os.path.join(day, "%s_%s.json" % (self.chain, self.started.strftime("%H%M%S")))
        ended = dt.datetime.now()
        doc = {"run": self.id, "chain": self.chain, "started": self.started.isoformat(timespec="seconds"),
               "ended": ended.isoformat(timespec="seconds"), "seconds": round((ended - self.started).total_seconds(), 1),
               "counts": self.counts(), "holds": self.holds, "steps": self.steps}
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, indent=1)
        line = {k: doc[k] for k in ("run", "chain", "started", "ended", "seconds", "counts")}
        line["holds"] = len(self.holds)
        line["alert"] = self.needs_alert()
        with open(os.path.join(RUNS, "runs.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps(line, ensure_ascii=False) + "\n")
        return doc


def last_runs(n=10):
    p = os.path.join(RUNS, "runs.jsonl")
    if not os.path.exists(p):
        return []
    with open(p, encoding="utf-8") as f:
        return [json.loads(x) for x in f.read().splitlines()[-n:] if x.strip()]


if __name__ == "__main__":
    for r in last_runs(20):
        print("%-34s %-8s %6ss holds=%s alert=%s %s" % (r["run"], r["chain"], r["seconds"], r["holds"], r["alert"], r["counts"]))
