"""Who designed a building, who built it, and how far the Municipality says it has got.

Three cuts the DDA session published on 22 Sep 2026, joined onto the stack through its canonical crosswalk:

  key_bridge_<slug>.json        one row per DLD property_id -> its parcel, the DM buildings on that parcel, its project ids.
                                We hold a property_id on 84% of buildings, so this is the lookup that turns our strongest key
                                into the parcel key four other registers are written against.
  project_team_<slug>.json      the Municipality's contractor and consultant registers, by parcel: designed by X, built by Y.
  project_buildings_<slug>.json project -> DM building, carrying the Municipality's OWN construction stage and the declared
                                building cost. Keyed on the DM building id, so it does not need the parcel at all.

Two things this must not claim:

  * a team is the PARCEL's. Where a plot holds several buildings - and 82,856 parcels citywide do - the contractor named
    against it built something on that plot, not necessarily this tower. The record says how many buildings share it so the
    page can say "the plot's" exactly as it already does for the permit.
  * the Municipality's construction stage is a SECOND opinion, not a correction. It sits beside the developer's percent
    complete, and where the two disagree the page shows both. Percent complete is a filing; so is this.

  python scripts/build_project_team.py businessbay [--push]
  python scripts/build_project_team.py --all --push
"""
import json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
BOARD = os.path.join(ROOT, "data", "board")
sys.path.insert(0, HERE)

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def load(name):
    p = os.path.join(BOARD, name)
    return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else None


def idstr(v):
    s = str(v if v is not None else "").strip()
    return s[:-2] if s.endswith(".0") else s


def build(district, tok):
    sp = os.path.join(BOARD, "stack_%s.json" % district)
    if not os.path.exists(sp):
        print("%-26s no stack" % district)
        return False
    doc = json.load(open(sp, encoding="utf-8"))
    umx = (load("unitmix_%s.json" % district) or {}).get("buildings_by_id") or {}

    bridge = {idstr(b.get("property_id")): b for b in ((load("key_bridge_%s.json" % district) or {}).get("buildings_list") or [])}
    team_by_parcel = {}
    for r in ((load("project_team_%s.json" % district) or {}).get("projects") or []):
        if r.get("contractor_english") or r.get("consultant_english"):
            team_by_parcel.setdefault(idstr(r.get("parcel_id")), []).append(r)
    stage_by_building, stage_by_project = {}, {}
    for r in ((load("project_buildings_%s.json" % district) or {}).get("buildings") or []):
        if r.get("construction_stage") or r.get("building_cost"):
            stage_by_building[idstr(r.get("building_id"))] = r
            stage_by_project.setdefault(idstr(r.get("project_no")), r)

    nb = nt = ns = 0
    for i, rec in doc.get("buildings_by_id", {}).items():
        pid = idstr(((umx.get(i) or {}).get("dld") or {}).get("property_id"))
        row = bridge.get(pid) if pid else None
        parcel = idstr((row or {}).get("parcel_key")) or idstr((rec.get("plot") or {}).get("key"))
        dmid = idstr((row or {}).get("dm_building_id")) or idstr(rec.get("dm"))
        if row:
            rec["bridge"] = {"parcel": parcel or None, "dm": dmid or None,
                             "via": row.get("source_parcel"), "on_plot": row.get("n_dm_buildings")}
            nb += 1

        # designed by / built by - the PARCEL's project, oldest permit first
        rows = team_by_parcel.get(parcel) or []
        if rows:
            r0 = sorted(rows, key=lambda r: str(r.get("first_building_permit_date") or ""))[0]
            rec["team"] = {"contractor": r0.get("contractor_english"), "consultant": r0.get("consultant_english"),
                           "type": r0.get("project_type"), "building_type": r0.get("building_type"),
                           "permit": str(r0.get("first_building_permit_date") or "")[:10] or None,
                           "status": r0.get("project_status"),
                           "on_plot": (row or {}).get("n_dm_buildings") or (rec.get("plot") or {}).get("n"),
                           "projects_on_plot": len(rows)}
            nt += 1

        # the Municipality's own stage, by DM building id first and by its project only as a fallback
        st = stage_by_building.get(dmid) or stage_by_project.get(idstr((row or {}).get("dm_project_no")))
        if st:
            cost = st.get("building_cost") or 0
            rec["stage"] = {"stage": st.get("construction_stage"), "cost": round(cost) if cost else None,
                            "by": "building" if stage_by_building.get(dmid) else "project"}
            ns += 1

    json.dump(doc, open(sp, "w", encoding="utf-8"), ensure_ascii=False)
    n = len(doc.get("buildings_by_id") or {})
    print("%-26s crosswalk %4d/%-4d | designed+built %4d | municipality stage %4d" % (district, nb, n, nt, ns))
    if tok:
        from build_avail_index import push
        print("   push stack_%s -> %s" % (district, push("stack_" + district, doc, tok).get("ok")))
    return True


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if "--all" in sys.argv:
        args = sorted(f[6:-5] for f in os.listdir(BOARD) if f.startswith("stack_") and f.endswith(".json"))
    tok = None
    if "--push" in sys.argv:
        from build_avail_index import env_token
        tok = env_token("INGEST_TOKEN")
    for d in (args or ["businessbay"]):
        build(d, tok)
    return 0


if __name__ == "__main__":
    sys.exit(main())
