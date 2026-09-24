"""Where each district is, so the map can fly to it (Kendall, 7 Sep: pick a district and the map zones in on it).

The twin already knows the districts by name and corridor; the map needs their geography. For every district we model, this
writes the bounding box of its own footprints, its centre, how many buildings it holds and how many sub-communities sit inside it.

Output data/board/districts_geo.json  {"districts": [{slug, name, bbox:[w,s,e,n], centre:[lon,lat], buildings, named, subs, plots}]}
Pushed as KV `districts_geo`.
Usage: python scripts/districts_geo.py [--no-push]
"""
import json, os, sys, time
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
from build_avail_index import env_token, push  # noqa: E402
from bind_dld_buildings import AREA_LABEL  # noqa: E402
CE = os.path.join(ROOT, "data", "ce"); NAMES = os.path.join(ROOT, "data", "names"); BOARD = os.path.join(ROOT, "data", "board")
# the twin's own grouping, so the map's rail reads the same as the twin's
CORRIDOR = {"dubaimarina": "Coast", "palmjumeirah": "Coast", "jltnorth": "Coast", "jltsouth": "Coast", "althanyahfifth": "Coast",
            "dubaimaritimecity": "Coast", "alkhairanfirst": "Downtown & Creek", "burjkhalifa": "Downtown & Creek",
            "businessbay": "Downtown & Creek", "samaaljadaf": "Downtown & Creek", "alsatwa": "Downtown & Creek", "alwasl": "Downtown & Creek",
            "palmdeira": "Downtown & Creek", "jumeirahvillagecircle": "New Dubai", "jumeirahvillagetriangle": "New Dubai",
            "motorcity": "New Dubai", "arjan": "New Dubai", "dubaisciencepark": "New Dubai", "dubaisportscity": "New Dubai",
            "dubaiproductioncity": "New Dubai", "dubaistudiocity": "New Dubai", "siliconoasis": "New Dubai", "majan": "New Dubai",
            "sobhaheartland": "Meydan & MBR", "bukadra": "Meydan & MBR", "rasalkhor": "Meydan & MBR", "meydanone": "Meydan & MBR", "wadialsafa4": "Meydan & MBR", "wadialsafa5": "Meydan & MBR",
            "dubaihills": "Meydan & MBR", "damachills": "South & Outer", "madinathind4": "South & Outer", "madinatalmataar": "South & Outer",
            "jabalalifirst": "South & Outer", "jabalaliindustrialsecond": "South & Outer", "dubaiindustrialcity": "South & Outer",
            "dubaiinvestmentparkfirst": "South & Outer", "dubaiinvestmentparksecond": "South & Outer", "alyelayiss1": "South & Outer",
            "alyelayiss2": "South & Outer", "alyufrah1": "South & Outer", "alhebiahfifth": "South & Outer"}
NICE = {"bukadra": "Sobha Hartland II / Bukadra", "rasalkhor": "Sobha One / Ras Al Khor", "althanyahfifth": "JLT / Al Thanyah 5", "alkhairanfirst": "Dubai Creek Harbour", "alyelayiss2": "Town Square",
        "madinathind4": "DAMAC Hills 2", "madinatalmataar": "Dubai South", "jabalalifirst": "Jebel Ali", "alyufrah1": "The Valley",
        "jabalaliindustrialsecond": "Jebel Ali Industrial 2", "dubaiinvestmentparkfirst": "Dubai Investments Park",
        "dubaiinvestmentparksecond": "Dubai Investments Park 2", "siliconoasis": "Dubai Silicon Oasis", "alhebiahfifth": "Al Hebiah 5"}


def main():
    do_push = "--push" in sys.argv and "--no-push" not in sys.argv
    out = []
    plots = {}
    pj = os.path.join(BOARD, "plots.json")
    if os.path.exists(pj):
        for f in json.load(open(pj, encoding="utf-8")).get("features", []):
            plots[f["properties"]["district"]] = plots.get(f["properties"]["district"], 0) + 1
    for slug in sorted(os.listdir(CE)):
        gj = os.path.join(CE, slug, "buildings.geojson")
        if not os.path.exists(gj): continue
        xs, ys = [], []
        def walk(c):
            if isinstance(c[0], (int, float)): xs.append(c[0]); ys.append(c[1])
            else:
                for k in c: walk(k)
        F = json.load(open(gj, encoding="utf-8"))["features"]
        for f in F: walk(f["geometry"]["coordinates"])
        if not xs: continue
        try:                                                                          # sub-community points widen the box where footprints stop short
            for c in (json.load(open(os.path.join(NAMES, f"clusters_{slug}.json"), encoding="utf-8")).get("clusters") or []):
                if c.get("lon") and c.get("lat"): xs.append(c["lon"]); ys.append(c["lat"])
        except Exception: pass
        A = json.load(open(os.path.join(NAMES, f"anchors_{slug}.json"), encoding="utf-8")).get("anchors", []) if os.path.exists(os.path.join(NAMES, f"anchors_{slug}.json")) else []
        cl = json.load(open(os.path.join(NAMES, f"clusters_{slug}.json"), encoding="utf-8")) if os.path.exists(os.path.join(NAMES, f"clusters_{slug}.json")) else {}
        out.append({"slug": slug, "name": NICE.get(slug) or AREA_LABEL.get(slug) or slug.replace("_", " ").title(),
                    "corridor": CORRIDOR.get(slug, "Other"),
                    "bbox": [round(min(xs), 5), round(min(ys), 5), round(max(xs), 5), round(max(ys), 5)],
                    "centre": [round((min(xs) + max(xs)) / 2, 5), round((min(ys) + max(ys)) / 2, 5)],
                    "buildings": len(F), "named": sum(1 for a in A if a.get("name")),
                    "subs": len(cl.get("clusters") or []), "plots": plots.get(slug, 0)})
    order = ["Coast", "Downtown & Creek", "New Dubai", "Meydan & MBR", "South & Outer", "Other"]
    out.sort(key=lambda d: (order.index(d["corridor"]) if d["corridor"] in order else 9, -d["buildings"]))
    doc = {"generated": time.strftime("%Y-%m-%d %H:%M"), "districts": out}
    json.dump(doc, open(os.path.join(BOARD, "districts_geo.json"), "w", encoding="utf-8"), ensure_ascii=False)
    print(f"districts: {len(out)}")
    for d in out[:6]: print(f"  {d['name'][:26]:<26} {d['corridor']:<17} buildings {d['buildings']:>5} named {d['named']:>5} subs {d['subs']:>4} plots {d['plots']:>4}")
    if do_push: print("districts_geo ->", push("districts_geo", doc, env_token("INGEST_TOKEN")).get("ok"))


if __name__ == "__main__":
    main()
