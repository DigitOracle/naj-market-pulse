"""Feasibility audit for the next developer fly-through: Ellington Properties (25 Sep 2026, read-only - writes nothing but its
own report). Follows Stages 1-3 of the developer fly-through bible
(DigitAlchemy_31MAY2026/Visualization_Engine/Developer_Flythroughs_Unreal/BIBLE.md).

Identity: DLD developer_number, never developer_name (Ellington's main number 1117 shows the LANDOWNER - Jumeirah Village,
Meydan, DMCC - per project). Group = 1117 plus the single-purpose entities whose only projects are Ellington's (see GROUP).
Excluded after checking: 1494 (LEOS: Weybridge Gardens, Hadley Heights), 581 Dana Tower and 1133 Burj Sabah (the identity
layer tags them Ellington; the register says otherwise).

Per project: the district slug(s) its DLD area maps to and whether that tile is massed; footprints found by
  parcel     a parcel key on the footprint (stack plot key / unitmix parcel / geojson parcel_key) in the project's register parcels
  name       an exact (normalised) name match in the geojson, the DM-bound stack name or the identity layer
  identity   the identity layer's developer field says Ellington and its name matches the project
the massed height (with the heights register's lift), the DM permit's floors on the parcel, and a Google point.
Grade: READY (footprint, real height) / HEIGHT (footprint, stub height, a permit or storeys to fix it) / PLACEHOLDER (no
footprint, tile massed, a position and a size exist) / NO-TILE (area not massed) / VILLAS (villa scheme, no plot geometry).
Output: data/board/ellington_feasibility.{json,md}
"""
import json, os, re, sys
from collections import defaultdict

import duckdb

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CE = os.path.join(ROOT, "data", "ce"); BOARD = os.path.join(ROOT, "data", "board")
GROUP = {1117: "Ellington Properties (main)", 1910: "Hillmont SPV", 1687: "Arbor View / Claydon SPV", 1638: "Ellington House IV SPV",
         1453: "Ellington House SPV", 1508: "Ellington House II SPV", 1547: "Ellington House III SPV", 1454: "Ellington Beach House SPV",
         1507: "Oakley Square SPV", 1535: "Art Bay SPV", 1590: "The Quayside SPV", 1986: "Ellington Karma (Belgravia Gardens)",
         1466: "Mercer House SPV", 1647: "One River Point SPV (Dutco Ellington)", 2371: "Eltiera SPV", 2420: "Windsor House SPV"}
AREA = {"Al Barsha South Fourth": ["jumeirahvillagecircle"], "Burj Khalifa": ["burjkhalifa"], "Al Merkadh": ["sobhaheartland", "bukadra"],
        "Al Barsha South Fifth": ["jumeirahvillagetriangle"], "Al Thanyah Fifth": ["althanyahfifth", "jltnorth"], "Business Bay": ["businessbay"],
        "Nadd Hessa": ["siliconoasis"], "Bukadra": ["bukadra", "sobhaheartland"], "Al Barshaa South Third": ["arjan"],
        "Hadaeq Sheikh Mohammed Bin Rashid": ["dubaihills"], "Palm Jumeirah": ["palmjumeirah"], "Al Jadaf": ["samaaljadaf"],
        "Wadi Al Safa 3": [], "Wadi Al Safa 2": [], "Madinat Al Mataar": ["madinatalmataar"]}
GEOCODE = os.path.join(ROOT, "data", "geocode_cache.json")


def norm(s):
    s = (s or "").lower().replace("by ellington", "").replace("residences", "residence")
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", s)).strip()


def load(p, default=None):
    return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else default


def main():
    con = duckdb.connect(os.path.join(ROOT, "data", "graph", "najma.duckdb"), read_only=True)
    nums = ",".join(str(n) for n in GROUP)
    projects = con.execute(f"""select p.project_number, trim(t.n), p.developer_number, p.project_status, round(p.percent_completed),
            p.area_name_en, p.no_of_buildings, p.no_of_villas, p.no_of_units, cast(p.project_start_date as varchar)[:10], cast(p.completion_date as varchar)[:10]
        from gov_dld__projects p left join (select project_number, any_value(project_name_en) n from gov_dld__transactions group by 1) t using(project_number)
        where p.developer_number in ({nums}) order by p.area_name_en, t.n""").fetchall()
    parcels = defaultdict(set)
    for pn, pk in con.execute(f"""select p.project_number, cast(cast(r.parcel_id as bigint) as varchar) from gov_dld__land_registry r join gov_dld__projects p using(project_id)
            where p.developer_number in ({nums}) and r.parcel_id is not null""").fetchall():
        parcels[int(pn)].add(pk)
    geo = load(GEOCODE, {})
    D = {}

    def district(slug):
        if slug in D:
            return D[slug]
        fc = load(os.path.join(CE, slug, "buildings.geojson"))
        if not fc:
            D[slug] = None; return None
        feats = fc["features"]
        ident = (load(os.path.join(ROOT, "data", "identity", "identity_%s.json" % slug), {}) or {}).get("by_index", {})
        stack = (load(os.path.join(BOARD, "stack_%s.json" % slug), {}) or {}).get("buildings_by_id", {})
        umix = (load(os.path.join(BOARD, "unitmix_%s.json" % slug), {}) or {}).get("buildings_by_id", {})
        hreg = (load(os.path.join(CE, slug, "heights_register.json"), {}) or {}).get("heights", {})
        dm = (load(os.path.join(BOARD, "parcel_buildings_%s.json" % slug), {}) or {}).get("parcels", {})
        rows = []
        for i, f in enumerate(feats):
            pr = f.get("properties") or {}; s = stack.get(str(i)) or {}; u = umix.get(str(i)) or {}; r = ident.get(str(i)) or {}
            pk = str((s.get("plot") or {}).get("key") or "") or str((u.get("dld") or {}).get("parcel") or "").split(".")[0] or str(pr.get("parcel_key") or "")
            h = float(pr.get("bHeight") or 0); rh = hreg.get(str(i))
            if rh and abs(h - 12.0) < 0.01:
                h = float(rh)
            rows.append({"i": i, "names": {norm(pr.get("name")), norm(s.get("name")), norm(r.get("name"))} - {""}, "dev": (r.get("developer") or "").lower(),
                         "pk": pk, "h": h, "storeys": r.get("storeys"), "area_ok": True})
        D[slug] = {"rows": rows, "dm": dm}
        return D[slug]

    out = []
    for pn, name, dn, status, pct, area, nb, nv, nu, start, done in projects:
        slugs = AREA.get(area, None)
        nn = norm(name)
        hits, dm_floors, massed = [], [], []
        for s in (slugs or []):
            d = district(s)
            if d is None:
                continue
            massed.append(s)
            for r in d["rows"]:
                how = None
                if r["pk"] and r["pk"] in parcels[pn]:
                    how = "parcel"
                elif nn and nn in r["names"]:
                    how = "identity" if "ellington" in r["dev"] else "name"
                if how:
                    hits.append({"slug": s, "i": r["i"], "how": how, "h": round(r["h"]), "storeys": r["storeys"]})
            for pk in parcels[pn]:
                for x in d["dm"].get(pk, []):
                    if x.get("status") != "Building Cancelled" and int(x.get("floors_above") or 0) >= 3:
                        dm_floors.append((int(x["floors_above"]), x.get("height_m")))
        # one footprint may sit in two overlapping district files: keep one per (rounded) index set by slug order
        seen, uniq = set(), []
        for h in hits:
            k = (h["h"], h["how"])
            if (h["slug"], h["i"]) not in seen:
                seen.add((h["slug"], h["i"])); uniq.append(h)
        gkey = next((k for k in geo if k.startswith("goog::") and nn and norm(k[6:]).startswith(nn[:18]) and isinstance(geo[k], dict) and geo[k].get("lon")), None)
        stub = [h for h in uniq if h["h"] <= 15]
        villas_only = (nv or 0) > 0 and not (nb or 0)
        if not slugs or not massed:          # area with no district slug, or a slug whose tile is not massed
            grade = "VILLAS (no tile)" if villas_only else "NO-TILE"
        elif villas_only:
            grade = "VILLAS"
        elif uniq and not stub:
            grade = "READY"
        elif uniq:
            grade = "HEIGHT" if (dm_floors or any(h["storeys"] for h in uniq)) else "HEIGHT (no source)"
        else:
            grade = "PLACEHOLDER" if (gkey or dm_floors) else "PLACEHOLDER (no position)"
        out.append({"project_number": pn, "name": name, "entity": int(dn), "status": status, "pct": pct, "area": area, "buildings": nb, "villas": nv,
                    "units": nu, "start": start, "completed": done, "slugs": slugs, "massed": massed, "footprints": uniq,
                    "dm_floors": sorted(set(dm_floors), reverse=True)[:4], "google": gkey, "grade": grade})
    grades = defaultdict(list)
    for r in out:
        grades[r["grade"].split(" (")[0]].append(r)
    tot = {"projects": len(out), "units": sum(int(r["units"] or 0) for r in out), "villas": sum(int(r["villas"] or 0) for r in out),
           "by_status": {s: sum(1 for r in out if r["status"] == s) for s in sorted({r["status"] for r in out})},
           "by_grade": {g: len(v) for g, v in grades.items()}}
    json.dump({"generated": __import__("time").strftime("%Y-%m-%d %H:%M"), "group": {str(k): v for k, v in GROUP.items()}, "totals": tot, "projects": out},
              open(os.path.join(BOARD, "ellington_feasibility.json"), "w", encoding="utf-8"), indent=1, default=str, ensure_ascii=False)
    print(json.dumps(tot, indent=1))
    for r in out:
        f = ",".join("%s/%d:%s:%dm" % (h["slug"][:6], h["i"], h["how"], h["h"]) for h in r["footprints"][:4])
        print("%-5s %-34s %-11s %3s%% %-26s b%s v%s u%-4s | %-18s | %s | DM %s | G %s" % (r["project_number"], (r["name"] or "")[:34], r["status"][:11], int(r["pct"] or 0),
              (r["area"] or "")[:26], r["buildings"], r["villas"], r["units"], r["grade"], f or "-", r["dm_floors"][:2], "y" if r["google"] else "-"))


if __name__ == "__main__":
    main()
