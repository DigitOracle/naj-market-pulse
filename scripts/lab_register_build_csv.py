"""LAB (register thread, research only): one register row per footprint, keyed by b<i>, for a district.

The model already carries b<i> (the footprint index) in every mesh name; this is the table that says what
b<i> IS. It joins the registers we hold, in a fixed order, and records where each field came from, so a
value that travels into the GLB / Datasmith can always be traced back to its source.

  id / i              b<i> and the footprint index into data/ce/<slug>/buildings.geojson
  duid                data/names/anchors_<slug>.json anchors[].duid (our stable building id)
  name  (name_src)    unitmix name -> anchors name -> bldgfacts name -> geojson name (OSM, may be Arabic)
  developer           unitmix developer -> anchors dev -> bldgfacts dev.  NOT master_developer_number: that
                      field points DAMAC at Emaar (data/names memory: DLD register traps)
  project             unitmix dld.project (DLD, often upper case) -> anchors dev_project -> bldgfacts project
  property_id         unitmix dld.property_id (DLD building property)
  floors (floors_src) DM floor register (stack, per-floor rows) -> unitmix dm floors -> unitmix floors ("estimate")
  units  (units_src)  THIS building's units only: registered_homes, else total_units when the DLD property
                      holds this one building (dld.buildings == 1), else a register lower bound (total_basis).
                      When the DLD property spans several buildings, total_units is the PROJECT's total
                      (alhebiahfifth: 48 villas each carry REMRAAM's 11,444) - it goes to project_units /
                      project_buildings, never to units. units_indicative (our massing's upper bound) kept apart
  status              unitmix status: verified | partial | placeholder
  height_m            bldgfacts height_m (the massing's own height)
  floor_uses          DM per-floor use, ground up, "|"-joined (stack floors[].u) - the Tutorial 21 per-floor array
  as_of               unitmix as_of

Writes data/lab/register/register_<slug>.csv (UTF-8, RFC 4180 quoting) and register_<slug>.json (coverage).

  python scripts/lab_register_build_csv.py alyufrah1 [alhebiahfifth arjan ...]
"""
import csv
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
OUT = os.path.join(ROOT, "data", "lab", "register")

COLS = ["id", "i", "duid", "name", "name_src", "developer", "project", "property_id", "floors", "floors_src",
        "units", "units_src", "project_units", "project_buildings", "units_indicative", "status", "height_m", "floor_uses", "as_of"]


def load(p, default=None):
    try:
        return json.load(open(p, encoding="utf-8"))
    except (OSError, ValueError):
        return default


def first(*pairs):
    """(value, source) of the first non-empty value."""
    for v, src in pairs:
        if v not in (None, "", [], {}):
            return v, src
    return "", ""


def num(v):
    if v in (None, ""):
        return ""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return ""
    return int(f) if f == int(f) else round(f, 1)


def rows_for(slug):
    feats = json.load(open(os.path.join(ROOT, "data", "ce", slug, "buildings.geojson"), encoding="utf-8"))["features"]
    um = (load(os.path.join(ROOT, "data", "board", "unitmix_%s.json" % slug), {}) or {}).get("buildings_by_id", {})
    bf = (load(os.path.join(ROOT, "data", "board", "bldgfacts_%s.json" % slug), {}) or {}).get("buildings_by_id", {})
    st = (load(os.path.join(ROOT, "data", "board", "stack_%s.json" % slug), {}) or {}).get("buildings_by_id", {})
    an = {str(a.get("i")): a for a in (load(os.path.join(ROOT, "data", "names", "anchors_%s.json" % slug), {}) or {}).get("anchors", [])}
    out = []
    for i, f in enumerate(feats):
        k = str(i)
        u, b, s, a, pr = um.get(k, {}) or {}, bf.get(k, {}) or {}, st.get(k, {}) or {}, an.get(k, {}) or {}, f.get("properties", {})
        dld = u.get("dld") or {}
        dm = u.get("dm") or {}
        name, name_src = first((u.get("name"), "unitmix"), (a.get("name"), "anchors:" + str(a.get("source") or "")),
                               (b.get("name"), "bldgfacts"), (pr.get("name"), "geojson"))
        dev, _ = first((u.get("developer"), "unitmix"), (a.get("dev"), "anchors"), (b.get("dev"), "bldgfacts"))
        proj, _ = first((dld.get("project"), "dld"), (a.get("dev_project"), "anchors"), (b.get("project"), "bldgfacts"))
        floor_rows = [fl for fl in (s.get("floors") or []) if fl.get("l") not in ("R",)]
        dm_above = dm.get("floors_above")
        if floor_rows:
            floors, floors_src = len(floor_rows), "dm_floors"
        elif dm_above not in (None, ""):
            floors, floors_src = int(dm_above) + 1, "dm_permit"          # G + n above
        elif u.get("floors") not in (None, ""):
            floors, floors_src = u.get("floors"), "estimate"
        else:
            floors, floors_src = "", ""
        units, units_src, p_units, p_bldgs = "", "", "", ""
        tu, nb = u.get("total_units"), dld.get("buildings")
        if u.get("registered_homes") not in (None, ""):
            units, units_src = u["registered_homes"], "dld_registered"
        elif tu not in (None, "") and nb == 1:
            units, units_src = tu, "dld_register"
        elif tu not in (None, "") and u.get("total_basis"):
            units, units_src = tu, "dld_lower_bound"
        elif tu not in (None, ""):
            p_units, p_bldgs = tu, nb if nb is not None else ""
        out.append({
            "id": "b%d" % i, "i": i, "duid": a.get("duid") or "",
            "name": str(name).strip(), "name_src": name_src,
            "developer": str(dev).strip(), "project": str(proj).strip(),
            "property_id": str(dld.get("property_id") or ""),
            "floors": num(floors), "floors_src": floors_src,
            "units": num(units), "units_src": units_src, "project_units": num(p_units), "project_buildings": num(p_bldgs),
            "units_indicative": num(u.get("indicative_homes")),
            "status": str(u.get("status") or ""),
            "height_m": num(b.get("height_m")),
            "floor_uses": "|".join(str(fl.get("u") or "") for fl in floor_rows),
            "as_of": str(u.get("as_of") or ""),
        })
    return out


def main():
    slugs = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not slugs:
        print(__doc__); return 2
    os.makedirs(OUT, exist_ok=True)
    for slug in slugs:
        rows = rows_for(slug)
        p = os.path.join(OUT, "register_%s.csv" % slug)
        with open(p, "w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=COLS, quoting=csv.QUOTE_MINIMAL, lineterminator="\n")
            w.writeheader()
            w.writerows(rows)
        cov = {c: sum(1 for r in rows if r[c] not in ("", None)) for c in COLS}
        cov["units_src"] = {s: sum(1 for r in rows if r["units_src"] == s) for s in ("dld_registered", "dld_register", "dld_lower_bound")}
        cov["project_total_not_carried_as_units"] = sum(1 for r in rows if r["project_units"] != "")
        cov["floors_src"] = {s: sum(1 for r in rows if r["floors_src"] == s) for s in ("dm_floors", "dm_permit", "estimate", "")}
        cov["status"] = {s: sum(1 for r in rows if r["status"] == s) for s in sorted(set(r["status"] for r in rows))}
        cov["non_ascii_names"] = sum(1 for r in rows if any(ord(ch) > 127 for ch in r["name"]))
        cov["names_with_comma_or_quote"] = sum(1 for r in rows if ("," in r["name"] or '"' in r["name"]))
        json.dump({"slug": slug, "buildings": len(rows), "coverage": cov, "csv": os.path.relpath(p, ROOT)},
                  open(os.path.join(OUT, "register_%s.json" % slug), "w", encoding="utf-8"), indent=1)
        print("  %-14s %4d rows  name %d  developer %d  project %d  units %s  project-total-only %d  floors %s  -> %s"
              % (slug, len(rows), cov["name"], cov["developer"], cov["project"], cov["units_src"],
                 cov["project_total_not_carried_as_units"], cov["floors_src"], os.path.relpath(p, ROOT)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
