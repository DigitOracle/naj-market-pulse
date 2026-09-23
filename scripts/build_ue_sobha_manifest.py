"""The Unreal manifest for the Sobha view: which Datasmith LOD 3 exports to import, and which actors in them are Sobha's.

Kendall, 23 Sep 2026: "i want this in unreal and ensure cityengine LOD 300". The CityEngine film lane
(ce_lod3_datasmith.py, rules/najma_v4.cga, LOD 3) has already exported every district Sobha builds in to
data/ce/_datasmith/<slug>_lod3.udatasmith, all on ONE global offset (-328289, 0, 2784598 in the CE frame) so
they land in the same Unreal world. The Datasmith actors carry the footprint index in their name
("b<i>_<class>_s<status>_Root"), and data/board/sobha_mask.json says which footprint indices are Sobha's
and how sure each one is. This joins the two, so the Unreal side never has to know about parcels.

Output data/ce/_datasmith/sobha_unreal.json
  {"generated", "offset_ce_xyz", "districts": {slug: {"udatasmith", "assets", "exported", "lod", "rule",
   "shape_count", "actors": {"b<i>_": {"name", "project_number", "method", "soft", "actor"}}}},
   "missing": [slug...]  - districts in the mask with no LOD 3 export yet (re-run after ce_lod3_datasmith.py)}
Then in the Unreal Editor: scripts/ue_sobha_lens.py (Editor Python).
Usage: python scripts/build_ue_sobha_manifest.py
"""
import json, os, re, datetime as dt

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DS = os.path.join(ROOT, "data", "ce", "_datasmith")
MASK = os.path.join(ROOT, "data", "board", "sobha_mask.json")
OUT = os.path.join(DS, "sobha_unreal.json")
OFFSET = [-328289, 0, 2784598]


def main():
    mask = json.load(open(MASK, encoding="utf-8"))
    out = {"generated": dt.datetime.now().isoformat(timespec="seconds"), "developer": "sobha",
           "offset_ce_xyz": OFFSET, "offset_note": "CE frame x=easting, y=up, z=-northing (m); every district export ADDS this offset, so they share one Unreal origin",
           "rule": "rules/najma_v4.cga", "lod": 3, "districts": {}, "missing": []}
    for slug, d in sorted(mask["districts"].items()):
        if not d.get("n"):
            continue
        # a Sobha-only export at FULL LOD 3 (towers included; the district exports drop towers >= 60 m to LOD 2 for
        # cost) wins over the district export when it exists: <slug>_sobha_lod3, from ce_lod3_datasmith.py --subset --tower-lod 3
        name = "%s_sobha_lod3" % slug if os.path.exists(os.path.join(DS, "%s_sobha_lod3.udatasmith" % slug)) else "%s_lod3" % slug
        uds = os.path.join(DS, "%s.udatasmith" % name)
        stats_p = os.path.join(DS, "%s_stats.json" % name)
        georef_p = os.path.join(DS, "%s_georef.json" % name)
        if not os.path.exists(uds):
            out["missing"].append(slug); continue
        stats = json.load(open(stats_p, encoding="utf-8")) if os.path.exists(stats_p) else {}
        georef = json.load(open(georef_p, encoding="utf-8")) if os.path.exists(georef_p) else {}
        # actor names as the .udatasmith carries them, so the Unreal script matches exactly, not by prefix guess
        names = {}
        for m in re.finditer(r'<Actor name="(b(\d+)_[^"]*)"', open(uds, encoding="utf-8", errors="ignore").read()):
            names.setdefault(m.group(2), m.group(1))
        actors = {}
        for i, rec in d["by_i"].items():
            actors["b%s_" % i] = {"i": int(i), "name": rec.get("name"), "project_number": rec.get("project_number"),
                                  "method": rec.get("method"), "soft": rec.get("method") in ("radius", "geocode") or bool(rec.get("register_placeholder")),
                                  "register_placeholder": bool(rec.get("register_placeholder")), "actor": names.get(str(i))}
        off = georef.get("offset_ce_xyz")
        if off and [round(x) for x in off] != OFFSET:
            print("  !! %s exported on a different offset %s - it will not sit with the others" % (slug, off))
        out["districts"][slug] = {"udatasmith": uds, "assets": os.path.join(DS, "%s_Assets" % name), "export": name,
                                  "towers_lod": 3 if name.endswith("_sobha_lod3") else 2,
                                  "exported": stats.get("generated"), "lod": stats.get("lod"), "rule": stats.get("rule"),
                                  "shape_count": stats.get("shape_count"), "offset_ce_xyz": off,
                                  "sobha_actors": len(actors), "found_in_export": sum(1 for a in actors.values() if a["actor"]),
                                  "actors": actors}
    # District geojsons overlap at their edges, so one physical building can sit in two districts' files (bukadra +
    # sobhaheartland share 363 footprints; althanyahfifth + jltnorth 224). The web twin never draws it twice - one tile at a
    # time - but Unreal imports every district into ONE level. So each Sobha footprint is kept once, by centroid to six
    # decimals: the copy reached by the surer route wins (parcel > dm > radius > geocode), then the copy with a sourced
    # height; the other is marked duplicate_of and the lens hides it. Which HEIGHT is right where the two copies disagree is
    # not decided here - it is listed under "height_conflicts" for a person (23 Sep 2026: 53 such pairs estate-wide).
    RANK = {"parcel": 0, "dm": 1, "radius": 2, "geocode": 3}
    seen, out["height_conflicts"], dup_n = {}, [], 0
    CE = os.path.join(ROOT, "data", "ce")
    for slug, d in out["districts"].items():
        feats = json.load(open(os.path.join(CE, slug, "buildings.geojson"), encoding="utf-8"))["features"]
        for pre, a in d["actors"].items():
            f = feats[a["i"]]; ring = f["geometry"]["coordinates"][0] if f["geometry"]["type"] == "Polygon" else f["geometry"]["coordinates"][0][0]
            c = (round(sum(p[0] for p in ring) / len(ring), 6), round(sum(p[1] for p in ring) / len(ring), 6))
            a["centroid"] = list(c); a["height_m"] = f["properties"].get("bHeight"); a["height_source"] = f["properties"].get("height_source")
            key = (RANK.get(a["method"], 9), 0 if a["height_source"] else 1)
            if c in seen:
                o_slug, o_pre, o_key = seen[c]; other = out["districts"][o_slug]["actors"][o_pre]
                keep, drop = ((slug, pre, a), (o_slug, o_pre, other)) if key < o_key else ((o_slug, o_pre, other), (slug, pre, a))
                drop[2]["duplicate_of"] = "%s/%s" % (keep[0], keep[1]); keep[2].pop("duplicate_of", None); seen[c] = (keep[0], keep[1], min(key, o_key)); dup_n += 1
                if (a["height_m"] or 0) != (other["height_m"] or 0):
                    out["height_conflicts"].append({"centroid": list(c), "kept": "%s/%s %.1f m (%s)" % (keep[0], keep[1], keep[2]["height_m"] or 0, keep[2]["height_source"] or "no source"),
                                                    "dropped": "%s/%s %.1f m (%s)" % (drop[0], drop[1], drop[2]["height_m"] or 0, drop[2]["height_source"] or "no source"), "name": a.get("name")})
            else:
                seen[c] = (slug, pre, key)
    out["duplicates_hidden"] = dup_n
    out["height_conflicts_note"] = ("pairs among the IMPORTED Sobha actors only. An empty list means no duplicate pair was imported, "
                                    "not that no disagreement exists: the full district files disagree on 59 shared footprints "
                                    "(digital-twin-transition session, 23 Sep 2026), which matter once district context is imported.")
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("Sobha Unreal manifest: %d districts, %d missing, %d cross-district duplicates hidden, %d height conflicts for a person" % (
        len(out["districts"]), len(out["missing"]), dup_n, len(out["height_conflicts"])))
    for hc in out["height_conflicts"]:
        print("   height conflict %s: kept %s | dropped %s" % (hc["name"], hc["kept"], hc["dropped"]))
    for s, d in out["districts"].items():
        print("  %-22s %-28s LOD %s (towers LOD %s) %s  exported %s  shapes %5s  sobha actors %3d (found %3d)" % (
            s, d["export"], d["lod"], d["towers_lod"], d["rule"], (d["exported"] or "?")[:10], d["shape_count"], d["sobha_actors"], d["found_in_export"]))
    if out["missing"]:
        print("  missing LOD 3 export:", ", ".join(out["missing"]))
    print("-> %s" % OUT)


if __name__ == "__main__":
    main()
