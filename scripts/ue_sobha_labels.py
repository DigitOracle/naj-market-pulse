"""Unreal (commandlet): project labels on the Sobha tour - a leader line up from each project's tallest roof to a box
carrying the project's name and its build status, turned to face the camera all the way through the tour.

Kendall, 24 Sep 2026: "add labels to the buildings as well, a line from the top of the building leading to a box with
the name." And, same day: the under-construction indication must not be lost. The client cut shows every tower as built
(its renderings), so the STATUS now travels on the label instead of the facade colour:
    line 1  project name                          white, TEXT_CM high
    line 2  "Completed 2021"                       soft gold          (register status FINISHED)
            "Under construction · 84% · due 2026"  amber              (register status ACTIVE, pct and due from DLD)
and the leader line itself is gold for completed projects, amber for projects still being built.

One label per PROJECT, not per building: the Sobha actors carry "sobha:<project name>" tags from ue_sobha_lens.py; each
project's label stands on its tallest building. Status comes from data/identity/sobha_projects.json (DLD register), joined
through data/ce/_datasmith/sobha_unreal.json (project name -> project_number); where one name covers several register
projects the least complete one speaks for it (a master project is "under construction" while any phase is).
  LBL_<n>_line    /Engine/BasicShapes/Cylinder, vertical from the roof to LINE_M above it (needs no turning)
  LBL_<n>         pivot: a mesh-less StaticMeshActor, MOVABLE, at the top of the line; keyed in SEQ_Sobha_Tour
  LBL_<n>_box     /Engine/BasicShapes/Cube flattened to a panel, attached to the pivot
  LBL_<n>_text    TextRenderActor, the name; LBL_<n>_status the status line; both attached to the pivot
Each pivot gets a yaw key at every camera key, computed from the camera's own keyed positions, so the box faces the lens
through every approach, orbit and pull-out. Run AFTER ue_sobha_tour.py and before the render. Re-running replaces labels.
Usage: UnrealEditor-Cmd.exe <uproject> -run=pythonscript -script=C:/Dev/naj-market-pulse/scripts/ue_sobha_labels.py
"""
import datetime, json, math, os, re

import unreal

LEVEL = "/Game/Main"; SEQ = "/Game/Najma/Cinematics/SEQ_Sobha_Tour"; LBL_DIR = "/Game/Najma/Sobha/Labels"
ROOT = "C:/Dev/naj-market-pulse"
MANIFEST = ROOT + "/data/ce/_datasmith/sobha_unreal.json"; PROJECTS = ROOT + "/data/identity/sobha_projects.json"
# v7 (14 m names, 60 m lines) read well but crowded the close orbits and sat half out of the 4:5 frame; v8 is ~2/3 the size
LINE_M = 40.0          # leader line height above the roof
TEXT_CM = 900.0        # name height
STATUS_CM = 560.0      # status line height
GAP_CM = 160.0
PAD_CM = 320.0
REF_CM = 45000.0       # camera distance at which the base sizes above are right; labels scale linearly beyond it
GOLD = (0.77, 0.65, 0.42); AMBER = (1.0, 0.55, 0.12)
log = unreal.log; eal = unreal.EditorAssetLibrary; ell = unreal.EditorLevelLibrary; MEL = unreal.MaterialEditingLibrary
SKIP = {"parcel", "dm", "claim", "radius", "geocode", "None"}
MOVABLE = unreal.ComponentMobility.MOVABLE


def unlit(name, rgb):
    p = "%s/%s" % (LBL_DIR, name)
    if eal.does_asset_exist(p):
        return eal.load_asset(p)
    if not eal.does_directory_exist(LBL_DIR):
        eal.make_directory(LBL_DIR)
    mat = unreal.AssetToolsHelpers.get_asset_tools().create_asset(name, LBL_DIR, unreal.Material, unreal.MaterialFactoryNew())
    mat.set_editor_property("shading_model", unreal.MaterialShadingModel.MSM_UNLIT)
    c = MEL.create_material_expression(mat, unreal.MaterialExpressionConstant3Vector, -400, 0)
    c.constant = unreal.LinearColor(rgb[0], rgb[1], rgb[2], 1.0)
    MEL.connect_material_property(c, "", unreal.MaterialProperty.MP_EMISSIVE_COLOR)
    MEL.recompile_material(mat); eal.save_asset(p)
    return mat


def pretty(name):
    return " ".join(w if w.isupper() and len(w) <= 3 and w not in ("ONE", "THE") else w.capitalize() for w in re.split(r"\s+", name.strip()))


def statuses():
    """project name (as tagged) -> (status line, under_construction bool)."""
    try:
        reg = json.load(open(PROJECTS, encoding="utf-8"))
        rows = reg["projects"] if isinstance(reg, dict) else reg
        rows = rows if isinstance(rows, list) else list(rows.values())
        by_no = {r.get("project_number"): r for r in rows}
        man = json.load(open(MANIFEST, encoding="utf-8"))
    except Exception as e:
        log("  labels: no status data (%s)" % e); return {}
    nums = {}
    for d in man.get("districts", {}).values():
        for a in d.get("actors", {}).values():
            if a.get("name") and a.get("project_number") is not None:
                nums.setdefault(a["name"], set()).add(a["project_number"])
    today = datetime.date.today().isoformat()
    out = {}
    for name, ns in nums.items():
        recs = [by_no[n] for n in ns if n in by_no]
        if not recs:
            continue
        active = [r for r in recs if str(r.get("status", "")).upper() != "FINISHED"]
        if active:
            r = min(active, key=lambda r: float(r.get("pct") or 0))
            pct = r.get("pct"); due = str(r.get("due") or "")[:4]
            # NOT_STARTED / PENDING (Skyvue, Sobha Central I/II, The Element): launched, not yet building - "0%" read as stalled
            offplan = str(r.get("status", "")).upper() in ("NOT_STARTED", "PENDING") or not float(pct or 0)
            bits = ["Off-plan"] if offplan else ["Under construction"]
            if pct is not None and not offplan:
                bits.append("%d%%" % round(float(pct)))
            if due and str(r.get("due")) >= today:
                bits.append("due %s" % due)
            out[name] = (" \u00b7 ".join(bits), True)
        else:
            yrs = [str(r.get("completed") or r.get("due") or "")[:4] for r in recs]
            yrs = [y for y in yrs if y.isdigit()]
            out[name] = ("Completed %s" % max(yrs) if yrs else "Completed", False)
    return out


def projects():
    """project name -> (x, y, roof z) of its tallest non-duplicate Sobha building."""
    best = {}
    for a in ell.get_all_level_actors():
        if not isinstance(a, unreal.StaticMeshActor):
            continue
        tags = [str(t) for t in a.tags]
        if "sobha" not in tags or "duplicate" in tags:
            continue
        name = next((t[6:] for t in tags if t.startswith("sobha:") and t[6:] and t[6:] not in SKIP), None)
        if not name:
            continue
        o, e = a.get_actor_bounds(False)
        top = o.z + e.z
        if name not in best or top > best[name][2]:
            best[name] = (o.x, o.y, top, best.get(name, (0, 0, 0, 0))[3] + 1)
        else:
            best[name] = best[name][:3] + (best[name][3] + 1,)
    return best


# v13 (Kendall, 25 Sep 2026: "fix the labels"): v12 put 16 labels on the Hartland stop alone. Sister projects now share one
# label - the name of the scheme a buyer knows, with a combined status - and labels that would overlap are stacked.
GROUPS = [("villas", "Sobha Hartland Villas & Estates"), ("estates - townhouse", "Sobha Hartland Villas & Estates"),
          ("greens", "Sobha Hartland Greens"), ("creek vista", "Sobha Creek Vistas"), ("hartland waves", "Sobha Hartland Waves"),
          ("the crest", "Sobha Hartland - The Crest"), ("crest grande", "Sobha Hartland - The Crest"),
          ("riverside crescent", "Riverside Crescent"), ("seahaven", "Sobha SeaHaven"), ("sobha one", "Sobha One"),
          ("sobha central", "Sobha Central"), ("ivory", "Sobha Ivory")]


def group_of(name):
    n = (name or "").lower()
    return next((g for k, g in GROUPS if k in n), None)


def combined(members, stat, projs):
    """One status line for a group of projects."""
    st = [stat.get(m, ("", False)) for m in members]
    uc = [m for m, (t, b) in zip(members, st) if b]
    done = [m for m, (t, b) in zip(members, st) if not b]
    nb = sum(projs[m][3] for m in members)
    if not uc:
        yrs = [t.split()[-1] for t, b in st if t.split() and t.split()[-1].isdigit()]
        return ("Completed %s" % (max(yrs) if len(set(yrs)) == 1 else "%s-%s" % (min(yrs), max(yrs))) if yrs else "Completed"), False
    if not done:
        if len(members) == 1:
            return st[0][0], True
        off = all(stat.get(m, ("", False))[0].startswith("Off-plan") for m in uc)
        return ("%d towers · %s" % (nb, "off-plan" if off else "under construction") if nb > 1 else st[0][0]), True
    return ("%d of %d complete · %d under construction" % (len(done), len(members), len(uc))), True


def plan_labels(projs, stat, cams):
    groups = {}
    for name in projs:
        groups.setdefault(group_of(name) or name, []).append(name)
    plan = []
    for g, members in sorted(groups.items()):
        anchor = max(members, key=lambda m: projs[m][2])
        x, y, top = projs[anchor][:3]
        if len(members) == 1 and not group_of(members[0]):
            label = pretty(members[0]); status, uc = stat.get(members[0], ("", False))
        else:
            label = g; status, uc = combined(members, stat, projs)
        dmin = min((math.sqrt((cx - x) ** 2 + (cy - y) ** 2 + (cz - top) ** 2) for (_, cx, cy, cz) in cams), default=REF_CM)
        sc = max(0.7, min(6.0, dmin / REF_CM))
        h = TEXT_CM + 2 * PAD_CM + ((GAP_CM + STATUS_CM) if status else 0.0)
        w = max(3000.0, len(label) * TEXT_CM * 0.62, len(status) * STATUS_CM * 0.58) + 2 * PAD_CM
        plan.append({"label": label, "status": status, "uc": uc, "x": x, "y": y, "top": top, "sc": sc, "h": h, "w": w,
                     "z0": top + LINE_M * 100.0 * sc, "members": members})
    # stack: a box whose footprint (its width, turned any way) comes within reach of a lower one is lifted above it
    placed = []
    for L in sorted(plan, key=lambda L: L["z0"]):
        moved = True
        while moved:
            moved = False
            for P in placed:
                reach = 0.55 * (L["w"] * L["sc"] + P["w"] * P["sc"])
                if math.hypot(L["x"] - P["x"], L["y"] - P["y"]) < reach:
                    lo, hi = P["z0"], P["z0"] + P["h"] * P["sc"]
                    if L["z0"] < hi + 200.0 and L["z0"] + L["h"] * L["sc"] > lo - 200.0:
                        L["z0"] = hi + 400.0 * L["sc"]; moved = True
        placed.append(L)
    return plan


def clear_old():
    for a in ell.get_all_level_actors():
        if str(a.get_actor_label() or "").startswith("LBL_"):
            ell.destroy_actor(a)


def camera_keys(seq):
    """[(frame, x, y, z)] from the camera binding's location channels."""
    for b in seq.get_bindings():
        for t in b.get_tracks():
            if not isinstance(t, unreal.MovieScene3DTransformTrack):
                continue
            for s in t.get_sections():
                ch = s.get_all_channels()
                xs = [(k.get_time().frame_number.value, k.get_value()) for k in ch[0].get_keys()]
                ys = [k.get_value() for k in ch[1].get_keys()]
                zs = [k.get_value() for k in ch[2].get_keys()]
                if xs and len(xs) == len(ys) == len(zs):
                    return [(f, x, y, z) for (f, x), y, z in zip(xs, ys, zs)]
    return []


def movable(actor):
    try:
        actor.root_component.set_mobility(MOVABLE)
    except Exception:
        pass


def text(label, loc, words, size, colour):
    tx = ell.spawn_actor_from_class(unreal.TextRenderActor, loc)
    tx.set_actor_label(label); movable(tx)
    tr = tx.text_render
    tr.set_text(words); tr.set_world_size(size); tr.set_text_render_color(colour)
    tr.set_horizontal_alignment(unreal.HorizTextAligment.EHTA_CENTER)
    tr.set_vertical_alignment(unreal.VerticalTextAligment.EVRTA_TEXT_CENTER)
    try:
        tr.set_editor_property("cast_shadow", False)
    except Exception:
        pass
    tx.set_actor_rotation(unreal.Rotator(0, 0, 180), False)      # reads toward -X, the box's front face
    return tx


def main():
    ell.load_level(LEVEL)
    seq = eal.load_asset(SEQ)
    if seq is None:
        raise RuntimeError("%s not found - run ue_sobha_tour.py first" % SEQ)
    clear_old()
    for b in list(seq.get_bindings()):
        if str(b.get_display_name() or "").startswith("LBL_"):
            b.remove()
    cams = camera_keys(seq)
    box_m = unlit("M_SobhaLabelBox", (0.02, 0.05, 0.07))
    gold_m = unlit("M_SobhaLabelLine", GOLD); amber_m = unlit("M_SobhaLabelLineBuilding", AMBER)
    cyl = eal.load_asset("/Engine/BasicShapes/Cylinder"); cube = eal.load_asset("/Engine/BasicShapes/Cube")
    stat = statuses()
    projs = projects()
    end = seq.get_playback_end()
    plan = plan_labels(projs, stat, cams)
    n_uc = 0
    for n, L in enumerate(plan):
        label, status, building, x, y, top, sc, z0, h, w = (L[k] for k in ("label", "status", "uc", "x", "y", "top", "sc", "z0", "h", "w"))
        n_uc += building
        line_cm = z0 - top
        ln = ell.spawn_actor_from_class(unreal.StaticMeshActor, unreal.Vector(x, y, top + line_cm / 2.0))
        ln.set_actor_label("LBL_%02d_line" % n); ln.static_mesh_component.set_static_mesh(cyl)
        ln.set_actor_scale3d(unreal.Vector(0.3 * sc, 0.3 * sc, line_cm / 100.0))
        ln.static_mesh_component.set_material(0, amber_m if building else gold_m)
        ln.static_mesh_component.set_cast_shadow(False)
        piv = ell.spawn_actor_from_class(unreal.StaticMeshActor, unreal.Vector(x, y, z0))
        piv.set_actor_label("LBL_%02d" % n); movable(piv)
        bx = ell.spawn_actor_from_class(unreal.StaticMeshActor, unreal.Vector(x, y, z0 + h / 2.0))
        bx.set_actor_label("LBL_%02d_box" % n); movable(bx); bx.static_mesh_component.set_static_mesh(cube)
        bx.set_actor_scale3d(unreal.Vector(0.4, w / 100.0, h / 100.0)); bx.static_mesh_component.set_material(0, box_m)
        bx.static_mesh_component.set_cast_shadow(False)
        kids = [bx, text("LBL_%02d_text" % n, unreal.Vector(x - 40.0, y, z0 + h - PAD_CM - TEXT_CM / 2.0), label, TEXT_CM, unreal.Color(r=255, g=255, b=255, a=255))]
        if status:
            col = unreal.Color(r=255, g=150, b=60, a=255) if building else unreal.Color(r=215, g=180, b=110, a=255)   # amber / soft gold
            kids.append(text("LBL_%02d_status" % n, unreal.Vector(x - 40.0, y, z0 + PAD_CM + STATUS_CM / 2.0), status, STATUS_CM, col))
        for c in kids:
            c.attach_to_actor(piv, "", unreal.AttachmentRule.KEEP_WORLD, unreal.AttachmentRule.KEEP_WORLD, unreal.AttachmentRule.KEEP_WORLD, False)
        if cams:
            b = seq.add_possessable(piv)
            tt = b.add_track(unreal.MovieScene3DTransformTrack); sec = tt.add_section(); sec.set_range(0, end)
            ch = sec.get_all_channels()
            prev = None
            for (f, cx, cy, cz) in cams:
                yaw = math.degrees(math.atan2(cy - y, cx - x)) + 180.0     # the box front (-X) toward the camera
                if prev is not None:
                    while yaw - prev > 180: yaw -= 360
                    while yaw - prev < -180: yaw += 360
                prev = yaw
                for c, v in zip(ch, [x, y, z0, 0.0, 0.0, yaw, sc, sc, sc]):
                    k = c.add_key(unreal.FrameNumber(int(f)), float(v))
                    try:
                        k.set_interpolation_mode(unreal.RichCurveInterpMode.RCIM_CUBIC)
                    except Exception:
                        pass
        log("  label %-34s %-40s roof %.0f m  x%.1f" % (label, status, top / 100.0, sc))
    eal.save_asset(SEQ)
    eal.save_directory(LBL_DIR, only_if_is_dirty=False, recursive=True)
    ell.save_current_level()
    log("Sobha labels: %d labels for %d projects (%d under construction), %d camera keys followed" % (len(plan), len(projs), n_uc, len(cams)))


if __name__ == "__main__":
    main()
