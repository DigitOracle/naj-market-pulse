"""Digital-thread audit: follow every building from its footprint to the page a person reaches by tapping it.

Kendall, 29 Sep 2026: every building clickable with data connected - "this is also a test of the digital thread". A
building is only as connected as the weakest link in its chain, so this measures each link separately, per district,
from what the LIVE worker serves (not from disk: a file on disk that was never pushed is a broken link, as liwan1's
anchors were).

  1 footprint   data/ce/<slug>/buildings.geojson feature i              the source geometry
  2 model       a mesh named b<i> in the live default tile sky_<slug>    what the person sees
  3 map         anchors_<slug>.fps holds i                               how a tapped mesh finds its id
  4 record      unitmix_<slug> holds i                                   what the building page renders from
  5 facts       bldgfacts_<slug> holds i                                 height, storeys, floor area
  6 register    stack_<slug> holds i                                     DM floor register (floors, types, prices)
  7 name        anchors_<slug> names i                                   a title other than "Unnamed building"

"Tappable" = 2 and 3 and 4 (the v266 tap rule). "Connected" = tappable and 5. The weakest link per district is the
first one where the count drops most.

  python scripts/thread_audit.py                 all districts, table + logs/thread_audit_<date>.json
  python scripts/thread_audit.py arjan liwan1    just these
"""
import gzip
import json
import os
import re
import struct
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
CE = os.path.join(ROOT, "data", "ce")
W = "https://azimuth-2.digitalchemy.workers.dev/img/"
LINKS = ["footprint", "model", "map", "record", "facts", "register", "name"]


def fetch(key):
    # curl, not urllib: the worker refuses the Python-urllib user agent with 403 (see worker-repos memory).
    # Retried: on 30 Sep one failed fetch of anchors_dubaiproductioncity read as "no map" and reported 1,270 buildings
    # untappable that were fine. A 404 is an answer and returns at once; a transport error is not, and is retried.
    for attempt in range(4):
        r = subprocess.run(["curl", "-s", "--compressed", "-w", "\n%{http_code}", W + key], capture_output=True, timeout=300)
        body, _, code = r.stdout.rpartition(b"\n")
        if code == b"200":
            return body
        if code == b"404":
            return None
        time.sleep(3 * (attempt + 1))
    raise RuntimeError("could not fetch %s after 4 attempts (last HTTP %s) - not treating it as missing" % (key, code.decode() or "none"))


def js(key):
    b = fetch(key)
    try:
        return json.loads(b) if b else None
    except ValueError:
        return None


def tile_ids(slug):
    """Building ids present as named meshes/nodes in the live default tile."""
    b = fetch("sky_" + slug)
    if not b:
        return set()
    if b[:2] == b"\x1f\x8b":
        b = gzip.decompress(b)
    if b[:4] != b"glTF":
        return set()
    n = struct.unpack("<I", b[12:16])[0]
    j = json.loads(b[20:20 + n])
    ids = set()
    for nd in j.get("nodes", []) + j.get("meshes", []):
        m = re.match(r"b(\d+)", nd.get("name") or "")
        if m:
            ids.add(int(m.group(1)))
    return ids


def audit(slug):
    n = len(json.load(open(os.path.join(CE, slug, "buildings.geojson"), encoding="utf-8"))["features"])
    fp = set(range(n))
    an = js("anchors_" + slug) or {}
    s = {
        "footprint": fp,
        "model": tile_ids(slug) & fp,
        "map": {int(f[0]) for f in (an.get("fps") or []) if f and f[1] is not None} & fp,
        "record": {int(k) for k in ((js("unitmix_" + slug) or {}).get("buildings_by_id") or {})} & fp,
        "facts": {int(k) for k in ((js("bldgfacts_" + slug) or {}).get("buildings_by_id") or {})} & fp,
        "register": {int(k) for k in ((js("stack_" + slug) or {}).get("buildings_by_id") or {})} & fp,
        "name": {int(a["i"]) for a in (an.get("anchors") or []) if a.get("name")} & fp,
    }
    tap = s["model"] & s["map"] & s["record"]
    row = {k: len(v) for k, v in s.items()}
    row.update(slug=slug, tappable=len(tap), connected=len(tap & s["facts"]))
    # the weakest link: the biggest single drop along the chain footprint -> model -> map -> record
    chain = ["footprint", "model", "map", "record"]
    row["weakest"] = max(chain[1:], key=lambda k: row[chain[chain.index(k) - 1]] - row[k]) if row["tappable"] < n else ""
    return row


def main():
    slugs = [a for a in sys.argv[1:] if not a.startswith("--")] or sorted(
        d for d in os.listdir(CE) if os.path.exists(os.path.join(CE, d, "buildings.geojson")))
    rows = []
    print("%-26s %6s %6s %6s %6s %6s %6s %6s | %6s %5s  %s" % (
        "district", "fprint", "model", "map", "record", "facts", "regstr", "named", "tap", "%", "weakest link"))
    for s in slugs:
        r = audit(s)
        rows.append(r)
        print("%-26s %6d %6d %6d %6d %6d %6d %6d | %6d %4.0f%%  %s" % (
            s, r["footprint"], r["model"], r["map"], r["record"], r["facts"], r["register"], r["name"],
            r["tappable"], 100.0 * r["tappable"] / max(r["footprint"], 1), r["weakest"]), flush=True)
    t = {k: sum(r[k] for r in rows) for k in LINKS + ["tappable", "connected"]}
    print("%-26s %6d %6d %6d %6d %6d %6d %6d | %6d %4.0f%%" % (
        "TOTAL", t["footprint"], t["model"], t["map"], t["record"], t["facts"], t["register"], t["name"],
        t["tappable"], 100.0 * t["tappable"] / max(t["footprint"], 1)))
    out = os.path.join(ROOT, "logs", "thread_audit_%s.json" % time.strftime("%Y%m%d_%H%M"))
    json.dump({"generated": time.strftime("%Y-%m-%dT%H:%M:%S"), "links": LINKS, "totals": t, "districts": rows},
              open(out, "w", encoding="utf-8"), indent=1)
    print("\nwritten", os.path.relpath(out, ROOT))


if __name__ == "__main__":
    main()
