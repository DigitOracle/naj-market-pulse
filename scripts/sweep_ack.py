"""After a sweep: tell Naj, briefly, what came in and what was captured (Kendall, 8 Sep 2026: "quick and clean... it just needs
to know it is captured and what information was captured").

Reads data/avail/_processed.json for entries newer than the last acknowledgement (data/avail/_acked.json), sums them up, and
sends one short WhatsApp message through the Azimuth Worker (Naj's instance), signed off the way every update to her is.
Zero-unit parses are mentioned as "could not be read yet", never hidden.

Usage: python scripts/sweep_ack.py [--dry] [--send] [--since 2026-09-08T00:00]
  --dry   print the message, send nothing, do not mark as acknowledged (default)
  --send  send it and record the acknowledgement
"""
import json, os, sys, urllib.parse, urllib.request
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
from build_avail_index import env_token, WORKER  # noqa: E402
AVAIL = os.path.join(ROOT, "data", "avail"); REG = os.path.join(AVAIL, "_processed.json"); ACK = os.path.join(AVAIL, "_acked.json")
SIGNOFF = "— Black Coffee, curated by Papi"
NL = chr(10)


def compose(entries, files):
    ok = [e for e in entries if e.get("units")]; bad = [e for e in entries if not e.get("units")]
    devs, units, projects, plans = [], 0, 0, 0
    for out in sorted({e["out"] for e in ok}):
        doc = files.get(out) or {}
        dev = doc.get("developer") or out.split("_")[0].title()
        if dev not in devs: devs.append(dev)
        ps = doc.get("projects") or []
        projects += len(ps); units += sum(len(p.get("units") or []) for p in ps); plans += sum(1 for p in ps if p.get("plan"))
    n = len(entries); s = "s" if n != 1 else ""
    lines = [f"Availability update: pulled {n} sheet{s} from the developer group" + (f" ({', '.join(devs)})" if devs else "") + "."]
    got = []
    if units: got.append(f"pricing and availability for {units} units across {projects} projects")
    if plans: got.append("payment plans")
    got.append("no floor plans in this batch")
    lines.append("Captured: " + "; ".join(got) + ".")
    if ok: lines.append("Now in the HOMES cards, remaining stock, search, map and twin.")
    if bad: lines.append(f"{len(bad)} sheet{'s' if len(bad) != 1 else ''} could not be read yet - flagged for a parser fix.")
    lines += ["", SIGNOFF]
    return NL.join(lines)


def main():
    send = "--send" in sys.argv
    since = sys.argv[sys.argv.index("--since") + 1] if "--since" in sys.argv else None
    reg = json.load(open(REG, encoding="utf-8")) if os.path.exists(REG) else {}
    acked = json.load(open(ACK, encoding="utf-8")) if os.path.exists(ACK) else {"hashes": [], "last": None}
    cutoff = since or acked.get("last") or "1970-01-01T00:00:00"
    entries = [dict(v, hash=h) for h, v in reg.items() if v.get("when", "") > cutoff and h not in acked["hashes"]]
    if not entries:
        print("nothing new to acknowledge"); return
    files = {}
    for e in entries:
        out = e.get("out")
        if out and out not in files and os.path.exists(os.path.join(AVAIL, out)):
            try: files[out] = json.load(open(os.path.join(AVAIL, out), encoding="utf-8"))
            except Exception: files[out] = {}
    msg = compose(entries, files)
    print(msg)
    if not send:
        print(NL + "[dry run - not sent, not marked]"); return
    key = env_token("READ_KEY")
    # the Worker's admin-keyed one-off message route (GET /announce?key=&text=, <= 3500 chars) - delivers to Naj's number on her instance
    req = urllib.request.Request(f"{WORKER}/announce?key={urllib.parse.quote(key)}&text={urllib.parse.quote(msg[:3400])}", headers={"User-Agent": "najma-sweep-ack"})
    r = urllib.request.urlopen(req, timeout=60).read().decode("utf-8", "replace")
    print("sent ->", r)
    acked["hashes"] = sorted(set(acked["hashes"] + [e["hash"] for e in entries])); acked["last"] = max(e["when"] for e in entries)
    json.dump(acked, open(ACK, "w", encoding="utf-8"), indent=1)


if __name__ == "__main__":
    main()
