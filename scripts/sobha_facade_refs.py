"""Every Sobha building at LOD 3 with the look of its own renderings: facade_refs.json for each Sobha district.

Kendall, 24 Sep 2026: "some of these buildings have texture, others don't ... every single building is a minimum of
LOD 300 ... look at the Sobha website for renderings ... this is being presented to the client."

The audit behind it: of the 218 Sobha actors in the Unreal manifest, 186 carried facade_v2's DEFAULT class (a plaster
'render' guess), 13 had none at all (the Hartland II permit boxes), and only 19 had a look from a real source. The
mechanism to fix that already exists - data/ce/<slug>/facade_refs.json -> facade_match.py -> facade_match.json ->
ce_lod3_datasmith.py --attr-file sets the rule's knobs per shape - it had only ever been written for DAMAC Hills.

This writes the Sobha refs for all eleven districts from the renderings in data/kits/sobha/site (read on 24 Sep):
  hartland_glass     Creek Vistas Heights / Grande, The Crest, Waves, Greens, One Park Avenue: blue-grey glass
                     curtain wall, fine vertical fins, a continuous white balcony band every floor, white podium
  hartland2_glass    Riverside Crescent 310-360, Skyscape, Skyvue: the Hartland II family - blue glass, continuous
                     white balcony slabs wrapping every floor, rounded corners, gold crown band
  sobha_one_frame    Sobha One, The Element: pale concrete frame grid, bronze vertical fins, clear glass, no balconies
  central_fins       Sobha Central I / II: clear glass, dense vertical fins, bronze slab bands, tiered, retail podium
  seahaven_wave      SeaHaven A / B & C: deep blue glass, sweeping continuous balconies, no fins
  motorcity_bronze   Orbis, Solis: bronze-tinted glass and warm render, continuous balconies
  verde_glass        Verde by Sobha: clear glass tower with light fins and balconies
  skyparks_glass     Sobha SkyParks: clear glass with fins, balconies above the podium
  legacy_render      Ivory I / II, Sapphire, Daffodil, The Serene: 2010-era render with punched windows and balconies

Footprints are listed explicitly from data/board/sobha_mask.json (the register's own attribution), so the resolver never
has to guess by name - bukadra and rasalkhor are not in the graph's building table at all. Existing refs in a district
(none today for these eleven) are merged, not replaced.
Usage: python scripts/sobha_facade_refs.py   then facade_match.py per district (this runs it), then the subset exports.
"""
import json, os, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CE = os.path.join(ROOT, "data", "ce")
MASK = os.path.join(ROOT, "data", "board", "sobha_mask.json")

LOOKS = {
    "hartland_glass": {"note": "Sobha Hartland towers: blue-grey glass, fine fins, continuous white balcony band each floor, white podium",
                       "cga": {"fclass": "glassblue", "balconyMinH": 0, "balconyContinuous": 1, "balconyD": 1.4, "finProj": 0.12, "finW": 0.08, "paneW": 1.5, "podiumLevels": 3},
                       "unreal": {"walls": "white", "slabs": "white", "vision": "blue_glass"}},
    "hartland2_glass": {"note": "Hartland II family (Riverside Crescent, Skyscape, Skyvue): blue glass, wrapping white balcony slabs, rounded corners, gold crown",
                        "cga": {"fclass": "glassblue", "balconyMinH": 0, "balconyContinuous": 1, "balconyD": 1.6, "finProj": 0.0, "paneW": 1.5, "crownPct": 0.03, "podiumLevels": 3},
                        "unreal": {"walls": "white", "slabs": "white", "vision": "blue_glass", "crown": "gold"}},
    "sobha_one_frame": {"note": "Sobha One: pale concrete frame grid, bronze vertical fins, clear glass, no balconies",
                        "cga": {"fclass": "concrete", "balconyMinH": 999, "finProj": 0.25, "finW": 0.14, "paneW": 2.0, "recess": 0.35, "podiumLevels": 2},
                        "unreal": {"walls": "pale_concrete", "slabs": "pale_concrete", "vision": "clear_glass", "fins": "bronze"}},
    "central_fins": {"note": "Sobha Central: clear glass, dense vertical fins, bronze slab bands, tiered, retail podium",
                     "cga": {"fclass": "glassclear", "balconyMinH": 999, "finProj": 0.22, "finW": 0.10, "paneW": 1.2, "bandProj": 0.25, "podiumLevels": 4, "podiumFloorH": 5.0},
                     "unreal": {"walls": "dark_bronze", "slabs": "dark_bronze", "vision": "clear_glass"}},
    "seahaven_wave": {"note": "SeaHaven: deep blue glass, sweeping continuous balconies, no fins",
                      "cga": {"fclass": "glassblue", "balconyMinH": 0, "balconyContinuous": 1, "balconyD": 1.8, "finProj": 0.0, "paneW": 1.8},
                      "unreal": {"walls": "white", "slabs": "white", "vision": "deep_blue_glass"}},
    "motorcity_bronze": {"note": "Orbis / Solis: bronze-tinted glass and warm render, continuous balconies",
                         "cga": {"fclass": "glassbronze", "balconyMinH": 0, "balconyContinuous": 1, "balconyD": 1.5, "finProj": 0.06, "paneW": 1.5},
                         "unreal": {"walls": "warm_render", "slabs": "bronze", "vision": "bronze_glass"}},
    "verde_glass": {"note": "Verde by Sobha: clear glass tower, light fins, balconies",
                    "cga": {"fclass": "glassclear", "balconyMinH": 0, "balconyContinuous": 0, "balconyD": 1.4, "finProj": 0.10, "paneW": 1.5},
                    "unreal": {"walls": "white", "slabs": "white", "vision": "clear_glass"}},
    "skyparks_glass": {"note": "Sobha SkyParks: clear glass with fins, balconies above a retail podium",
                       "cga": {"fclass": "glassclear", "balconyMinH": 20, "balconyContinuous": 1, "balconyD": 1.4, "finProj": 0.15, "paneW": 1.4, "podiumLevels": 3},
                       "unreal": {"walls": "white", "slabs": "white", "vision": "clear_glass"}},
    "legacy_render": {"note": "2010-era Sobha (Ivory, Sapphire, Daffodil) and small schemes: render with punched windows and balconies",
                      "cga": {"fclass": "render", "balconyMinH": 0, "balconyContinuous": 0, "balconyD": 1.2, "finProj": 0.0},
                      "unreal": {"walls": "cream_render", "slabs": "cream_render", "vision": "tinted_glass"}},
}
LOOK_OF = [
    ("Riverside Crescent", "hartland2_glass"), ("SKYSCAPE", "hartland2_glass"), ("Skyvue", "hartland2_glass"),
    ("SOBHA ONE", "sobha_one_frame"), ("Element at Sobha One", "sobha_one_frame"),
    ("Sobha Central", "central_fins"),
    ("Seahaven", "seahaven_wave"),
    ("Orbis", "motorcity_bronze"), ("Solis", "motorcity_bronze"),
    ("Verde", "verde_glass"),
    ("SkyParks", "skyparks_glass"),
    ("IVORY", "legacy_render"), ("SAPPHIRE", "legacy_render"), ("DAFFODIL", "legacy_render"), ("SERENE", "legacy_render"),
    ("Hartland", "hartland_glass"), ("Creek Vista", "hartland_glass"), ("Crest", "hartland_glass"), ("Waves", "hartland_glass"), ("Greens", "hartland_glass"),
]


def look_for(name):
    n = (name or "").lower()
    for key, look in LOOK_OF:
        if key.lower() in n:
            return look
    return "legacy_render"


def main():
    mask = json.load(open(MASK, encoding="utf-8"))
    for slug, d in mask["districts"].items():
        if not d.get("n"):
            continue
        path = os.path.join(CE, slug, "facade_refs.json")
        refs = json.load(open(path, encoding="utf-8")) if os.path.exists(path) else {"looks": {}, "buildings": {}}
        refs["looks"].update(LOOKS)
        by_name = {}
        for i_s, rec in d["by_i"].items():
            nm = rec.get("name") or ("sobha_%s" % i_s)
            by_name.setdefault(nm, []).append(int(i_s))
        placeholders = {int(i_s) for i_s, rec in d["by_i"].items() if rec.get("register_placeholder")}
        for nm, fps in by_name.items():
            entry = {"look": look_for(nm), "footprints": sorted(fps), "source": "sobha_mask + sobharealty.com renderings, 24 Sep 2026"}
            # client cut (Kendall, 24 Sep, "some are still different colours"): EVERY Sobha building is shown finished - the
            # rule's construction-teal and pipeline-gold ghosts are the twin's status coding, not a facade. The exports that
            # carry this are the <slug>_sobha_client_lod3 variants; the canonical exports and the twin keep the register status.
            entry["cga"] = {"status": "existing"}
            if all(f in placeholders for f in fps):
                entry["note"] = "register placeholder rendered as built for the client cut"
            refs["buildings"][nm] = entry
        refs["note"] = refs.get("note") or "Sobha looks from the developer's renderings (scripts/sobha_facade_refs.py); other developers' entries untouched"
        json.dump(refs, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        r = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "facade_match.py"), slug], capture_output=True, text=True, encoding="utf-8", errors="replace")
        m = json.load(open(os.path.join(CE, slug, "facade_match.json"), encoding="utf-8")) if os.path.exists(os.path.join(CE, slug, "facade_match.json")) else {}
        print("%-22s %2d projects -> %3d footprints matched %s" % (slug, len(by_name), len(m), "" if r.returncode == 0 else "(facade_match rc=%d %s)" % (r.returncode, (r.stderr or "")[-160:])))


if __name__ == "__main__":
    main()
