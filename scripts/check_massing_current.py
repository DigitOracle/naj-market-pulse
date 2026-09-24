"""Which districts are ACTUALLY finished, measured against source rather than remembered from a completed list.

  python scripts/check_massing_current.py            # every district
  python scripts/check_massing_current.py arjan      # one

WHY THIS EXISTS. The LOD 3 session, 24 Sep 2026: "districts I re-massed BEFORE a fix existed look finished and are
not, and there is no marker on disk that says which build carries which rule. My rollout state records the route and
not the rules that were live when it ran."

That is the real problem and it is not fixable by being more careful. A district re-massed on 22 September cannot know
about a rule wired on the 24th, and nothing in its output says which rules it was built under. So "re-massed" is not a
durable claim, a completed list is a record of what ran and not of what is correct, and the only method that has
worked all week is re-checking output against source.

This makes that method repeatable instead of a thing someone does by hand and forgets to redo. It answers one
question: **for each district, how many buildings are still standing at the massing placeholder while a real height
is already on disk for them?** Nothing else - it does not judge, re-mass, or write to any district.

THE THREE SOURCES IT CHECKS, all of which have been right about a building the massing had at 12 m:

    data/ce/<slug>/heights_register.json   DLD units register, floors x 3.2      the lift rule reads this
    data/names/anchors_<slug>.json         h where h_source is "dld floors"      apply_identity.py writes it
    data/ce/<slug>/buildings.geojson       bHeight, the massing's own input      already correct for 113 in
                                                                                Business Bay with no height_source

The first two agreed within 3 m on 188 of 189 buildings when this was first measured by hand, which is why the report
names WHICH sources back each building rather than merging them into one number.

WHAT IT DELIBERATELY DOES NOT DO. It does not read a rollout state, a completed list, or any record of what ran. Those
are exactly what cannot be trusted here - the whole point is that they say "done" for districts that are not. It reads
the current report and the current sources, every time.

A DISTRICT WITH ZERO IS NOT PROVEN FINISHED FOREVER. It is finished against the sources as they stand right now. Add a
source, or a rule, and the honest thing is to run this again - which is the cost of there being no rule marker, and
cheaper than the alternative of finding out from a clip.
"""
import csv
import glob
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLACEHOLDER_MAX = 12.7
REAL_MIN = 20.0


def massed(slug):
    """What the district's CURRENT report says was built, per footprint index. v4 if present, else v3."""
    for v in ("report_v4.csv", "report_v3.csv"):
        p = os.path.join(ROOT, "data", "ce", slug, v)
        if not os.path.exists(p):
            continue
        out = {}
        try:
            for r in csv.DictReader(open(p, encoding="utf-8-sig")):
                sh = str(r.get("shape") or "")
                if sh.startswith("b"):
                    try:
                        out[int(sh[1:].split("_")[0])] = float(r.get("height_m") or 0)
                    except Exception:
                        pass
        except Exception:
            continue
        return out, v, os.path.getmtime(p)
    return {}, None, 0


def sources(slug):
    """Every real height we hold for this district, by index, tagged with where it came from."""
    out = {}

    p = os.path.join(ROOT, "data", "ce", slug, "heights_register.json")
    if os.path.exists(p):
        try:
            for k, v in (json.load(open(p, encoding="utf-8")).get("heights") or {}).items():
                out.setdefault(int(k), {})["register"] = float(v)
        except Exception:
            pass

    p = os.path.join(ROOT, "data", "names", "anchors_%s.json" % slug)
    if os.path.exists(p):
        try:
            for a in (json.load(open(p, encoding="utf-8")).get("anchors") or []):
                h, i = a.get("h"), a.get("i")
                # only a height the register put there - the massing's own value would compare with itself
                if i is not None and h and a.get("h_source"):
                    out.setdefault(int(i), {})["anchor"] = float(h)
        except Exception:
            pass

    p = os.path.join(ROOT, "data", "ce", slug, "buildings.geojson")
    if os.path.exists(p):
        try:
            for i, f in enumerate(json.load(open(p, encoding="utf-8"))["features"]):
                h = (f.get("properties") or {}).get("bHeight")
                if h:
                    out.setdefault(i, {})["geojson"] = float(h)
        except Exception:
            pass
    return out


def names(slug):
    p = os.path.join(ROOT, "data", "names", "anchors_%s.json" % slug)
    if not os.path.exists(p):
        return {}
    try:
        return {int(a["i"]): a.get("name") for a in (json.load(open(p, encoding="utf-8")).get("anchors") or [])
                if a.get("i") is not None}
    except Exception:
        return {}


def check(slug):
    M, ver, mt = massed(slug)
    if not M:
        return None
    S, NM = sources(slug), names(slug)
    rows = []
    for i, h in M.items():
        if h > PLACEHOLDER_MAX:
            continue
        got = {k: v for k, v in (S.get(i) or {}).items() if v >= REAL_MIN}
        if not got:
            continue
        rows.append({"i": i, "name": NM.get(i), "massed_m": round(h, 1),
                     "available_m": round(max(got.values()), 1),
                     "from": sorted(got), "sources": {k: round(v, 1) for k, v in got.items()}})
    rows.sort(key=lambda r: -r["available_m"])
    return {"district": slug, "report": ver, "report_written": mt, "buildings": len(M),
            "still_placeholder_with_a_real_height": len(rows), "rows": rows}


def main(slugs):
    if not slugs:
        slugs = sorted({os.path.basename(os.path.dirname(p)) for p in
                        glob.glob(os.path.join(ROOT, "data", "ce", "*", "report_v*.csv"))})
    out, total = [], 0
    for s in slugs:
        r = check(s)
        if r is None:
            continue
        out.append(r)
        total += r["still_placeholder_with_a_real_height"]
    out.sort(key=lambda r: -r["still_placeholder_with_a_real_height"])

    import time
    dest = os.path.join(ROOT, "data", "board", "massing_not_current.json")
    json.dump({"checked": time.strftime("%Y-%m-%dT%H:%M:%S"), "districts": len(out), "buildings": total,
               "rule": "massed at or below %.1f m while a source holds >= %.0f m" % (PLACEHOLDER_MAX, REAL_MIN),
               "note": "measured against the CURRENT report and the CURRENT sources. Reads no rollout state and no "
                       "completed list, because those say done for districts that are not. Zero means finished "
                       "against the sources as they stand now, not finished forever.",
               "results": out}, open(dest, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    print("%d buildings across %d districts are massed at the placeholder with a real height on disk\n" % (total, len(out)))
    print("   %-26s %-11s %6s  %s" % ("district", "report", "left", "tallest missed"))
    for r in out:
        if not r["still_placeholder_with_a_real_height"]:
            continue
        t = r["rows"][0]
        print("   %-26s %-11s %6d  %6.1f m  %s" % (r["district"], r["report"],
                                                   r["still_placeholder_with_a_real_height"],
                                                   t["available_m"], (t["name"] or "")[:30]))
    clean = [r["district"] for r in out if not r["still_placeholder_with_a_real_height"]]
    print("\n   current against every source: %d districts (%s%s)"
          % (len(clean), ", ".join(clean[:6]), " …" if len(clean) > 6 else ""))
    print("-> " + dest)


if __name__ == "__main__":
    main([a for a in sys.argv[1:] if not a.startswith("-")])
