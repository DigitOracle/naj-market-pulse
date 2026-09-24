"""Plot identification numbers for the map (Kendall, 6 Sep: "why do i not see the plot identification numbers").

There is no public parcel geometry in Dubai, so we cannot draw parcel outlines. What we do hold is the parcel identifier for every
registered building - parcel_id = community number x 10000 + plot number - and, for every building we have bound to a footprint,
that footprint's position. So the map can carry the plot NUMBER at the building's own location even though it cannot carry the
plot BOUNDARY.

Sources: reg_bindings / tx_bindings (which footprint a register building sits on) + anchors_<slug>.json (that footprint's lon/lat)
+ units_buildings_<slug>.json (parcel, community, plot, master project, units).
Output data/board/plots.json  GeoJSON FeatureCollection, properties: plot ("392-192"), community, no, name, units, district, parcel,
and (v228) i / pid / bldgs - the footprint index, the DLD property_id and how many buildings share the parcel, so the map can
resolve a plot to its building by ID rather than by name.
Pushed as KV `plots`; the map draws it above zoom 14.5 as a label layer.
Usage: python scripts/plot_points.py [--no-push]
"""
import json, os, re, sys, glob, time, collections
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


def nwords(s):
    """Significant words of a building name, for the rescue's identity test. Drops the fillers that
    make unrelated towers look alike, so a shared word means something."""
    out = re.sub(r"[^a-z0-9 ]+", " ", str(s or "").lower()).split()
    return {w for w in out if len(w) > 2 and w not in ("the", "by", "at", "tower", "towers", "residence", "residences", "building", "dubai")}


def plot_label(parcel, community, no):
    if community and no: return f"{community}-{no}"
    try:
        v = int(float(parcel)); return f"{v // 10000}-{v % 10000}"
    except Exception:
        return None


def main():
    do_push = "--push" in sys.argv and "--no-push" not in sys.argv
    reg = load(os.path.join(IDENT, "reg_bindings.json"), {}) or {}
    tx = load(os.path.join(IDENT, "tx_bindings.json"), {}) or {}
    # v233 - a building's register row does not always sit in the file named after its district. DLD
    # reassigned the seven Sobha Heartland towers (Maybach Six, Vision Iconic and five others) to
    # Meydan, so their property_ids left units_buildings_sobhaheartland.json while the footprints kept
    # their district - and units, master and plot area silently became null on plots that still
    # resolve perfectly well. Nothing is lost, it is just filed elsewhere, so look citywide by
    # property_id when the district's own file does not hold it. The district file still wins.
    ANY = {}
    for _p in glob.glob(os.path.join(DLD, "units_buildings_*.json")):
        for _b in (load(_p, {}) or {}).get("buildings", []):
            ANY.setdefault(str(_b.get("property_id")), _b)

    feats = []; seen = set(); per = collections.Counter(); rescued = 0
    for slug in sorted({k for k in list(reg) + list(tx) if not k.startswith("_")}):
        A = load(os.path.join(NAMES, f"anchors_{slug}.json"), {}) or {}
        pos = {a["i"]: (a.get("lon"), a.get("lat")) for a in A.get("anchors", []) if a.get("lon") is not None}
        ub = {str(b.get("property_id")): b for b in (load(os.path.join(DLD, f"units_buildings_{slug}.json"), {}) or {}).get("buildings", [])}
        rows = dict(tx.get(slug) or {}); rows.update(reg.get(slug) or {})       # the register binding wins where both exist
        for i_s, v in rows.items():
            i = int(i_s)
            lonlat = pos.get(i)
            if not lonlat or lonlat[0] is None: continue
            # v235 - `ub` is keyed by str(property_id), so a register row whose property_id is null
            # lands under the literal key "None" - and a tx binding, which carries no property_id at
            # all, then matched it. Thirteen unrelated buildings on Dubai Investment Park (Lake Views,
            # South West Apartments, Garden Apartments West...) all inherited that one row: the same
            # plot label 598-771 and the same 47,782 units, a master community's total. No id, no
            # lookup - an absent key must not be a key.
            pid = v.get("property_id")
            b = (ub.get(str(pid)) if pid else None) or {}
            if not b and pid:
                # A rescue has to clear the same two tests we apply on screen, because a bare
                # property_id lookup does not. Taken on its own it pulled 766 rows, and most were
                # wrong: AL THAMAM 26, 20, 49, 10 and 8 all matched one row carrying 47,782 units -
                # a master community's total pasted onto individual buildings. So the candidate must
                # agree on IDENTITY (a shared significant word with the binding's name) and on SCOPE
                # (a unit count within 15% of what the binding says this building holds). Either one
                # alone lets the aggregates through.
                cand = ANY.get(str(pid)) or {}
                if cand:
                    cn, vn = nwords(cand.get("name")), nwords(v.get("name"))
                    same_name = bool(cn & vn)
                    cu, vu = cand.get("units"), v.get("units")
                    same_scope = bool(cu and vu and abs(cu - vu) <= max(2, 0.15 * vu))
                    if same_name and same_scope:
                        b = cand; rescued += 1
            parcel = v.get("parcel") or b.get("parcel") or b.get("plot_parcel")
            lab = plot_label(parcel, b.get("community"), b.get("plot_no"))
            if not lab: continue
            key = (slug, i)
            if key in seen: continue
            seen.add(key); per[slug] += 1
            # v228 - carry the ids the binding already proved, so the map can resolve a plot to its building by
            # ID instead of by name. `i` is the footprint index, which is the key of unitmix_<slug>.buildings_by_id;
            # the binding that put this label here was made per footprint, so `i` is a per-BUILDING fact. `bldgs` is how
            # many buildings share the parcel - a plot is not a building, and where bldgs > 1 nothing downstream may
            # present one building's record as though it described the whole plot.
            feats.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [round(lonlat[0], 6), round(lonlat[1], 6)]},
                          "properties": {"plot": lab, "name": v.get("name") or v.get("building"), "units": b.get("units"),
                                         "master": b.get("master"), "district": slug, "parcel": str(parcel) if parcel else None,
                                         "area_sqm": b.get("plot_area_sqm"),
                                         "i": i, "pid": str(pid) if pid else None,
                                         "bldgs": b.get("buildings_on_plot")}})
    doc = {"type": "FeatureCollection", "generated": time.strftime("%Y-%m-%d %H:%M"),
           "note": "Plot number = community number and plot number from the Dubai Land Department parcel id, placed at the building's own footprint. No parcel outlines exist publicly, so this is the number without the boundary.",
           "features": feats}
    json.dump(doc, open(os.path.join(BOARD, "plots.json"), "w", encoding="utf-8"), ensure_ascii=False)
    print(f"plot points: {len(feats):,} across {len(per)} districts | {os.path.getsize(os.path.join(BOARD, 'plots.json'))//1024} KB"
          + (f" | {rescued} rescued from another district's register file" if rescued else ""))
    for s, n in per.most_common(8): print(f"  {s:<26}{n:>6}")
    if "--push" not in sys.argv:
        print("  not pushed. data/board/plots.json is written; pass --push to ship it, and only with the"
              " deploying session's agreement.")
    if do_push: print("plots ->", push("plots", doc, env_token("INGEST_TOKEN")).get("ok"))


if __name__ == "__main__":
    main()
