"""UNIT MIX per building - the card a broker needs at a glance: how many units, of what type, on which levels, and the split by
asset class (residential / office / retail). Every modelled building gets a record; where we do not hold the mix yet the
record is an honest PLACEHOLDER that says what we do know and which source fills the rest.

Layers, most authoritative first (each record lists the sources it used):
  dld_buildings   data/dld/buildings_register.csv (Dubai Land Department buildings register, on disk): FLATS / OFFICES / SHOPS,
                  FLOORS, CAR_PARKS, PROJECT_EN, AREA_EN. Matched to a footprint by project name (normalised) inside the same
                  district. Gives the asset-class split and the total. Status -> "verified" at asset-class level.
  register        data/board/projfacts.json: units (total) + mix (the unit types the developer sells). Status -> "partial".
  sheet           data/avail/<developer>_<date>.json: what is on the developer's availability sheet TODAY, counted by type
                  (available now, not the building's total).
  model           data/board/bldgfacts_<slug>.json: homes registered (DLD transactions seen) and the model's indicative count.
  brochure        (future) unit-mix tables from developer decks (levels per type) - the shape in the reference photo.

Output  data/board/unitmix_<slug>.json     {"buildings_by_id": {"<i>": REC}}                  -> KV unitmix_<slug>
        data/board/unitmix_projects.json   {"<normalised project name>": REC + district + i} -> KV unitmix_projects (HOMES hover)
REC = {status: verified|partial|placeholder, name, total_units, asset_classes:{residential,office,retail}, floors, car_parks,
       rows:[{type, configuration, levels, units, basis}], sheet:{date, developer, by_type:{...}, n}, registered_homes,
       indicative_homes, sources:[...], needs:[...], as_of}
Usage: python scripts/build_unit_mix.py [--dry] [slug ...]
"""
import csv, glob, json, os, re, sys, collections, datetime as dt
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
BOARD = os.path.join(ROOT, "data", "board"); NAMES = os.path.join(ROOT, "data", "names"); CE = os.path.join(ROOT, "data", "ce")
from dld_rent_buildings import DLD_AREA   # the shared map: DLD area name -> [twin slug, ...], all 40 modelled districts
TILE_TWIN = {"jltnorth": "jltsouth"}   # a DLD area that maps to a tile pair is searched in both
TYPE_LABEL = {"studio": "Studio", "1 b/r": "1 bedroom", "2 b/r": "2 bedroom", "3 b/r": "3 bedroom", "4 b/r": "4 bedroom", "5 b/r": "5 bedroom", "penthouse": "Penthouse", "office": "Office", "retail": "Retail", "shop": "Retail", "duplex": "Duplex"}


def norm(s): return re.sub(r"[^a-z0-9]", "", str(s or "").lower())
def stem(s): return re.sub(r"\b(by|the|tower|towers|residences?|residence|building|bldg|apartments?)\b", "", str(s or "").lower())
def nkey(s): return norm(stem(s))


def load_dld():
    """DLD Buildings table (property level, 4 Sep 2026 export): one row per building with flats / offices / shops, floors, car parks,
    elevators, parcel, project (= the tower name for towers). Falls back to the older register pull if the export is absent."""
    p = os.path.join(ROOT, "data", "dld", "buildings_2026-09-04.csv")
    if not os.path.exists(p): p = os.path.join(ROOT, "data", "dld", "buildings_register.csv")
    if not os.path.exists(p): return {}
    by = collections.defaultdict(list)
    def g(r, *ks):
        for k in ks:
            if k in r and r[k] not in (None, ""): return r[k]
        return ""
    for r in csv.DictReader(open(p, encoding="utf-8", errors="replace")):
        slug = (DLD_AREA.get(g(r, "area_name_en", "AREA_EN")) or [None])[0]
        proj = (g(r, "project_name_en", "PROJECT_EN") or "").strip()
        if not slug or not proj: continue
        fl = int(float(g(r, "flats", "FLATS") or 0)); of = int(float(g(r, "offices", "OFFICES") or 0)); sh = int(float(g(r, "shops", "SHOPS") or 0))
        if fl + of + sh == 0 and (g(r, "property_sub_type_en", "PROP_SUB_TYPE_EN") or "") != "Building": continue
        rec = {"project": proj, "flats": fl, "offices": of, "shops": sh, "floors": int(float(g(r, "floors", "FLOORS") or 0)), "levels": int(float(g(r, "bld_levels", "BLD_LEVELS") or 0)),
               "car_parks": int(float(g(r, "car_parks", "CAR_PARKS") or 0)), "elevators": int(float(g(r, "elevators") or 0)), "pools": int(float(g(r, "swimming_pools") or 0)), "freehold": g(r, "is_free_hold", "IS_FREE_HOLD"),
               "parcel": g(r, "parcel_id", "PARCEL_ID"), "land": g(r, "land_number", "LAND_NUMBER"), "bno": g(r, "building_number", "BUILDING_NUMBER"), "property_id": g(r, "property_id"), "area": g(r, "area_name_en", "AREA_EN"), "created": g(r, "creation_date", "CREATION_DATE")}
        for s in ((DLD_AREA.get(g(r, "area_name_en", "AREA_EN")) or []) + [TILE_TWIN.get(slug)]):
            if s: by[s].append(rec)
    return by


def load_sheets():
    """latest sheet per developer -> {project nkey: {date, developer, by_type, n}}"""
    latest = {}
    for p in sorted(glob.glob(os.path.join(ROOT, "data", "avail", "*.json"))):
        if os.path.basename(p).startswith("_"): continue
        try: j = json.load(open(p, encoding="utf-8"))
        except Exception: continue
        dev = (j.get("developer") or os.path.basename(p).split("_")[0]).strip(); d = j.get("sheet_date") or ""
        if dev in latest and latest[dev][0] > d: continue
        latest[dev] = (d, j)
    out = {}
    for dev, (d, j) in latest.items():
        for pr in (j.get("projects") or []):
            units = pr.get("units") or []; bt = collections.Counter((u[1] if len(u) > 1 else "?") for u in units)
            out[nkey(pr.get("p") or pr.get("block") or "")] = {"date": d, "developer": dev, "project": pr.get("p"), "by_type": dict(bt), "n": len(units), "completion": pr.get("completion"), "plan": pr.get("plan")}
    return out


def main():
    dry = "--dry" in sys.argv; want = [a for a in sys.argv[1:] if not a.startswith("--")]
    slugs = want or sorted(os.path.basename(p)[10:-5] for p in glob.glob(os.path.join(BOARD, "bldgfacts_*.json")))
    P = json.load(open(os.path.join(BOARD, "projfacts.json"), encoding="utf-8")); P = P.get("projects") or P; P = list(P.values()) if isinstance(P, dict) else P
    reg = {}
    for pr in P:
        for nm in [pr.get("name")] + list(pr.get("aliases") or []):
            if nm: reg.setdefault(nkey(nm), pr)
    dld = load_dld(); sheets = load_sheets()
    ub = {}; ub_pid = {}                      # units_buildings_<slug>.json: the register's own unit list rolled up per building (dld_units_buildings.py)
    for slug_ in {x for v in DLD_AREA.values() for x in v}:
        up = os.path.join(ROOT, "data", "dld", f"units_buildings_{slug_}.json")
        if os.path.exists(up):
            for r_ in json.load(open(up, encoding="utf-8")).get("buildings", []):
                ub_pid[str(r_.get("property_id"))] = r_
                if r_.get("name"): ub.setdefault(slug_, {}).setdefault(nkey(r_["name"]), []).append(r_)
    regb = json.load(open(os.path.join(ROOT, "data", "identity", "official", "dld", "reg_bindings.json"), encoding="utf-8")) if os.path.exists(os.path.join(ROOT, "data", "identity", "official", "dld", "reg_bindings.json")) else {}
    rem = {}                                  # remaining.json: launched / sold / on sheet / remaining per project (remaining_inventory.py)
    rp_ = os.path.join(BOARD, "remaining.json")
    if os.path.exists(rp_):
        for k_, v_ in json.load(open(rp_, encoding="utf-8")).get("projects", {}).items():
            rem[k_] = v_
            for rn in v_.get("register_names") or []: rem.setdefault(nkey(rn), v_)
    dm = {}                                   # dm_buildings_<slug>.json: Dubai Municipality record + floor-level file, keyed by DLD property id (dm_bridge.py)
    for slug_ in {x for v in DLD_AREA.values() for x in v}:
        dp = os.path.join(ROOT, "data", "dld", f"dm_buildings_{slug_}.json")
        if os.path.exists(dp): dm.update(json.load(open(dp, encoding="utf-8")).get("buildings", {}))
    geo = json.load(open(os.path.join(ROOT, "data", "identity", "register", "geocoded_projects.json"), encoding="utf-8")) if os.path.exists(os.path.join(ROOT, "data", "identity", "register", "geocoded_projects.json")) else {}
    txb = json.load(open(os.path.join(ROOT, "data", "identity", "official", "dld", "tx_bindings.json"), encoding="utf-8")) if os.path.exists(os.path.join(ROOT, "data", "identity", "official", "dld", "tx_bindings.json")) else {}
    rents = {}
    for slug_ in {x for v in DLD_AREA.values() for x in v}:
        rp = os.path.join(ROOT, "data", "dld", f"rent_projects_{slug_}.json")
        if os.path.exists(rp):
            for pr_ in json.load(open(rp, encoding="utf-8")).get("projects", []): rents.setdefault(slug_, {})[nkey(pr_["project"])] = pr_
    ROOMS_LABEL = {"Studio": "Studio", "1 B/R": "1 bedroom", "2 B/R": "2 bedroom", "3 B/R": "3 bedroom", "4 B/R": "4 bedroom", "5 B/R": "5 bedroom", "6 B/R": "6 bedroom", "PENTHOUSE": "Penthouse", "Office": "Office", "Shop": "Retail", "n/a": "unspecified"}
    tok = None
    if not dry:
        from build_avail_index import env_token, push
        tok = env_token("INGEST_TOKEN")
    projects_out = {}; today = dt.date.today().isoformat(); tot = collections.Counter()
    for slug in slugs:
        bf = json.load(open(os.path.join(BOARD, f"bldgfacts_{slug}.json"), encoding="utf-8")).get("buildings_by_id", {})
        anchors = {str(a.get("i")): a for a in json.load(open(os.path.join(NAMES, f"anchors_{slug}.json"), encoding="utf-8")).get("anchors", [])} if os.path.exists(os.path.join(NAMES, f"anchors_{slug}.json")) else {}
        dld_by = {}
        for r in dld.get(slug, []): dld_by.setdefault(nkey(r["project"]), []).append(r)
        gslug = geo.get(slug, {})
        out = {}
        for i, b in bf.items():
            a = anchors.get(i, {}); g = gslug.get(i, {})
            cand_names = [x for x in (a.get("dev_project"), g.get("name"), a.get("name"), b.get("name"), b.get("project")) if x]
            rec = {"status": "placeholder", "name": cand_names[0] if cand_names else None, "total_units": None, "asset_classes": None, "floors": b.get("storeys"), "car_parks": None, "rows": [], "sheet": None,
                   "registered_homes": b.get("units_registered"), "indicative_homes": b.get("units_indicative"), "developer": a.get("dev") or g.get("developer"), "sources": [], "needs": [], "as_of": today}
            # 1. the register's unit list: units.parent_property_id -> buildings.property_id, matched here by the building's register name
            #    (the transactions name first, then whatever the footprint already carries). Units by rooms type, size, the floors each type sits on.
            tb0 = (txb.get(slug) or {}).get(i)
            if tb0 and tb0.get("building"): cand_names = [tb0["building"]] + ([tb0["project"]] if tb0.get("project") else []) + cand_names
            hit = None
            rb = (regb.get(slug) or {}).get(i)                       # bound by property id: no name round-trip
            if rb and str(rb.get("property_id")) in ub_pid:
                hit = [ub_pid[str(rb["property_id"])]] + [ub_pid[str(x.get("property_id"))] for x in (rb.get("also") or []) if str(x.get("property_id")) in ub_pid]
                if rb.get("name"): cand_names = [rb["name"]] + cand_names
            for nm in ([] if hit else cand_names):
                k = nkey(nm)
                if k and k in ub.get(slug, {}): hit = ub[slug][k]; break
            if not hit:
                for nm in cand_names:
                    k = nkey(nm)
                    if k and k in dld_by: hit = [dict(x, units=x["flats"] + x["offices"] + x["shops"], by_rooms={}, floors_min=None, floors_max=None, parking=None) for x in dld_by[k]]; break
            if hit:
                units = sum(x["units"] for x in hit); fl = sum(x["flats"] for x in hit); of = sum(x["offices"] for x in hit); sh = sum(x["shops"] for x in hit)
                br = {}
                for x in hit:
                    for ty, v in (x.get("by_rooms") or {}).items():
                        cur = br.setdefault(ty, {"n": 0, "median_sqm": None, "floors_min": None, "floors_max": None, "levels": 0})
                        if v["n"] > cur["n"] or cur["median_sqm"] is None: cur["median_sqm"] = v.get("median_sqm")
                        cur["n"] += v["n"]; cur["levels"] += v.get("levels") or 0
                        for kk, fn in (("floors_min", min), ("floors_max", max)):
                            if v.get(kk) is not None: cur[kk] = v[kk] if cur[kk] is None else fn(cur[kk], v[kk])
                if units > 0:
                    if fl + of + sh == 0:                      # building not in the buildings table: classes from the unit types themselves
                        of = sum(v["n"] for t, v in br.items() if t == "Office"); sh = sum(v["n"] for t, v in br.items() if t == "Shop"); fl = units - of - sh
                    fmax = max([x.get("floors_max") or 0 for x in hit] + [0]); floors = max([x.get("floors") or 0 for x in hit] + [0])
                    rec.update({"status": "verified", "total_units": units, "asset_classes": {"residential": fl, "office": of, "retail": sh}, "floors": floors or (int(fmax) if fmax else None) or rec["floors"],
                                "car_parks": sum(x.get("car_parks") or 0 for x in hit) or None, "elevators": sum(x.get("elevators") or 0 for x in hit) or None, "pools": sum(x.get("pools") or 0 for x in hit) or None,
                                "parking_allocated": sum((x.get("parking") or {}).get("allocated", 0) for x in hit) or None,
                                "dld": {"project": hit[0].get("name") or hit[0].get("project"), "buildings": len(hit), "property_id": hit[0].get("property_id"), "parcel": hit[0].get("parcel"), "land": hit[0].get("land"), "freehold": hit[0].get("freehold"),
                                        "units_registered": units, "flats": fl, "offices": of, "shops": sh, "master": hit[0].get("master"), "community": hit[0].get("community"), "plot_no": hit[0].get("plot_no"),
                                        "plot_property_id": hit[0].get("plot_property_id"), "plot_area_sqm": hit[0].get("plot_area_sqm"), "plot_type": hit[0].get("plot_type"), "plot_sub_type": hit[0].get("plot_sub_type"), "buildings_on_plot": hit[0].get("buildings_on_plot")}})
                    if hit[0].get("master"): rec["master_project"] = hit[0]["master"]
                    dmr = dm.get(str(hit[0].get("property_id")))
                    if dmr:
                        rec["dm"] = {k: dmr.get(k) for k in ("dm_building_id", "dm_status", "floors_label", "basements", "floors_above", "podium", "roof", "lifts", "indoor_parking", "outdoor_parking", "usages", "building_type",
                                                             "completed", "permitted", "construction_year", "height_m", "total_area_sqm", "plot_area_sqm", "buildings_on_plot", "dm_buildings_on_parcel", "permit_no", "project_no", "green", "units_by_usage", "levels_by_usage")}
                        if dmr.get("floors_above") and (not rec["floors"] or dmr["floors_above"] > rec["floors"]): rec["floors"] = dmr["floors_above"]; rec["floors_basis"] = "Dubai Municipality permit"
                        if dmr.get("lifts") and not rec.get("elevators"): rec["elevators"] = dmr["lifts"]
                        if dmr.get("indoor_parking") and not rec.get("car_parks"): rec["car_parks"] = dmr["indoor_parking"]
                        lbu = dmr.get("levels_by_usage") or {}
                        def lv_usage(*keys):
                            for k, v in lbu.items():
                                if any(x in k.lower() for x in keys) and v: return (f"{v[0]}\u2013{v[1]}" if v[0] != v[1] else str(v[0]))
                        for r_ in rec["rows"]:
                            if r_.get("levels"): continue
                            if r_["type"] == "Retail": r_["levels"] = lv_usage("commercial", "retail", "shop")
                            elif r_["type"] == "Office": r_["levels"] = lv_usage("office")
                            if r_.get("levels"): r_["levels_basis"] = "DM floor-level file"
                        rec["sources"].append(f"Dubai Municipality building record {dmr['dm_building_id']} on the same parcel ({dmr.get('floors_label') or 'floors n/a'}, {len(dmr.get('floors') or [])} floors listed)")
                    rec["sources"].append(f"Dubai Land Department units register, 4 Sep 2026 ({units} registered units, building property {hit[0].get('property_id')})")
                    def lv(v):
                        if v.get("floors_min") is None: return None
                        a_, b_ = int(v["floors_min"]), int(v["floors_max"]); return (f"{a_}–{b_}" if a_ != b_ else str(a_)) + (f" ({v['levels']} levels)" if v.get("levels") and b_ - a_ + 1 != v["levels"] else "")
                    order = ["Studio", "1 B/R", "2 B/R", "3 B/R", "4 B/R", "5 B/R", "6 B/R", "P–THOUSE", "Office", "Shop"]
                    for ty in sorted(br, key=lambda t: (order.index(t) if t in order else 99, t)):
                        v = br[ty]; rec["rows"].append({"type": ROOMS_LABEL.get(ty, ty), "configuration": (str(round(v["median_sqm"])) + " m² median") if v.get("median_sqm") else None, "median_sqm": v.get("median_sqm"), "levels": lv(v), "units": v["n"], "basis": "DLD units register"})
                    if not br:
                        if fl: rec["rows"].append({"type": "Residential", "configuration": "apartments", "levels": None, "units": fl, "basis": "DLD buildings table"})
                        if of: rec["rows"].append({"type": "Office", "configuration": "commercial suites", "levels": None, "units": of, "basis": "DLD buildings table"})
                        if sh: rec["rows"].append({"type": "Retail", "configuration": "ground and podium", "levels": None, "units": sh, "basis": "DLD buildings table"})
            # 1b. the DLD transactions register bound to this footprint: units sold by type (initial off-plan sales = units; else a lower bound)
            tb = (txb.get(slug) or {}).get(i)
            if tb and tb.get("by_rooms"):
                cand_names = [tb["building"]] + cand_names; rec["name"] = rec["name"] or tb["building"]
                br = {k: v for k, v in tb["by_rooms"].items() if k != "n/a"}; sold = sum(v["n"] for v in br.values())
                rows = [{"type": ROOMS_LABEL.get(k, k), "configuration": (str(round(v["median_sqm"])) + " m² median") if v.get("median_sqm") else None, "levels": None, "units": v["n"], "basis": "DLD sales register - units sold of this type"} for k, v in sorted(br.items(), key=lambda kv: -kv[1]["n"])]
                if not rec["rows"]: rec["rows"] = rows
                rec["dld_sales"] = {"sold_by_type": {ROOMS_LABEL.get(k, k): v["n"] for k, v in br.items()}, "sold_total": sold, "first": tb.get("first"), "last": tb.get("last"), "median_sqm": tb.get("median_sqm"), "median_aed_sqm": tb.get("median_aed_sqm"), "project": tb.get("project"), "metro": tb.get("metro"), "mall": tb.get("mall"), "landmark": tb.get("landmark"), "usage": tb.get("usage")}
                if not rec["total_units"]: rec["total_units"] = sold; rec["total_basis"] = "units sold in the register (lower bound)"
                us = tb.get("usage") or {}
                if not rec["asset_classes"] and us: rec["asset_classes"] = {"residential": us.get("Residential", 0), "office": us.get("Commercial", 0) if "Commercial" in us else 0, "retail": 0}
                rec["sources"].append(f"DLD transactions register ({sold} unit sales, {tb.get('first','')[:4]}-{tb.get('last','')[:4]})")
                if rec["status"] == "placeholder": rec["status"] = "partial"
                for r_ in rec["rows"]:                                   # price per type onto the table rows
                    k_ = next((k for k in br if ROOMS_LABEL.get(k, k) == r_["type"]), None)
                    if k_ and br[k_].get("median_aed"): r_["median_aed"] = br[k_]["median_aed"]; r_["median_sqm"] = br[k_].get("median_sqm")
            # 1c. Ejari rents by type for the same project/building (contracts since 2024) -> rent and gross yield per type
            rk = None
            for nm in ([tb.get("building"), tb.get("project")] if tb else []) + cand_names:
                if nm and nkey(nm) in rents.get(slug, {}): rk = rents[slug][nkey(nm)]; break
            if rk:
                rec["rent_by_type"] = {}; rec["yield_by_type"] = {}
                for ty, v in rk["by_type"].items():
                    lab = ROOMS_LABEL.get(ty, ty); rec["rent_by_type"][lab] = {"n": v["n"], "median_annual": v["median_annual"], "median_sqm": v["median_sqm"], "new": v["new"], "renew": v["renew"]}
                    row = next((r_ for r_ in rec["rows"] if r_["type"] == lab), None)
                    if row is not None: row["median_rent"] = v["median_annual"]; row["rent_n"] = v["n"]
                    if row is not None and row.get("median_aed") and v["median_annual"]:
                        y = round(100.0 * v["median_annual"] / row["median_aed"], 1); row["gross_yield_pct"] = y; rec["yield_by_type"][lab] = y
                rec["rent_source"] = {"project": rk["project"], "contracts": rk["n"], "window": "contracts from 2024"}
                rec["sources"].append(f"Ejari rent contracts ({rk['n']} contracts from 2024, project {rk['project']})")
                if rec["status"] == "placeholder": rec["status"] = "partial"
            # 1d. what is left: launched (units register) - sold (off-plan sales) vs the developer's own sheet (remaining_inventory.py)
            rr = None
            for nm in cand_names:
                k_ = nkey(nm)
                if k_ and (k_ in rem or re.sub(r"[^a-z0-9]", "", str(nm).lower()) in rem): rr = rem.get(k_) or rem.get(re.sub(r"[^a-z0-9]", "", str(nm).lower())); break
            if rr:
                tt = rr.get("totals") or {}
                rec["remaining"] = {"launched": tt.get("launched"), "sold": tt.get("sold"), "resold": tt.get("resold"), "sheet": tt.get("sheet"), "rented": tt.get("rented"), "remaining": tt.get("remaining"), "unaccounted": tt.get("unaccounted"),
                                    "sheet_date": rr.get("sheet_date"), "developer": rr.get("developer"), "first_sale": rr.get("first_sale"), "last_sale": rr.get("last_sale"), "basis": rr.get("basis")}
                if not rec["total_units"] and tt.get("launched"): rec["total_units"] = tt["launched"]; rec["total_basis"] = "DLD units register (launched)"
                bt = rr.get("by_type") or {}
                for ty_, v_ in bt.items():
                    lab = ROOMS_LABEL.get(ty_, ty_)
                    row = next((r_ for r_ in rec["rows"] if r_["type"] == lab), None)
                    if row is None and (v_.get("launched") or v_.get("sheet")):
                        row = {"type": lab, "configuration": None, "levels": None, "units": v_.get("launched"), "basis": "DLD units register"}; rec["rows"].append(row)
                    if row is not None: row.update({"launched": v_.get("launched"), "sold": v_.get("sold"), "sheet": v_.get("sheet"), "remaining": v_.get("remaining"), "unaccounted": v_.get("unaccounted"),
                                                    "ask_min": v_.get("ask_min"), "ask_med": v_.get("ask_med"), "ask_max": v_.get("ask_max"), "ask_n": v_.get("ask_n"), "ask_sqft_med": v_.get("ask_sqft_med"), "median_aed": row.get("median_aed") or v_.get("sold_med")})
                rec["sources"].append(f"remaining = launched (DLD units register) - sold (DLD off-plan sales); developer sheet {rr.get('sheet_date')}")
                if rec["status"] == "placeholder": rec["status"] = "partial"
            # 1e. estimates where the register has no median for a type: building AED/m2 x the type's size; else the building's sales-weighted average
            if tb:
                aedsqm = tb.get("median_aed_sqm")
                br_ = {k: v for k, v in (tb.get("by_rooms") or {}).items() if v.get("median_aed") and v.get("n")}
                wsum = sum(v["n"] for v in br_.values()); wavg = round(sum(v["n"] * v["median_aed"] for v in br_.values()) / wsum) if wsum else None
                for r_ in rec["rows"]:
                    if r_.get("median_aed") or r_.get("est_aed"): continue
                    sqm = r_.get("median_sqm") or (r_.get("ask_sqft_med") * 0.0929 if r_.get("ask_sqft_med") else None)
                    if aedsqm and sqm: r_["est_aed"] = round(aedsqm * sqm); r_["est_basis"] = "register AED/m\u00b2 for this building x the type's median size"
                    elif wavg: r_["est_aed"] = wavg; r_["est_basis"] = "this building's sales-weighted average price, all types"
                if aedsqm: rec["register_aed_sqm"] = aedsqm
                if wavg: rec["register_avg_aed"] = wavg
            # 2. register (projfacts): total + types
            pr = None
            for nm in cand_names:
                if nkey(nm) in reg: pr = reg[nkey(nm)]; break
            if pr:
                if pr.get("units") and not rec["total_units"]: rec["total_units"] = pr["units"]; rec["sources"].append("developer register (units)")
                if pr.get("mix"):
                    rec["mix_types"] = pr["mix"]; rec["sources"].append("developer register (unit types)")
                    if not rec["rows"]:
                        for m in pr["mix"]: rec["rows"].append({"type": TYPE_LABEL.get(str(m).lower(), str(m)), "configuration": None, "levels": None, "units": None, "basis": "developer register - type offered, count not on file"})
                if rec["status"] == "placeholder": rec["status"] = "partial"
                rec["developer"] = rec["developer"] or pr.get("developer") or pr.get("dev")
            # 3. the developer's latest availability sheet
            for nm in cand_names:
                sh = sheets.get(nkey(nm))
                if sh: rec["sheet"] = sh; rec["sources"].append(f"{sh['developer']} availability sheet {sh['date']} ({sh['n']} units listed)"); break
            # 4. model / register counts already carried
            if rec["registered_homes"]: rec["sources"].append("DLD transactions seen for this building")
            # needs
            if rec["status"] != "verified": rec["needs"].append("a register name for this footprint (DLD units register then fills units, types and levels)")
            if not any(r.get("levels") for r in rec["rows"]): rec["needs"].append("floors per type (DLD units register once the footprint is named)")
            if not rec["sheet"]: rec["needs"].append("developer availability sheet for what is on offer now")
            out[i] = rec; tot[rec["status"]] += 1
            for nm in cand_names[:2]:
                if nm: projects_out.setdefault(nkey(nm), dict(rec, district=slug, i=int(i)))
        json.dump({"district": slug, "generated": today, "buildings_by_id": out}, open(os.path.join(BOARD, f"unitmix_{slug}.json"), "w", encoding="utf-8"), ensure_ascii=False)
        c = collections.Counter(r["status"] for r in out.values())
        print(f"  {slug:<24} {len(out):>5} buildings | verified {c.get('verified',0):>4} partial {c.get('partial',0):>4} placeholder {c.get('placeholder',0):>5}" + ("" if dry else f" -> {push('unitmix_' + slug, {'district': slug, 'generated': today, 'buildings_by_id': out}, tok).get('ok')}"))
    # projects the developer sheets cover but no footprint carries yet (Treppan Tower before it is bound): a project record from the register alone
    for k_, v_ in rem.items():
        if k_ in projects_out or not isinstance(v_, dict) or not v_.get("totals"): continue
        tt = v_["totals"]; rows_ = []
        for ty_, x_ in (v_.get("by_type") or {}).items():
            if x_.get("launched") or x_.get("sheet"): rows_.append({"type": ROOMS_LABEL.get(ty_, ty_), "configuration": None, "levels": None, "units": x_.get("launched"), "launched": x_.get("launched"), "sold": x_.get("sold"), "sheet": x_.get("sheet"), "remaining": x_.get("remaining"), "unaccounted": x_.get("unaccounted"),
                                                                    "ask_min": x_.get("ask_min"), "ask_med": x_.get("ask_med"), "ask_max": x_.get("ask_max"), "ask_n": x_.get("ask_n"), "ask_sqft_med": x_.get("ask_sqft_med"), "median_aed": x_.get("sold_med"), "basis": "DLD units register"})
        projects_out[k_] = {"status": "partial" if tt.get("launched") else "placeholder", "name": v_.get("name"), "total_units": tt.get("launched"), "asset_classes": None, "floors": None, "car_parks": None, "rows": rows_, "sheet": None, "developer": v_.get("developer"),
                            "sources": ["DLD units register (launched)", "DLD off-plan sales (sold)", f"developer sheet {v_.get('sheet_date')}"], "needs": ["a footprint on the twin (bind the register name)"], "as_of": today,
                            "remaining": {"launched": tt.get("launched"), "sold": tt.get("sold"), "resold": tt.get("resold"), "sheet": tt.get("sheet"), "rented": tt.get("rented"), "remaining": tt.get("remaining"), "unaccounted": tt.get("unaccounted"), "sheet_date": v_.get("sheet_date"), "developer": v_.get("developer"), "basis": v_.get("basis")}}
    # the hover index carries only what the compact card draws; the full record stays in the district file
    ROW_KEEP = ("type", "units", "sold", "remaining", "sheet", "levels", "median_sqm", "configuration", "median_aed", "est_aed",
                "median_rent", "gross_yield_pct", "ask_med", "ask_min", "ask_max", "ask_n", "basis")
    DLD_KEEP = ("project", "property_id", "community", "plot_no", "master", "plot_area_sqm", "buildings_on_plot", "freehold")
    DM_KEEP = ("floors_label", "basements", "floors_above", "lifts", "indoor_parking", "completed", "dm_status", "height_m")
    slim = {}
    for k_, r_ in projects_out.items():
        o = {x: r_.get(x) for x in ("name", "district", "i", "status", "total_units", "asset_classes", "floors", "car_parks",
                                    "developer", "master_project", "registered_homes", "as_of", "total_basis", "register_aed_sqm") if r_.get(x) is not None}
        o["rows"] = [{x: y for x, y in (row or {}).items() if x in ROW_KEEP and y is not None} for row in (r_.get("rows") or [])[:9]]
        if r_.get("dld"): o["dld"] = {x: r_["dld"].get(x) for x in DLD_KEEP if r_["dld"].get(x) is not None}
        if r_.get("dm"): o["dm"] = {x: r_["dm"].get(x) for x in DM_KEEP if r_["dm"].get(x) is not None}
        if r_.get("remaining"): o["remaining"] = {x: y for x, y in r_["remaining"].items() if x != "basis" and y is not None}
        slim[k_] = o
    json.dump({"generated": today, "projects": projects_out}, open(os.path.join(BOARD, "unitmix_projects.json"), "w", encoding="utf-8"), ensure_ascii=False)
    json.dump({"generated": today, "projects": slim}, open(os.path.join(BOARD, "unitmix_projects_slim.json"), "w", encoding="utf-8"), ensure_ascii=False)
    print(f"unitmix_projects: {len(projects_out):,} projects | full {os.path.getsize(os.path.join(BOARD, 'unitmix_projects.json'))//1024} KB -> hover index {os.path.getsize(os.path.join(BOARD, 'unitmix_projects_slim.json'))//1024} KB")
    if not dry: print("unitmix_projects ->", push("unitmix_projects", {"generated": today, "projects": slim}, tok).get("ok"))
    print(f"TOTAL {dict(tot)} | projects indexed {len(projects_out)}")


if __name__ == "__main__":
    main()
