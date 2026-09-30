"""LAB (landmarks, research only): the landmark override table - which named building gets which facade family.

One row per landmark, keyed "<slug>:<footprint index>" (the index into data/ce/<slug>/buildings.geojson that every
builder uses as the shape id b<i>). A row is:
  family     the facade family (rules/lab/landmarks/lm_<family>.cga + gen_Facade_<family>.cga)
  cga        the per-shape rule attrs, in the same form as facade_match.json's "cga" block, so ce_lod3_datasmith.py
             --attr-file and pyprt_district.prepare can push them unchanged. Footprint-bound numbers (lmAz*, lmLen*)
             are MEASURED here from the footprint by the family's binder, never typed in.
  facts      the published numbers the family's defaults encode, each with its source
  twin       what the twin carries today for the same building (height, levels) and where it disagrees
  checks     binder diagnostics (e.g. how rectangular the footprint is), so a bad binding is visible

Adding a landmark that fits an existing family = one entry in LANDMARKS below (name, key, family, facts) and a
re-run. The binder does the geometry. A new family = one binder function here + one mass + one gen_ file.

  python scripts/lab_landmarks_table.py            -> data/lab/landmarks/landmark_table.json
"""
import json
import math
import os
import sys
import time

import numpy as np
from pyproj import Transformer
from shapely.geometry import Polygon

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
CEDIR = os.path.join(ROOT, "data", "ce")
OUT = os.path.join(ROOT, "data", "lab", "landmarks")
TF = Transformer.from_crs("EPSG:4326", "EPSG:32640", always_xy=True)

WIKI_BK = "https://en.wikipedia.org/wiki/Burj_Khalifa"
SOM_BK = "https://www.som.com/projects/burj-khalifa/"
WIKI_CAYAN = "https://en.wikipedia.org/wiki/Cayan_Tower"
SOM_CAYAN = "https://www.som.com/projects/cayan-tower/"
CTBUH_OPUS = "https://www.skyscrapercenter.com/building/the-opus/18366"
ZHA_OPUS = "https://www.zha.com/architecture/opus/"

LANDMARKS = [
    {"key": "burjkhalifa:67", "name": "Burj Khalifa", "family": "spiral_setback",
     "cga": {"lmFloors": 154},
     "facts": [
         {"fact": "architectural height", "value": "828 m", "source": WIKI_BK},
         {"fact": "top floor", "value": "585.4 m (ssTopFrac 0.707)", "source": WIKI_BK},
         {"fact": "floors", "value": "154 + 9 maintenance levels (lmFloors 154, ssCrownFloors 9); SOM says 160 stories", "source": WIKI_BK + " ; " + SOM_BK},
         {"fact": "spire", "value": "242.5 m", "source": WIKI_BK},
         {"fact": "setbacks", "value": "27, in an upward spiral (ssSetbacks 27)", "source": WIKI_BK + " ; " + SOM_BK},
         {"fact": "plan", "value": "Y-shaped, three wings around a hexagonal hub; core emerges as the spire", "source": SOM_BK},
         {"fact": "cladding", "value": "reflective glass, aluminium and textured stainless steel spandrels, vertical tubular fins; panels ~4.5 x 10.7 ft (ssPanelW 1.37 m)", "source": WIKI_BK},
         {"fact": "mechanical floors", "value": "seven double-storey, ~every 30 storeys, darker bands outside; levels 17-18, 40-42, 73-75, 109-110, 136-138 from secondary floor guides", "source": "https://www.burjkhalifa.ae/the-tower/structures/ (search snippet; page 403 to fetch)"}],
     "unreal": {"vision": "reflective_silver_blue_glass", "spandrel": "textured_stainless", "fins": "polished_stainless", "spire": "stainless"}},
    {"key": "dubaimarina:55", "name": "Cayan Tower", "family": "twist",
     "cga": {"lmFloors": 75},
     "facts": [
         {"fact": "height", "value": "306.4 m", "source": WIKI_CAYAN},
         {"fact": "twist", "value": "90 deg total, 1.2 deg per floor about a cylindrical core (twDeg 1.2)", "source": WIKI_CAYAN + " ; " + SOM_CAYAN},
         {"fact": "storeys", "value": "75 (SOM; 75 x 1.2 = 90 deg) - Wikipedia and the twin say 73", "source": SOM_CAYAN},
         {"fact": "facade", "value": "prefabricated (titanium-coloured) metal panels on cast-in-place perimeter columns, repeating staggered screen panels, deep window sills", "source": SOM_CAYAN + " ; " + WIKI_CAYAN}],
     "unreal": {"columns": "titanium_metal_panel", "screens": "perforated_metal", "vision": "dark_glass"}},
    {"key": "businessbay:158", "name": "The Opus", "family": "void_cube",
     "cga": {"lmFloors": 21},
     "facts": [
         {"fact": "height", "value": "93 m architectural, 21 floors above ground", "source": CTBUH_OPUS},
         {"fact": "form", "value": "a cube of two towers with a free-form void carved from its centre", "source": ZHA_OPUS},
         {"fact": "void", "value": "eight storeys; 6,000 m2 facade of 4,300 flat / single- / double-curved glass units", "source": ZHA_OPUS},
         {"fact": "atrium", "value": "four storeys at ground level, links the halves (vcAtrium 4)", "source": ZHA_OPUS},
         {"fact": "bridge", "value": "38 m wide, three storeys, 71 m above ground (vcBridgeW 38, vcBridgeAt 16 = 71 / (93 / 21))", "source": ZHA_OPUS},
         {"fact": "glazing", "value": "double-glazed, dotted frit pattern; LEDs in each panel at night", "source": ZHA_OPUS}],
     "unreal": {"vision": "dark_glass_silver_frit", "void": "mirror_glass"}},
]


def footprint_en(slug, i):
    f = json.load(open(os.path.join(CEDIR, slug, "buildings.geojson"), encoding="utf-8"))["features"][i]
    g = f["geometry"]
    ring = g["coordinates"][0] if g["type"] == "Polygon" else g["coordinates"][0][0]
    return np.array([TF.transform(c[0], c[1]) for c in ring]), f["properties"]


def ce_az(de, dn):
    """Map direction (east, north) -> the CGA rotateScope(0, a, 0) angle that turns scope +x onto it.
    CE frame: x = east, z = -north; a right-handed turn about +y by a takes +x to (cos a, 0, -sin a) = east cos a,
    north sin a. So a is the ordinary map angle, counter-clockwise from east. (Checked on the built GLB by
    lab_landmarks_build.py: the tier-1 cut must land on wing 0.)"""
    return round(math.degrees(math.atan2(dn, de)), 2)


def bind_spiral_setback(P):
    """Three wing tips = the farthest vertices from the centroid, at least 60 deg apart. Wing w is trimmed back to
    just past the farthest OTHER geometry along its axis (the hub and the lobes between wings), so the last setback
    leaves the hub whole."""
    poly = Polygon(P); c = np.array(poly.centroid.coords[0]); d = P[:-1] - c
    ang = np.degrees(np.arctan2(d[:, 1], d[:, 0])); r = np.hypot(d[:, 0], d[:, 1])
    tips = []
    for k in np.argsort(-r):
        if all(abs((ang[k] - ang[t] + 180) % 360 - 180) > 60 for t in tips):
            tips.append(k)
        if len(tips) == 3:
            break
    tips.sort(key=lambda k: ang[k])                           # spiral order: counter-clockwise from the first wing
    cga, chk = {}, {"centroid_en": [round(c[0], 1), round(c[1], 1)], "wings": []}
    for w, k in enumerate(tips):
        u = d[k] / r[k]
        proj = d @ u
        near = np.abs((ang - ang[k] + 180) % 360 - 180) < 30     # vertices belonging to this wing
        hub = float(proj[~near].max())                          # farthest other geometry along the wing axis
        tip = float(proj.max())
        cut = max(0.0, tip - hub - 1.0)
        cga["lmAz%d" % w] = ce_az(u[0], u[1])
        cga["lmLen%d" % w] = round(cut, 1)
        chk["wings"].append({"tip_m": round(tip, 1), "hub_m": round(hub, 1), "trim_m": round(cut, 1),
                             "map_deg": round(float(ang[k]), 1)})
    return cga, chk


def rect_check(P):
    poly = Polygon(P); mrr = poly.minimum_rotated_rectangle
    q = np.array(mrr.exterior.coords)
    sides = [float(np.hypot(*(q[k + 1] - q[k]))) for k in range(4)]
    k = int(np.argmax(sides[:2]))
    long_vec = q[k + 1] - q[k]
    return {"fill": round(poly.area / mrr.area, 3), "long_m": round(max(sides), 1), "short_m": round(min(sides), 1)}, long_vec


def bind_twist(P):
    chk, _ = rect_check(P)
    return {}, chk


def bind_void_cube(P):
    chk, v = rect_check(P)
    return {"lmAz0": ce_az(v[0], v[1])}, chk


BINDERS = {"spiral_setback": bind_spiral_setback, "twist": bind_twist, "void_cube": bind_void_cube}
FAMILIES = {
    "spiral_setback": {"reference": "Burj Khalifa", "binds": "lmAz0..2 wing directions, lmLen0..2 wing trim lengths",
                       "fits": "Y / tripartite plans stepping back wing by wing (e.g. other Y towers); swap facts via family attrs"},
    "twist": {"reference": "Cayan Tower", "binds": "nothing - rotates about the footprint's own centre",
              "fits": "any tower of identical rotated floor plates: set lmFloors and twDeg"},
    "void_cube": {"reference": "The Opus", "binds": "lmAz0 long axis",
                  "fits": "a block with a carved through-void: atrium / bridge / void storeys are family attrs"},
}


def main():
    os.makedirs(OUT, exist_ok=True)
    rows = {}
    for L in LANDMARKS:
        slug, i = L["key"].split(":"); i = int(i)
        P, props = footprint_en(slug, i)
        bound, chk = BINDERS[L["family"]](P)
        anchors = json.load(open(os.path.join(ROOT, "data", "names", "anchors_%s.json" % slug), encoding="utf-8"))["anchors"]
        a = next((x for x in anchors if x.get("i") == i), {})
        rows[L["key"]] = {
            "name": L["name"], "family": L["family"],
            "cga": {"landmark": L["family"], "lmLOD": 2, **L["cga"], **bound},
            "facts": L["facts"], "unreal": L["unreal"],
            "twin": {"bHeight": props.get("bHeight"), "levels": props.get("levels"), "anchor_name": a.get("name"),
                     "identity_grade": a.get("identity_grade"), "footprint_vertices": len(P) - 1,
                     "footprint_m2": round(Polygon(P).area, 1)},
            "checks": chk}
    doc = {"schema": "landmark override table v1 - LAB, research only",
           "key": "<slug>:<footprint index into data/ce/<slug>/buildings.geojson> (= shape b<i>)",
           "apply": "row['cga'] is pushed per shape exactly like facade_match.json's cga block; the rule is "
                    "najma_v4.cga + INTEGRATION.patch (landmark != '' at LOD 3 -> rules/lab/landmarks/landmarks.cga)",
           "families": FAMILIES, "landmarks": rows,
           "built": time.strftime("%Y-%m-%dT%H:%M:%S"), "builder": "scripts/lab_landmarks_table.py"}
    p = os.path.join(OUT, "landmark_table.json")
    json.dump(doc, open(p, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    # the CE lane takes ONE --attr-file per run (ce_lod3_datasmith.py): write the district's facade_match.json with the
    # landmark rows laid over it (landmark wins), in facade_match's own format, as a NEW file beside the table
    for slug in sorted({k.split(":")[0] for k in rows}):
        fm_p = os.path.join(CEDIR, slug, "facade_match.json")
        fm = json.load(open(fm_p, encoding="utf-8")) if os.path.exists(fm_p) else {}
        for k, r in rows.items():
            if k.split(":")[0] == slug:
                i = k.split(":")[1]
                fm[i] = {"name": r["name"], "look": "landmark:" + r["family"],
                         "cga": {**fm.get(i, {}).get("cga", {}), **r["cga"]}, "unreal": r["unreal"]}
        json.dump(fm, open(os.path.join(OUT, "attrs_%s.json" % slug), "w", encoding="utf-8"), indent=1, ensure_ascii=False)
        print("attr file for the CE lane: data/lab/landmarks/attrs_%s.json (%d entries)" % (slug, len(fm)))
    for k, r in rows.items():
        print("%-18s %-14s %s" % (k, r["name"], json.dumps(r["cga"])))
        print("%18s %s" % ("", json.dumps(r["checks"])))
    print("-> %s" % os.path.relpath(p, ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
