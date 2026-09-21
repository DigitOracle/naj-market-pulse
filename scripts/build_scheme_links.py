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
    """Single letters and digits COUNT: "Binghatti Aquarise" and "Binghatti Aquarise - TOWER C" are different buildings of one
    scheme, and the C is the whole difference."""
    return [w for w in re.findall(r"[a-z0-9]+", str(x or "").lower()) if len(w) == 1 or w not in GENERIC]


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


def idstr(v):
    """A register id, however it was written down. The two districts cut by hand carry project ids as integers; the 40 cut by
    build_district_cuts.py carry the same ids as "28943491.0", because they came back through a float column. Comparing the two
    as strings never matched, which is why every district outside Business Bay and DAMAC Hills showed no construction at all."""
    s = str(v if v is not None else "").strip()
    if s.endswith(".0"):
        s = s[:-2]
    return s


def project_for(umx_rec, projects, by_building):
    """By id, never by name (DDA session, 20 Sep): the units register gives parent_property_id for a building and project_id for
    its project, so our building's own property_id meets a project without a single name comparison. The register holds no
    English project name at all - project_name_en is lifted from the units register - so names are for display only."""
    pid = idstr((umx_rec.get("dld") or {}).get("property_id"))
    if not pid:
        return None
    link = by_building.get(pid)
    row = None
    if link:
        row = next((p for p in projects if idstr(p.get("project_id")) == idstr(link.get("project_id"))), None)
    if row is None:
        row = next((p for p in projects if idstr(p.get("property_id")) == pid), None)
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


def land_for(umx_rec, by_prop, by_parcel):
    """The plot this building stands on, from the DLD land registry, joined by the plot's own property id (and by DM parcel id
    where that is all we have). We already carry a freehold flag per building; what the registry adds is the plot's ZONING -
    a residential tower on a commercially zoned plot is a real thing a buyer should see - its registered area and its status."""
    d = umx_rec.get("dld") or {}
    row = by_prop.get(str(d.get("plot_property_id") or ""))
    if row is None and d.get("parcel"):
        try:
            row = by_parcel.get(str(int(float(d["parcel"]))))
        except (TypeError, ValueError):
            row = None
    if row is None:
        return None
    return {"land": row.get("land_number"), "parcel": int(row["parcel_id"]) if row.get("parcel_id") else None,
            "zoned": row.get("land_type_en"), "use": row.get("property_sub_type_en"),
            "area_sqm": round(row["actual_area"]) if row.get("actual_area") else None,
            "freehold": None if row.get("is_free_hold") is None else bool(row["is_free_hold"]),
            "registered": None if row.get("is_registered") is None else bool(row["is_registered"]),
            "project": row.get("project_name_en")}


def makani_of(district, slug):
    """The Makani entrance points, already bound to our duid by the DDA session - the one register that touches a building
    rather than a community, and the address a client actually navigates to."""
    f = load("makani_%s.json" % slug) or {}
    out = {}
    for p in f.get("points") or []:
        d = p.get("duid")
        if not d:
            continue
        cur = out.get(d)
        if cur is None or (p.get("dist_m") or 999) < (cur.get("dist_m") or 999):
            out[d] = p
    return out


def duids_of(district):
    p = os.path.join(ROOT, "data", "identity", "identity_%s.json" % district)
    if not os.path.exists(p):
        return {}
    return {i: v.get("duid") for i, v in (json.load(open(p, encoding="utf-8")).get("by_index") or {}).items() if v.get("duid")}


def sales_for(rec, umx_rec, by_name):
    """The DLD transaction register carries NO property id, no parcel, no land number - only a building name (DDA session,
    20 Sep). So this binds by OUR strict rule, the same one the rents use: the name must match on its distinctive words. The
    card says the sales are registered against that NAME, not that they are provably this footprint's."""
    # only this building's own name: the transaction register names towers, so the scheme name would match a sibling's sales
    names = [rec.get("name")]
    for key, rows in by_name.items():
        if not any(same(n, key) for n in names if n):
            continue
        rows = sorted(rows, key=lambda r: r.get("date") or "")
        px = sorted([r["price_per_sqm"] for r in rows if r.get("price_per_sqm")])
        recent = [{"date": r.get("date"), "rooms": r.get("rooms"), "sqft": round((r.get("area_sqm") or 0) * 10.764) or None,
                   "price": round(r["price"]) if r.get("price") else None,
                   "offplan": (r.get("reg_type") or "").lower().startswith("off")} for r in rows[-6:]][::-1]
        return {"name": key, "n": len(rows),
                "first": (rows[0].get("date") or "")[:10], "last": (rows[-1].get("date") or "")[:10],
                "psf": round(px[len(px) // 2] / 10.764) if px else None,
                "offplan_pct": round(100 * sum(1 for r in rows if (r.get("reg_type") or "").lower().startswith("off")) / len(rows)),
                "recent": recent}
    return None


def permit_for(umx_rec, by_parcel):
    """The plot's building permit. DM permits carry parcel_id and project_no, never a building id, so this is the PLOT's
    permit - on a shared plot it may belong to a neighbour, and the card says so."""
    d = umx_rec.get("dld") or {}
    try:
        key = str(int(float(d.get("parcel"))))
    except (TypeError, ValueError):
        return None
    rows = by_parcel.get(key) or []
    new = [r for r in rows if str(r.get("application_type") or "").startswith("Final-New Building")]
    pick = sorted(new or rows, key=lambda r: r.get("permit_date") or "")[-1:]
    if not pick:
        return None
    r = pick[0]
    return {"type": r.get("application_type"), "no": r.get("permit_no"), "date": (r.get("permit_date") or "")[:10],
            "status": r.get("status"), "buildings": r.get("building_count"), "area": r.get("total_area"),
            "permits_on_plot": len(rows), "new_on_plot": len(new)}


def anchors_of(district):
    p = os.path.join(ROOT, "data", "names", "anchors_%s.json" % district)
    if not os.path.exists(p):
        return {}
    return {str(x["i"]): x for x in (json.load(open(p, encoding="utf-8")).get("anchors") or []) if x.get("i") is not None}


def names_of(slug):
    """Names derived by id, never by string: DM building -> parcel -> DLD land registry project_name_en (DDA session, 20 Sep).
    Where one of these disagrees with the name we bound by string matching, this one is the evidence."""
    f = load("names_%s.json" % slug) or {}
    return {str(x.get("building_id")): x for x in (f.get("buildings_list") or []) if x.get("name")}


def name_check(rec, anchor_name, by_id):
    """Does the id-derived name back our binding, or the map? For the one footprint where the register and the map disagree,
    this is what decides it - and it decided against us: the register bound Enara to the footprint the map calls The Binary."""
    row = by_id.get(str(rec.get("dm") or ""))
    if not row:
        return None
    n = row.get("name")
    ours, theirs, mapped = set(words(rec.get("name"))), set(words(n)), set(words(anchor_name))
    return {"name": n, "plot_code": row.get("plot_code"), "source": row.get("source"),
            "backs_register": bool(ours and ours == theirs),
            "backs_map": bool(mapped and mapped == theirs and ours != theirs),
            "broader": bool(theirs and theirs < ours)}      # the scheme rather than the tower: Golf Panorama, not Tower A


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
    names_id = names_of(slug)
    anchors = anchors_of(district)
    mak = makani_of(district, slug)
    duid = duids_of(district)
    tx = (load("transactions_%s.json" % slug) or {}).get("by_building_name") or {}
    perm = {}
    for r in (load("permits_%s.json" % slug) or {}).get("permits") or []:
        if r.get("parcel_id") is not None:
            perm.setdefault(str(int(float(r["parcel_id"]))), []).append(r)
    lfile = load("land_registry_%s.json" % slug) or {}
    lrows = lfile.get("plots") or []
    by_prop = {idstr(x.get("property_id")): x for x in lrows}
    by_parcel = {str(int(float(x["parcel_id"]))): x for x in lrows if x.get("parcel_id") is not None}
    fh_yes = sum(1 for x in lrows if x.get("is_free_hold"))
    nr = np = nl = nm = nt = npm = 0
    for i, rec in doc["buildings_by_id"].items():
        u = umx.get(i) or {}
        r = rent_for(rec, u, schemes)
        p = project_for(u, projects, by_building)
        rec["rent"] = r
        rec["project"] = p
        rec["land"] = land_for(u, by_prop, by_parcel)
        mp = mak.get(duid.get(i) or "")
        rec["makani"] = {"makani": mp.get("makani"), "dist_m": mp.get("dist_m")} if mp else None
        rec["sales"] = sales_for(rec, u, tx)
        rec["name_id"] = name_check(rec, (anchors.get(i) or {}).get("name"), names_id)
        if rec.get("conflict") and (rec["name_id"] or {}).get("backs_map"):
            rec["conflict_verdict"] = "map"      # the id-derived name agrees with the map: our register binding is the wrong one
        rec["permit"] = permit_for(u, perm)
        nm += bool(rec["makani"]); nt += bool(rec["sales"]); npm += bool(rec["permit"])
        nr += bool(r)
        np += bool(p)
        nl += bool(rec["land"])
    if amen:
        doc["district_amenities"] = {
            "centre": amen.get("centre"), "radius_km": amen.get("radius_km"),
            "schools": sorted(amen.get("schools") or [], key=lambda s: (s.get("km") if s.get("km") is not None else 99))[:40],
            "health_n": len(amen.get("health") or []),
            "health_top": sorted(amen.get("health") or [], key=lambda s: (s.get("km") if s.get("km") is not None else 99))[:12],
        }
    if lrows:
        doc["district_land"] = {"plots": len(lrows), "freehold": fh_yes}      # before the file is written, not after it
    doc["sources"] = [x for x in (doc.get("sources") or []) if not x.startswith(("Ejari", "DLD project", "KHDA"))] + [
        "Ejari rent contracts since 2024, registered per SCHEME and shown as the scheme's, never as this tower's alone",
        "DLD project register: escrow agent, percent complete, end date",
        "KHDA schools and DHA facilities within %s km of the district centre" % (amen or {}).get("radius_km", 5),
        "DLD land registry: the plot's zoning, area, freehold and registration, joined by the plot's property id"]
    json.dump(doc, open(path, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    n = len(doc["buildings_by_id"])
    print("%s: %d of %d buildings - rent %d, project %d, plot %d, makani %d, sales %d, permit %d%s"
          % (district, n, n, nr, np, nl, nm, nt, npm,
             ("; district plots %d of %d freehold" % (fh_yes, len(lrows))) if lrows else ""))
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
