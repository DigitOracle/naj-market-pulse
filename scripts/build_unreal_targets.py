"""Choose which Business Bay buildings are worth a per-building Unreal clip, and say honestly where each height came from.

  python scripts/build_unreal_targets.py businessbay

WHY THIS REPLACES A FILTER I WROTE YESTERDAY. The first target list took every building with a NAMED height_source and
h >= 60 m, and got 108. That guard was meant to keep guesses out of the render set. Applied to this data it did close to
the opposite: it excluded the best buildings in the district and kept some of the weakest.

Measured on data/ce/businessbay/buildings.geojson, 23 Sep 2026:

    113 buildings of 60 m or more were excluded for height_source = None. They carry a bHeight, the export built
    them at it (110 of 113 agree to within 0.5 m), and 91 of them have a name:

        b573  595.0 m  Burj Binghatti Jacob & Co Residences
        b3    355.0 m  JW Marriott Marquis Hotel
        b603  348.0 m  Safa Two
        b574  345.0 m  Al Habtoor Tower
        b541  258.0 m  Paramount Hotel Midtown

    Those are the Business Bay skyline. Their heights are round real-world figures and match the buildings. What
    they lack is not a height, it is a RECORDED PROVENANCE: height_source and height_basis are both null.

    Meanwhile the 108 that passed the guard have bases like "osm height x 30% of this footprint" - a stated height
    split proportionally across a footprint the building shares - and "osm levels 20 (stated height implausible for
    the floor count)". Those are inferences. They are honest inferences and worth keeping, but a named-but-derived
    basis is not stronger evidence than an unnamed-but-exact figure, and the filter treated it as though it were.

So the guard is no longer "is there a named source" but "is there a height at all, is the building tall, and does it
have a name a viewer could recognise". Provenance is carried per building instead of deciding membership, because the
place to be honest about a weak source is on the clip, not by silently dropping the building.

    exact       height_source names a measurement, or the figure is a recorded landmark height
    derived     osm height apportioned across a shared footprint, or levels x storey height
    unrecorded  a height with no lineage recorded - true as far as we can tell, and we cannot say why

WHAT IS STILL WRONG AND IS NOT FIXED HERE. b154 Tiger Sky Tower is massed at 110.0 m against a units-register figure
of 390.4 m. It is the most conspicuous building in the district and 110 m looks like an OSM height captured part-built.
The CityEngine session has it in data/ce/<slug>/height_conflicts.json and has put the decision to Kendall rather than
picking a threshold. Until it is settled this script marks it, and any building whose register height exceeds its
massed height by more than 40 m, as "height_disputed" so stage 3 can hold those clips back rather than publish a
tower at a third of its height.
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MIN_H = 60.0
DISPUTE_M = 40.0


def load(slug):
    ce = os.path.join(ROOT, "data", "ce", slug)
    feats = json.load(open(os.path.join(ce, "buildings.geojson"), encoding="utf-8"))["features"]
    built = {}
    for r in json.load(open(os.path.join(ce, "report_v4.json"), encoding="utf-8"))["rows"]:
        nm = str(r.get("shape") or "")
        if nm.startswith("b") and "_" in nm:
            built[int(nm[1:nm.index("_")])] = r.get("height_m")
    reg = {}
    p = os.path.join(ce, "heights_register.json")
    if os.path.exists(p):
        reg = {int(k): v for k, v in json.load(open(p, encoding="utf-8"))["heights"].items()}
    return feats, built, reg


def prior_names(slug):
    """Names the web twin holds, which the CityEngine geojson sometimes lacks. Union, never overwrite."""
    p = os.path.join(ROOT, "data", "board", "unreal_targets_%s.json" % slug)
    if not os.path.exists(p):
        return {}
    try:
        return {t["i"]: t.get("name") for t in json.load(open(p, encoding="utf-8"))["towers"] if t.get("name")}
    except Exception:
        return {}


def usable_name(n):
    """A name a viewer could read on a clip. Rejects Arabic-script and degenerate labels.

    The CityEngine geojson carries OSM's name, which for Business Bay is Arabic on some buildings ("ذا سيتاديل" for
    Citadel Tower) and a bare fragment on others - b535 is "One" where the twin says Peninsula One, b620 is "2" where
    the twin says Canal Heights 2. The same trap the DLD register sets with project_name. So the twin's name wins
    where we have one and this only decides whether a fallback is worth taking.
    """
    n = (n or "").strip()
    if len(n) < 4 or n.replace(" ", "").isdigit():
        return ""
    if sum(1 for ch in n if "؀" <= ch <= "ۿ") > len(n) / 4:
        return ""
    return n


def provenance(props):
    src = props.get("height_source")
    basis = str(props.get("height_basis") or "")
    if not src:
        return "unrecorded"
    if "%" in basis or "levels" in basis or "implausible" in basis:
        return "derived"
    return "exact"


def main(slug):
    feats, built, reg = load(slug)
    twin_names = prior_names(slug)

    towers, skipped_unnamed, skipped_short = [], 0, 0
    for i, f in enumerate(feats):
        p = f.get("properties") or {}
        h = built.get(i)
        if h is None:
            h = p.get("bHeight")
        if not h or h < MIN_H:
            skipped_short += 1
            continue
        # the twin's name is the one the product already shows a user, and it is English; OSM's is the fallback
        twin_n = usable_name(twin_names.get(i))
        osm_n = usable_name(p.get("name"))
        name = twin_n or osm_n
        if not name:
            skipped_unnamed += 1
            continue
        rec = {
            "i": i,
            "actor_prefix": "b%d_" % i,
            "name": name,
            "height_m": round(float(h), 1),
            "provenance": provenance(p),
            "height_source": p.get("height_source"),
            "height_basis": p.get("height_basis"),
            "status": p.get("status"),
            "levels": p.get("levels") or None,
        }
        # a clip captions the building by name, so two registers calling it different things is a thing to see, not
        # to average. Most are wording ("SLS DUBAI" / "SLS Dubai Hotel & Residences"); a few are two buildings.
        if twin_n and osm_n and twin_n.lower() != osm_n.lower():
            rec["name_alt"] = osm_n
        rh = reg.get(i)
        if rh and rh - h > DISPUTE_M:
            rec["height_disputed"] = {"massed_m": round(float(h), 1), "register_m": rh,
                                      "gap_m": round(rh - float(h), 1),
                                      "why": "units register is far above the massed height - an OSM height caught "
                                             "part-built looks exactly like this. Hold the clip until settled."}
        towers.append(rec)

    towers.sort(key=lambda t: -t["height_m"])
    by_prov = {}
    for t in towers:
        by_prov[t["provenance"]] = by_prov.get(t["provenance"], 0) + 1
    disputed = [t for t in towers if "height_disputed" in t]

    out = {
        "district": slug,
        "built": "build_unreal_targets.py, 23 Sep 2026",
        "rule": "named building, %g m or taller, height from the CityEngine massing the Datasmith export was "
                "generated from" % MIN_H,
        "counts": {"towers": len(towers), "by_provenance": by_prov, "height_disputed": len(disputed),
                   "skipped_no_name": skipped_unnamed, "skipped_under_%gm" % MIN_H: skipped_short},
        "note": "provenance does not decide membership - it travels with the building so a weak height can be said "
                "out loud on the clip rather than silently dropped. height_disputed means hold, not render.",
        "towers": towers,
    }
    dest = os.path.join(ROOT, "data", "board", "unreal_targets_%s.json" % slug)
    json.dump(out, open(dest, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    print("%s: %d towers >= %g m with a name" % (slug, len(towers), MIN_H))
    print("   provenance: " + ", ".join("%s %d" % (k, v) for k, v in sorted(by_prov.items())))
    print("   height disputed (hold): %d" % len(disputed))
    for t in disputed:
        print("      b%-5d %-34s massed %.1f m, register %.1f m"
              % (t["i"], t["name"][:34], t["height_disputed"]["massed_m"], t["height_disputed"]["register_m"]))
    print("   skipped: %d unnamed, %d under %g m" % (skipped_unnamed, skipped_short, MIN_H))
    print("   tallest:")
    for t in towers[:8]:
        print("      b%-5d %7.1f m  %-38s %s" % (t["i"], t["height_m"], t["name"][:38], t["provenance"]))
    print("-> " + dest)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "businessbay")
