"""Plot identification numbers for the map (Kendall, 6 Sep: "why do i not see the plot identification numbers").

There is no public parcel geometry in Dubai, so we cannot draw parcel outlines. What we do hold is the parcel identifier for every
registered building - parcel_id = community number x 10000 + plot number - and, for every building we have bound to a footprint,
that footprint's position. So the map can carry the plot NUMBER at the building's own location even though it cannot carry the
plot BOUNDARY.

Sources: reg_bindings / tx_bindings (which footprint a register building sits on) + anchors_<slug>.json (that footprint's lon/lat)
+ units_buildings_<slug>.json (parcel, community, plot, master project, units).
Output data/board/plots.json  GeoJSON FeatureCollection, properties: plot ("392-192"), community, no, name, units, district, parcel.
Pushed as KV `plots`; the map draws it above zoom 14.5 as a label layer.
Usage: python scripts/plot_points.py [--no-push]
"""
import json, os, sys, glob, time, collections
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
from build_avail_index import env_token, push  # noqa: E402
NAMES = os.path.join(ROOT, "data", "names"); DLD = os.path.join(ROOT, "data", "dld"); BOARD = os.path.join(ROOT, "data", "board")
IDENT = os.path.join(ROOT, "data", "identity", "official", "dld")


def load(p, d=None):
    try: return json.load(open(p, encoding="utf-8"))
    except Exception: return d


def plot_label(parcel, community, no):
    if community and no: return f"{community}-{no}"
    try:
        v = int(float(parcel)); return f"{v // 10000}-{v % 10000}"
    except Exception:
        return None


def main():
    do_push = "--no-push" not in sys.argv
    reg = load(os.path.join(IDENT, "reg_bindings.json"), {}) or {}
    tx = load(os.path.join(IDENT, "tx_bindings.json"), {}) or {}
    feats = []; seen = set(); per = collections.Counter()
    for slug in sorted({k for k in list(reg) + list(tx) if not k.startswith("_")}):
        A = load(os.path.join(NAMES, f"anchors_{slug}.json"), {}) or {}
        pos = {a["i"]: (a.get("lon"), a.get("lat")) for a in A.get("anchors", []) if a.get("lon") is not None}
        ub = {str(b.get("property_id")): b for b in (load(os.path.join(DLD, f"units_buildings_{slug}.json"), {}) or {}).get("buildings", [])}
        rows = dict(tx.get(slug) or {}); rows.update(reg.get(slug) or {})       # the register binding wins where both exist
        for i_s, v in rows.items():
            i = int(i_s)
            lonlat = pos.get(i)
            if not lonlat or lonlat[0] is None: continue
            b = ub.get(str(v.get("property_id"))) or {}
            parcel = v.get("parcel") or b.get("parcel") or b.get("plot_parcel")
            lab = plot_label(parcel, b.get("community"), b.get("plot_no"))
            if not lab: continue
            key = (slug, i)
            if key in seen: continue
            seen.add(key); per[slug] += 1
            feats.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [round(lonlat[0], 6), round(lonlat[1], 6)]},
                          "properties": {"plot": lab, "name": v.get("name") or v.get("building"), "units": b.get("units"),
                                         "master": b.get("master"), "district": slug, "parcel": str(parcel) if parcel else None,
                                         "area_sqm": b.get("plot_area_sqm")}})
    doc = {"type": "FeatureCollection", "generated": time.strftime("%Y-%m-%d %H:%M"),
           "note": "Plot number = community number and plot number from the Dubai Land Department parcel id, placed at the building's own footprint. No parcel outlines exist publicly, so this is the number without the boundary.",
           "features": feats}
    json.dump(doc, open(os.path.join(BOARD, "plots.json"), "w", encoding="utf-8"), ensure_ascii=False)
    print(f"plot points: {len(feats):,} across {len(per)} districts | {os.path.getsize(os.path.join(BOARD, 'plots.json'))//1024} KB")
    for s, n in per.most_common(8): print(f"  {s:<26}{n:>6}")
    if do_push: print("plots ->", push("plots", doc, env_token("INGEST_TOKEN")).get("ok"))


if __name__ == "__main__":
    main()
