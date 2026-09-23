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
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("Sobha Unreal manifest: %d districts, %d missing" % (len(out["districts"]), len(out["missing"])))
    for s, d in out["districts"].items():
        print("  %-22s %-28s LOD %s (towers LOD %s) %s  exported %s  shapes %5s  sobha actors %3d (found %3d)" % (
            s, d["export"], d["lod"], d["towers_lod"], d["rule"], (d["exported"] or "?")[:10], d["shape_count"], d["sobha_actors"], d["found_in_export"]))
    if out["missing"]:
        print("  missing LOD 3 export:", ", ".join(out["missing"]))
    print("-> %s" % OUT)


if __name__ == "__main__":
    main()
