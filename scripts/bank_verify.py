"""Staleness check for the question bank: is each ANSWERED question still true, and on how old a data?

Assigned by Kendall via the audit (29 Sep 2026): "today the bank cannot tell anyone which of the 74 answered
questions is still true". For every answered question this records, in questions/bank.json:

    "verified": {"at": date of this check,
                 "data_age_days": age of the OLDEST artefact behind the answer - the file's own "generated" date
                                  where it carries one, its modified time otherwise (an answer checked today off
                                  week-old files must not read as fresh - the audit's own point),
                 "artefacts": the files the question's source names (globs for per-district families),
                 "value": a live measure from the data (records of the question's kind), and the previous one,
                 "screen": "ok" / "down" / "n/a" - the screen its `where` names answers with HTTP 200,
                 "flag": "" or why a person should look: stale data, a missing file, a value that moved >20%,
                         a screen that is down}

    python scripts/bank_verify.py [--max-age 7] [--no-screens]

Prints a summary and exits 1 when any answered question is flagged, so a scheduled run can alert. It is NOT
scheduled: a standing nightly job waits for Kendall's own go (29 Sep).
"""
import datetime as dt
import glob
import io
import json
import os
import re
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BANK = os.path.join(ROOT, "questions", "bank.json")
PATH_RX = re.compile(r"((?:data|public)/[A-Za-z0-9_./<>*-]+\.(?:json|geojson|csv|kml))")
BARE_RX = re.compile(r"(?<![/\w])([A-Za-z0-9_<>*-]+\.(?:json|geojson|csv))")   # a file named without its folder
LOOK_IN = ("data/board", "public", "data")
REGISTER_RX = re.compile(r"\b(DLD|RTA|DHA|KHDA|DEWA|DM|RERA|Ejari|register|lake|g_[a-z_]+)\b")
SCREENS = {"MAP": "/map", "AREA": "/area", "AVAIL": "/avail", "DEV": "/dev", "COMPARE": "/compare",
           "BUILDING": "/building", "MARKET": "/market", "TRENDS": "/trends", "TWIN": "/skyline/businessbay",
           "PULSE": "/market", "FIND": "/find", "CARDS": "/cards", "HOME": "/home", "VIEW": "/view"}
KINDS = ["supermarket", "pharmacy", "hospital", "clinic", "mall", "park", "beach", "school", "metro", "ev"]


def arg(name, default):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


def artefacts(q):
    """The data files a question's source names - '<slug>' placeholders become globs over every district."""
    out, src = [], q.get("source") or ""
    for p in PATH_RX.findall(src):
        p = re.sub(r"<[^>]+>", "*", p.rstrip("."))
        out.append((p, sorted(glob.glob(os.path.join(ROOT, p)))))
    for name in BARE_RX.findall(PATH_RX.sub("", src)):
        name = re.sub(r"<[^>]+>", "*", name)
        hits = []
        for base in LOOK_IN:
            hits = sorted(glob.glob(os.path.join(ROOT, base, name)))
            if hits:
                out.append((base + "/" + name, hits))
                break
        else:
            out.append((name, []))
    return out


def generated(path):
    """A file's own 'generated' date when it states one, else its modified time."""
    if path.endswith((".json", ".geojson")) and os.path.getsize(path) < 60_000_000:
        try:
            with io.open(path, encoding="utf-8") as f:
                head = f.read(4000)
            m = re.search(r'"generated"\s*:\s*"(\d{4}-\d{2}-\d{2}[ T]?\d{0,2}:?\d{0,2})', head)
            if m:
                return dt.datetime.fromisoformat(m.group(1).strip().replace(" ", "T")[:16].rstrip("T:"))
        except (OSError, ValueError):
            pass
    return dt.datetime.fromtimestamp(os.path.getmtime(path))


def live_value(q, files):
    """A number from the data that should move only when the answer does."""
    kind = next((k for k in KINDS if any(k in str(x).lower() for x in [q.get("question", "")] + q.get("keys", []))),
                None)
    for f in files:
        if f.endswith("amenities.json") and kind:
            try:
                items = json.load(io.open(f, encoding="utf-8")).get("items", [])
                return {"kind": kind, "records": sum(1 for i in items if i.get("k") == kind)}
            except (OSError, ValueError):
                return None
    if files:
        f = files[0]
        try:
            d = json.load(io.open(f, encoding="utf-8")) if f.endswith((".json", ".geojson")) else None
        except (OSError, ValueError):
            d = None
        if isinstance(d, list):
            return {"records": len(d)}
        if isinstance(d, dict):
            for k in ("items", "features", "rows", "buildings", "records"):
                if isinstance(d.get(k), list):
                    return {"records": len(d[k])}
            return {"keys": len(d)}
    return None


_screen_cache = {}


def screen_ok(where):
    routes = [SCREENS[w] for w in re.findall(r"\b([A-Z]{3,})\b", where or "") if w in SCREENS]
    if not routes or "--no-screens" in sys.argv:
        return "n/a"
    route = routes[0]
    if route not in _screen_cache:
        try:
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            os.environ.setdefault("NAJMA_VIDEO", "10")
            import demo_capture as D                       # the CLIENT-key URL; the key itself is never printed
            req = urllib.request.Request(D.url(route), headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                         "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0 Safari/537.36"})
            with urllib.request.urlopen(req, timeout=40) as r:    # the edge 403s a bare urllib user agent
                _screen_cache[route] = "ok" if r.status == 200 else "down"
        except Exception:
            _screen_cache[route] = "down"
    return _screen_cache[route]


def main():
    max_age = float(arg("--max-age", "7"))
    now = dt.datetime.now()
    bank = json.load(io.open(BANK, encoding="utf-8"))
    flagged = []
    ages = []
    for q in bank["questions"]:
        if q.get("status") != "answered":
            q.pop("verified", None)
            continue
        named = artefacts(q)
        files = [f for _, hits in named for f in hits]
        missing = [p for p, hits in named if not hits]
        age = max(((now - generated(f)).total_seconds() / 86400 for f in files), default=None)
        prev = (q.get("verified") or {}).get("value")
        val = live_value(q, files)
        scr = screen_ok(q.get("where"))
        why = []
        register_only = not named and bool(REGISTER_RX.search(q.get("source") or ""))
        if not named and not register_only:
            why.append("no data file named in source")
        if missing:
            why.append("missing: " + ", ".join(missing))
        if age is not None and age > max_age:
            why.append("data %.0f days old" % age)
        if prev and val and prev.get("records") and val.get("records") is not None:
            if abs(val["records"] - prev["records"]) / max(1, prev["records"]) > 0.2:
                why.append("value moved %s -> %s" % (prev["records"], val["records"]))
        if scr == "down":
            why.append("screen down")
        q["verified"] = {"at": now.strftime("%Y-%m-%d %H:%M"),
                         "data_age_days": None if age is None else round(age, 1),
                         "artefacts": [os.path.relpath(f, ROOT).replace("\\", "/") for f in files][:6]
                                      + (["... +%d more" % (len(files) - 6)] if len(files) > 6 else []),
                         "value": val, "previous": prev, "screen": scr,
                         "basis": "register (not file-checked)" if register_only else "files",
                         "flag": "; ".join(why)}
        if age is not None:
            ages.append(age)
        if why:
            flagged.append((q["id"], "; ".join(why)))
    io.open(BANK, "w", encoding="utf-8").write(json.dumps(bank, ensure_ascii=False))
    n = sum(1 for q in bank["questions"] if q.get("status") == "answered")
    print("answered %d | flagged %d | data age median %.1f d, oldest %.1f d" %
          (n, len(flagged), sorted(ages)[len(ages) // 2] if ages else 0, max(ages) if ages else 0))
    for qid, why in flagged:
        print("  %s  %s" % (qid, why))
    return 1 if flagged else 0


if __name__ == "__main__":
    sys.exit(main())
