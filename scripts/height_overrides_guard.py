"""Keep reviewed heights on the building they were reviewed for.

scripts/height_overrides.json keys each reviewed height by FOOTPRINT INDEX. If a district's buildings.geojson is ever
reordered or a feature is inserted anywhere but the end, every later index shifts, and each reviewed height silently
lands on a neighbour, with nothing in any log. Flagged by the height-handles lab agent on 30 Sep 2026.

Each entry now carries "fp": {"lon", "lat", "area_m2"} of the footprint it was reviewed on. filter() keeps an entry
only while the footprint at that index still matches (centroid within MATCH_M, area within MATCH_AREA), and logs
every entry it drops. An entry without "fp" is still applied, with a warning, until it is stamped.

  python scripts/height_overrides_guard.py --check           verify every entry against the current geojson
  python scripts/height_overrides_guard.py --stamp           add "fp" to entries that lack one (review the diff)
"""
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PATH = os.path.join(HERE, "height_overrides.json")
MATCH_M = 3.0          # centroid drift allowed (re-digitised outline, not a different building)
MATCH_AREA = 0.10      # relative area change allowed


def _ring(geom):
    c = geom["coordinates"]
    return c[0] if geom["type"] == "Polygon" else c[0][0]


def fingerprint(feature):
    """Centroid (lon, lat) and area (m2) of the outer ring, equirectangular - ample for a same-building test."""
    r = _ring(feature["geometry"])
    lat0 = sum(p[1] for p in r) / len(r)
    kx, ky = 111320.0 * math.cos(math.radians(lat0)), 110540.0
    pts = [((p[0]) * kx, (p[1]) * ky) for p in r]
    a = cx = cy = 0.0
    for (x1, y1), (x2, y2) in zip(pts, pts[1:] + pts[:1]):
        cr = x1 * y2 - x2 * y1
        a += cr; cx += (x1 + x2) * cr; cy += (y1 + y2) * cr
    if abs(a) < 1e-9:
        return {"lon": round(sum(p[0] for p in r) / len(r), 7), "lat": round(lat0, 7), "area_m2": 0.0}
    cx, cy = cx / (3 * a), cy / (3 * a)
    return {"lon": round(cx / kx, 7), "lat": round(cy / ky, 7), "area_m2": round(abs(a) / 2, 1)}


def matches(fp, feature):
    now = fingerprint(feature)
    kx = 111320.0 * math.cos(math.radians(fp["lat"]))
    d = math.hypot((now["lon"] - fp["lon"]) * kx, (now["lat"] - fp["lat"]) * 110540.0)
    da = abs(now["area_m2"] - fp["area_m2"]) / max(fp["area_m2"], 1.0)
    return d <= MATCH_M and da <= MATCH_AREA, d, da


def filter(slug, entries, feats, log=print):
    """Return only the override entries whose footprint is still the one they were reviewed on."""
    keep = {}
    for k, e in (entries or {}).items():
        i = int(k)
        if i >= len(feats):
            log("  HEIGHT OVERRIDE DROPPED %s b%s: index beyond %d footprints" % (slug, k, len(feats))); continue
        fp = e.get("fp")
        if fp is None:
            log("  height override %s b%s has no fingerprint - applied unchecked (run height_overrides_guard.py --stamp)" % (slug, k))
            keep[k] = e; continue
        ok, d, da = matches(fp, feats[i])
        if not ok:
            log("  HEIGHT OVERRIDE DROPPED %s b%s: footprint moved %.1f m / area %+.0f%% - the geojson was reordered or "
                "re-digitised; re-review this entry" % (slug, k, d, 100 * da)); continue
        keep[k] = e
    return keep


def _feats(slug):
    return json.load(open(os.path.join(ROOT, "data", "ce", slug, "buildings.geojson"), encoding="utf-8"))["features"]


def main():
    doc = json.load(open(PATH, encoding="utf-8"))
    bad = stamped = 0
    for slug, entries in doc.get("districts", {}).items():
        feats = _feats(slug)
        for k, e in entries.items():
            i = int(k)
            if i >= len(feats):
                print("%-24s b%-5s INDEX OUT OF RANGE (%d footprints)" % (slug, k, len(feats))); bad += 1; continue
            if "fp" not in e:
                if "--stamp" in sys.argv:
                    e["fp"] = fingerprint(feats[i]); stamped += 1
                    print("%-24s b%-5s stamped %s  name=%r" % (slug, k, e["fp"], feats[i]["properties"].get("name")))
                else:
                    print("%-24s b%-5s no fingerprint yet  name=%r" % (slug, k, feats[i]["properties"].get("name")))
                continue
            ok, d, da = matches(e["fp"], feats[i])
            print("%-24s b%-5s %s  drift %.2f m, area %+.1f%%" % (slug, k, "OK   " if ok else "MOVED", d, 100 * da))
            bad += 0 if ok else 1
    if stamped:
        json.dump(doc, open(PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print("\nstamped %d entries - review the diff before committing" % stamped)
    print("%d entries failing" % bad)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
