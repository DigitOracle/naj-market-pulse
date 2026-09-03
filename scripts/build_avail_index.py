"""Developer-availability index for the board strip (KV img_avail_index) + claimed-units merge for the drill pages.

Reads every data/avail/<developer>_<date>[_auto].json (hand-verified beats _auto for the same developer+date; newest
sheet date wins per developer), then:
  1. pushes img_avail_index = {"updated", "sheets":[{"sheet","note","mapped","d"}]}  (board strip, v68)
  2. for each developer with a drill key, merges claimed availability into drill_<key>:
        claimed = {"as_of", "source", "rooms":[{"r","n","from"}], "detail":[{"p","completion","plan","units":[...]}]}
     (drill_<key> base = registered mix from build_avail_drill.py; we read the current KV copy, patch, push back)
Run after extract_avail.py --scan in the daily refresh. Needs INGEST_TOKEN (listener .env) and READ_KEY for the KV read.
"""
import base64, collections, datetime as dt, glob, json, os, re, sys, urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
AVAIL = os.path.join(ROOT, "data", "avail")
WORKER = "https://azimuth-2.digitalchemy.workers.dev"
DRILL_KEY = {"imtiaz": "imtiaz"}          # developer slug -> drill_<key>; extend as developers join the group


def env_token(name):
    for line in open(r"C:\Dev\azimuth-listener-naj\.env", encoding="utf-8"):
        if line.startswith(name + "="):
            return line.split("=", 1)[1].strip()
    return os.environ.get(name)


def push(name, obj, tok):
    raw = json.dumps(obj, ensure_ascii=False).encode()
    body = json.dumps({"imageName": name, "image": base64.b64encode(raw).decode(), "contentType": "application/json"}).encode()
    req = urllib.request.Request(WORKER + "/ingest_market", data=body, method="POST",
                                 headers={"X-Azimuth-Ingest": tok, "Content-Type": "application/json", "User-Agent": "najma-market-pulse/1.0"})
    return json.load(urllib.request.urlopen(req, timeout=60))


def latest_sheets():
    best = {}
    for p in glob.glob(os.path.join(AVAIL, "*.json")):
        b = os.path.basename(p)
        if b.startswith("_"):
            continue
        m = re.match(r"([a-z0-9]+)_(\d{4}-\d{2}-\d{2})(_auto)?\.json$", b)
        if not m:
            continue
        dev, date, auto = m.group(1), m.group(2), bool(m.group(3))
        rank = (date, 0 if auto else 1)          # newest date; verified beats auto on the same date
        if dev not in best or rank > best[dev][0]:
            best[dev] = (rank, p, auto)
    return {dev: (path, auto) for dev, (rank, path, auto) in best.items()}


def claimed_for_dev(dev):
    """Claimed-availability block for drill_<key>, from the newest sheet of this developer (None if no sheet)."""
    sheets = latest_sheets()
    if dev not in sheets:
        return None
    path, auto = sheets[dev]
    d = json.load(open(path, encoding="utf-8"))
    rooms = collections.OrderedDict()
    for p in d["projects"]:
        for u in p["units"]:
            r = rooms.setdefault(u[1], {"r": u[1], "n": 0, "from": None})
            r["n"] += 1
            if u[3]:
                r["from"] = u[3] if r["from"] is None else min(r["from"], u[3])
    return {"as_of": d.get("sheet_date"), "received": d.get("received"),
            "source": d.get("developer", dev.title()) + (" sheet (auto-read; verify before quoting)" if auto else " sheet"),
            "rooms": list(rooms.values()),
            "detail": [{"p": p["p"], "completion": p.get("completion"), "plan": p.get("plan"), "units": p["units"]} for p in d["projects"]]}


def main():
    tok = env_token("INGEST_TOKEN")
    read_key = env_token("READ_KEY") or os.environ.get("READ_KEY")
    sheets, out = latest_sheets(), []
    for dev, (path, auto) in sorted(sheets.items()):
        d = json.load(open(path, encoding="utf-8"))
        n_units = sum(len(p["units"]) for p in d["projects"])
        key = DRILL_KEY.get(dev)
        out.append({"sheet": "%s %s" % (dev.title(), d.get("sheet_date", "")), "note": "%d units · %d projects%s" % (n_units, len({p["p"] for p in d["projects"]}), " · auto-read" if auto else ""),
                    "mapped": bool(key), "d": key})
    idx = {"updated": dt.date.today().isoformat(), "sheets": out}
    r = push("avail_index", idx, tok)
    print("avail_index ->", r.get("ok"), out)


if __name__ == "__main__":
    main()
