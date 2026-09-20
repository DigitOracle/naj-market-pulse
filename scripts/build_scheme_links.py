"""What a building lets for, what the register says about its project, and the schools around it.

Three joins onto data/board/stack_<district>.json, all by name, all strict (DDA session, 20 Sep 2026):

  rents    data/dld/rent_projects_<district>.json - Ejari registers at SCHEME level, never per tower: "AL HABTOOR CITY" carries
           1,686 contracts and there is no "Al Habtoor Tower" row at all. So a tower may only take a scheme's rents when its own
           name or its register project name IS that scheme. A near-miss is left empty: borrowing the rent of the scheme next
           door would be a fabrication, and the page would state it as this building's.
  projects data/board/projects_<slug>.json - the DLD project register: escrow agent, percent complete, end date. This is the
           Symphony page's construction section, from the register, for every off-plan building.
  schools  data/board/amenities_<slug>.json - KHDA schools and DHA facilities within 5 km of the DISTRICT centre, with
           curriculum and rating. District context, not a distance from this building's door - the card says which it is.

  python scripts/build_scheme_links.py businessbay damachills   (--push publishes, as the view pass does)
"""
import json, os, re, sys, time

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
BOARD = os.path.join(ROOT, "data", "board")
DLD = os.path.join(ROOT, "data", "dld")
SLUG = {"businessbay": "business_bay", "damachills": "damac_hills"}
GENERIC = set("the by of and a at in to residence residences tower towers building buildings project development dubai "
              "properties property llc fz llp group real estate".split())


def words(x):
    return [w for w in re.findall(r"[a-z0-9]+", str(x or "").lower()) if w not in GENERIC and len(w) > 1]


def same(a, b):
    """Two names are the same scheme only when their distinctive words match exactly, in the same set. 'Al Habtoor Tower' and
    'AL HABTOOR CITY' are NOT the same: tower and city are the distinguishing words, and they differ."""
    wa, wb = set(words(a)), set(words(b))
    return bool(wa) and wa == wb


def rents_of(district):
    p = os.path.join(DLD, "rent_projects_%s.json" % district)
    if not os.path.exists(p):
        return []
    return json.load(open(p, encoding="utf-8")).get("projects") or []


def load(slug_file):
    p = os.path.join(BOARD, slug_file)
    return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else None


def rent_for(rec, umx_rec, schemes):
    names = [rec.get("name"), (umx_rec.get("dld") or {}).get("project"), (umx_rec.get("dld") or {}).get("master")]
    for s in schemes:
        if any(same(n, s.get("project")) for n in names if n):
            by = {}
            for t, v in (s.get("by_type") or {}).items():
                if not v.get("median_annual"):
                    continue
                by[t] = {"n": v.get("n"), "aed": round(v["median_annual"]), "sqm": v.get("median_sqm"),
                         "aed_sqm": v.get("median_aed_sqm"), "new": v.get("new"), "renew": v.get("renew")}
            if by:
                return {"scheme": s.get("project"), "n": s.get("n"), "by_type": by}
    return None


def project_for(umx_rec, projects, by_building):
    """By id, never by name (DDA session, 20 Sep): the units register gives parent_property_id for a building and project_id for
    its project, so our building's own property_id meets a project without a single name comparison. The register holds no
    English project name at all - project_name_en is lifted from the units register - so names are for display only."""
    pid = str((umx_rec.get("dld") or {}).get("property_id") or "")
    if not pid:
        return None
    link = by_building.get(pid)
    row = None
    if link:
        row = next((p for p in projects if str(p.get("project_id")) == str(link.get("project_id"))), None)
    if row is None:
        row = next((p for p in projects if str(p.get("property_id") or "") == pid), None)
    if row is None:
        return None
    pct = row.get("percent_completed")
    try:
        pct = float(pct)
    except (TypeError, ValueError):
        pct = None
    return {"name": row.get("project_name_en") or (link or {}).get("project_name_en") or row.get("project_name"),
            "status": row.get("project_status"), "pct": pct,
            "start": (row.get("project_start_date") or "")[:10] or None,
            "end": (row.get("project_end_date") or row.get("completion_date") or "")[:10] or None,
            "escrow": row.get("escrow_agent_name"), "units": row.get("no_of_units"),
            "buildings": row.get("no_of_buildings"), "registered": row.get("units_registered"),
            "master": row.get("master_project_en") or row.get("master_project_en_units")}


def build(district, push_tok):
    path = os.path.join(BOARD, "stack_%s.json" % district)
    if not os.path.exists(path):
        print("%s: no stack file" % district)
        return None
    doc = json.load(open(path, encoding="utf-8"))
    umx = json.load(open(os.path.join(BOARD, "unitmix_%s.json" % district), encoding="utf-8"))["buildings_by_id"]
    schemes = rents_of(district)
    slug = SLUG.get(district, district)
    pfile = load("projects_%s.json" % slug) or {}
    projects = pfile.get("projects") or []
    by_building = {str(x.get("parent_property_id")): x for x in (pfile.get("building_to_project") or [])}
    amen = load("amenities_%s.json" % slug)
    nr = np = 0
    for i, rec in doc["buildings_by_id"].items():
        u = umx.get(i) or {}
        r = rent_for(rec, u, schemes)
        p = project_for(u, projects, by_building)
        rec["rent"] = r
        rec["project"] = p
        nr += bool(r)
        np += bool(p)
    if amen:
        doc["district_amenities"] = {
            "centre": amen.get("centre"), "radius_km": amen.get("radius_km"),
            "schools": sorted(amen.get("schools") or [], key=lambda s: (s.get("km") if s.get("km") is not None else 99))[:40],
            "health_n": len(amen.get("health") or []),
            "health_top": sorted(amen.get("health") or [], key=lambda s: (s.get("km") if s.get("km") is not None else 99))[:12],
        }
    doc["sources"] = [x for x in (doc.get("sources") or []) if not x.startswith(("Ejari", "DLD project", "KHDA"))] + [
        "Ejari rent contracts since 2024, registered per SCHEME and shown as the scheme's, never as this tower's alone",
        "DLD project register: escrow agent, percent complete, end date",
        "KHDA schools and DHA facilities within %s km of the district centre" % (amen or {}).get("radius_km", 5)]
    json.dump(doc, open(path, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    n = len(doc["buildings_by_id"])
    print("%s: rent on %d of %d buildings (%d Ejari schemes in the district), project register on %d, schools %s"
          % (district, nr, n, len(schemes), np, len((doc.get("district_amenities") or {}).get("schools") or [])))
    if push_tok:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from build_avail_index import push
        print("  push stack_%s -> %s" % (district, push("stack_" + district, doc, push_tok).get("ok")))
    return doc


def main():
    tok = None
    if "--push" in sys.argv:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from build_avail_index import env_token
        tok = env_token("INGEST_TOKEN")
    for d in [a for a in sys.argv[1:] if not a.startswith("--")] or ["businessbay", "damachills"]:
        build(d, tok)


if __name__ == "__main__":
    main()
