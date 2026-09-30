"""lab_streets_build.py -- LAB technique #3: a district's streets built as a CityEngine 2025.1 street graph with Dubai lanes
(right-hand traffic, zebra crossings at junctions, kerbside verges with date palms and lamps), exported as a streets-only glTF.

Research only. Never pushes, deploys or uploads; never opens or saves a production scene - everything happens in
/najma/scenes/lab_streets_<slug>.cej. Every CE step holds data/ce/.ce_lock (lab_streets_ce.ce_lock, released in finally)
and long passes are chunked so the lock is released between chunks.

Steps (run in order; `all` chains them):
  prep       python scripts/lab_streets_prep.py <slug>            (offline: UTM polylines, lane plans, source audit)
  graph      new lab scene, EPSG:32640, one street configuration per lane plan (built from a template segment with the
             lab lane rules), one createGraphSegments call per OSM way, cleanupGraph (merge nodes 0.5 m, snap 1.0 m,
             no intersect), node shapes -> ESRI Default_Node.cga, save
  lanes      per segment: travel direction per car lane (right-hand), zebra/kerb crossings on every lane at CROSSING /
             ROUNDABOUT ends when the segment has pavements and is long enough (chunked; lock released between chunks)
  generate   generate every street shape, export GLB (INSTANCED, global offset = the v5 building tile origin), snapshots
             (overview + hero junction, with grey context massing imported AFTER the export)
  verify     offline GLB audit -> data/lab/streets/<slug>/streets_verify.json

Usage: python scripts/lab_streets_build.py businessbay all | graph | lanes | generate | verify   [--via-api]

STATE (30 Sep 2026, Business Bay): prep + configs + graph import MEASURED; the full-district cleanupGraph ran >26 min and
the CE Python bridge stopped answering during it, so lanes / generate / verify have only been proven on the 3-segment
probe (scripts/lab_streets_probe3.py). Graph builder: default --via shp (bulk SHP import, 13 min for 5,482 segments);
--via-api (one createGraphSegments per way) measured 1.1-1.6 s per way and rising. Before running a whole district
again: tile it (~1 km cells, one lab scene each) or pre-merge topology offline so cleanupGraph has nothing to do.
"""
import collections, json, math, os, re, struct, subprocess, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lab_streets_ce import CEDIR, LAB, HERE, log, idle, jdump, ce_lock, dump_log

_pos = [a for a in sys.argv[1:] if not a.startswith("--")]
SLUG = _pos[0] if _pos else "businessbay"
STEP = _pos[1] if len(_pos) > 1 else "all"
VIA = "api" if "--via-api" in sys.argv else "shp"            # graph builder: bulk SHP import (default) or per-way API
OUT = os.path.join(LAB, SLUG); os.makedirs(OUT, exist_ok=True)
SCENE = f"/najma/scenes/lab_streets_{SLUG}.cej"
LAYER = f"streets_{SLUG}"
RULES = {"pave": "/ESRI.lib/rules/Streets/Lane/Sidewalk/Sidewalk_Lane.cga",
         "verge": "/najma/rules/lab/streets/Dubai_Verge_Lane.cga",
         "car": "/ESRI.lib/rules/Streets/Lane/Vehicle/Car_Lane.cga"}
NODE_RULE = "/ESRI.lib/rules/Streets/Node/Default_Node.cga"
CONTEXT_RULE = "/najma/rules/lab/streets/context_mass.cga"
CROSS_AT = {"CROSSING", "ROUNDABOUT"}
CHUNK = 1200                                     # segments per lock hold in the lanes pass
STATE = os.path.join(OUT, "build_state.json")


def state():
    return json.load(open(STATE, encoding="utf-8")) if os.path.exists(STATE) else {}


def save_state(st):
    jdump(st, STATE)


def origin():
    p = os.path.join(CEDIR, SLUG, "origin_v5.json")
    if os.path.exists(p):
        o = json.load(open(p, encoding="utf-8"))["origin_ce_xyz"]
        return [float(o[0]), float(o[1]), float(o[2])], os.path.relpath(p, os.path.dirname(CEDIR))
    prep = json.load(open(os.path.join(OUT, "prep.json"), encoding="utf-8"))
    xs = [f["verts"][0] for f in prep["features"]]; zs = [f["verts"][2] for f in prep["features"]]
    return [round(sum(xs) / len(xs)), 0.0, round(sum(zs) / len(zs))], "street centroid"


def my_scene_open(ce):
    try:
        return bool(ce.getObjectsFrom(ce.scene, ce.isGraphLayer, ce.withName("'%s'" % LAYER)))
    except Exception:
        return False


def ensure_scene(ce):
    if not my_scene_open(ce):
        log("  opening", SCENE)
        ce.openFile(SCENE); idle(ce, 3)
    L = ce.getObjectsFrom(ce.scene, ce.isGraphLayer, ce.withName("'%s'" % LAYER))
    if not L:
        raise SystemExit("lab scene has no layer %s - run the graph step" % LAYER)
    return L[0]


def write_cfg_shps(prep):
    """One EPSG:32640 polyline SHP per lane plan under <OUT>/shp/cfgNN.shp (scene frame back to easting/northing)."""
    import geopandas as gpd
    from shapely.geometry import LineString
    d = os.path.join(OUT, "shp"); os.makedirs(d, exist_ok=True)
    rows = []
    for f in prep["features"]:
        v = f["verts"]
        rows.append({"cfg": f["cfg"], "osm_id": str(f["osm_id"]), "hw": f["hw"],
                     "geometry": LineString([(v[i], -v[i + 2]) for i in range(0, len(v), 3)])})
    g = gpd.GeoDataFrame(rows, crs="EPSG:32640")
    idx = {}
    for k, key in enumerate(sorted(g.cfg.unique())):
        sub = g[g.cfg == key]
        sub.to_file(os.path.join(d, "cfg%02d.shp" % k)); idx["cfg%02d" % k] = {"cfg": key, "ways": int(len(sub))}
    jdump(idx, os.path.join(d, "index.json"))
    return idx


# ---------------------------------------------------------------------------------------------------------------- graph
def step_graph():
    prep = json.load(open(os.path.join(OUT, "prep.json"), encoding="utf-8"))
    feats, plans = prep["features"], prep["plans"]
    st = {"slug": SLUG, "scene": SCENE}
    T = {}
    with ce_lock("graph %s" % SLUG):
        from cityengine import CE, CleanupGraphSettings
        ce = CE()
        t0 = time.time()
        fs = ce.toFSPath(SCENE)
        if my_scene_open(ce):                      # our own half-built lab scene is open: save it so newFile has no
            ce.saveFile(SCENE); idle(ce)           # unsaved-changes prompt to block on, then rebuild from scratch
            try: ce.closeFile(SCENE)
            except Exception as e: log("  closeFile:", str(e)[:80])
        if os.path.exists(fs):                     # a rerun rebuilds OUR lab scene from scratch (never a production scene)
            os.remove(fs)
            try: ce.refreshWorkspace()
            except Exception: pass
        ce.newFile(SCENE); idle(ce)
        ce.setSceneCoordSystem("EPSG:32640")
        st["crs"] = [str(x) for x in ce.getSceneCoordSystem()]
        # 1. one template segment per lane plan -> street configuration
        tl = ce.addGraphLayer("lab_templates")
        x0 = min(f["verts"][0] for f in feats) - 1500.0; z0 = min(f["verts"][2] for f in feats)
        hint = {"L": CE.SIDEWALK_LEFT, "R": CE.SIDEWALK_RIGHT, None: CE.ROADBED}
        tmpl, by_kind, dirs = {}, collections.defaultdict(list), collections.defaultdict(list)
        for k, (key, plan) in enumerate(sorted(plans.items())):
            seg = ce.createGraphSegments(tl, [x0, 0, z0 + 40 * k, x0 + 60, 0, z0 + 40 * k])[0]
            for i, (kind, w, side, trav) in enumerate(plan):
                ce.addLane(seg, i, float(w), hint[side])
            lanes = ce.getObjectsFrom(seg, ce.isLane)
            if len(lanes) != len(plan):
                raise SystemExit("template %s: %d lanes for a %d-lane plan" % (key, len(lanes), len(plan)))
            for ln, (kind, w, side, trav) in zip(lanes, plan):
                by_kind[kind].append(ln)
                if trav: dirs[trav].append(ln)
            tmpl[key] = seg
        for kind, lst in by_kind.items():
            ce.setRuleFile(lst, RULES[kind]); ce.setStartRule(lst, "Start")
        for d, lst in dirs.items():
            ce.setAttribute(lst, "/ce/street/lane/travelDirection", d)
        idle(ce)
        cfgs = {}
        for key, seg in tmpl.items():
            c = ce.createStreetConfiguration(seg)
            try: c.setName(key)
            except Exception: pass
            cfgs[key] = c
        ce.delete([tl]); idle(ce)
        T["configs_s"] = round(time.time() - t0, 1); log(f"  {len(cfgs)} street configurations in {T['configs_s']} s")
        # 2. the street graph
        t0 = time.time()
        created = 0
        if VIA == "shp":
            # bulk: one SHP import per lane plan (written by write_cfg_shps), then ONE applyStreetConfigurationToSegment
            # per plan, then merge the 29 graph layers into one. Per-way createGraphSegments measured ~1.1 s/way and
            # rising on Business Bay (every call re-derives street shapes around the growing graph).
            idx = write_cfg_shps(prep)
            layers = []
            for tag, meta in sorted(idx.items()):
                new = ce.importFile(os.path.join(OUT, "shp", tag + ".shp"))
                gl = [x for x in (new or []) if ce.isGraphLayer(x)]
                segs = [s for x in gl for s in ce.getObjectsFrom(x, ce.isGraphSegment)]
                if segs:
                    ce.applyStreetConfigurationToSegment(segs, cfgs[meta["cfg"]])
                created += len(segs); layers += gl
            idle(ce)
            merged = ce.mergeLayers(layers) if len(layers) > 1 else layers
            L = [x for x in (merged or layers) if ce.isGraphLayer(x)][0]
            ce.setName(L, LAYER)
            log(f"    imported {len(layers)} SHP layers, {created} segments, merged into {LAYER}")
        else:
            # per way: one createGraphSegments call per OSM way with its configuration
            L = ce.addGraphLayer(LAYER)
            for n, f in enumerate(feats):
                segs = ce.createGraphSegments(L, f["verts"], cfgs[f["cfg"]])
                created += len(segs)
                if n % 300 == 0: log(f"    {n}/{len(feats)} ways, {created} segments ({time.time() - t0:.0f} s)")
        st["via"] = VIA
        idle(ce)
        T["create_s"] = round(time.time() - t0, 1)
        st["ways"] = len(feats); st["segments_created"] = created
        st["nodes_before_cleanup"] = len(ce.getObjectsFrom(L, ce.isGraphNode))
        log(f"  created {created} segments / {st['nodes_before_cleanup']} nodes from {len(feats)} ways in {T['create_s']} s")
        # 3. cleanup: OSM junctions already share vertices -> merge coincident nodes; snap the <1 m near-misses;
        #    NO intersect (it would weld grade-separated crossings into false junctions)
        cs = CleanupGraphSettings()
        cs.setIntersectSegments(False); cs.setMergeNodes(True); cs.setMergingDist(0.5)
        cs.setSnapNodesToSegments(True); cs.setSnappingDist(1.0); cs.setResolveConflictShapes(False)
        t0 = time.time(); ce.cleanupGraph([L], cs); idle(ce, 5)
        T["cleanup_s"] = round(time.time() - t0, 1)
        segs = ce.getObjectsFrom(L, ce.isGraphSegment); nodes = ce.getObjectsFrom(L, ce.isGraphNode)
        st["segments_after_cleanup"] = len(segs); st["nodes_after_cleanup"] = len(nodes)
        log(f"  cleanup {T['cleanup_s']} s -> {len(segs)} segments / {len(nodes)} nodes")
        # 4. node shapes (junction surfaces + kerb corners) -> Default_Node
        t0 = time.time()
        node_shapes = ce.getObjectsFrom(L, ce.isShape, ce.withName("'Shape'"))
        if node_shapes:
            ce.setRuleFile(node_shapes, NODE_RULE); ce.setStartRule(node_shapes, "Start")
        st["node_shapes"] = len(node_shapes)
        st["shapes_total"] = len(ce.getObjectsFrom(L, ce.isShape))
        T["node_rules_s"] = round(time.time() - t0, 1)
        log(f"  {len(node_shapes)} node shapes -> Default_Node; {st['shapes_total']} street shapes in all")
        ce.saveFile(SCENE)
    st["timings_s"] = T
    st["lanes_done_upto"] = 0
    save_state(st)


# ---------------------------------------------------------------------------------------------------------------- lanes
def step_lanes():
    st = state()
    prep = json.load(open(os.path.join(OUT, "prep.json"), encoding="utf-8"))
    plans = prep["plans"]
    conn_hist = collections.Counter(st.get("connections", {}))
    stats = collections.Counter(st.get("lane_stats", {}))
    t_all = time.time()
    while True:
        done = st.get("lanes_done_upto", 0)
        with ce_lock("lanes %s @%d" % (SLUG, done)):
            from cityengine import CE
            ce = CE()
            L = ensure_scene(ce)
            segs = ce.getObjectsFrom(L, ce.isGraphSegment)
            total = len(segs)
            if done >= total:
                break
            chunk = segs[done:done + CHUNK]
            dirs = collections.defaultdict(list); cross = collections.defaultdict(list)
            for s in chunk:
                lanes = ce.getObjectsFrom(s, ce.isLane)
                cfg = ce.getStreetConfiguration(s)
                key = str(cfg.getName()) if cfg is not None else ""
                plan = plans.get(key)
                if not plan or len(plan) != len(lanes):
                    stats["segments_without_plan"] += 1
                    continue
                for ln, (kind, w, side, trav) in zip(lanes, plan):
                    if trav: dirs[trav].append(ln)
                a, b = str(ce.getAttribute(s, "connectionStart")), str(ce.getAttribute(s, "connectionEnd"))
                conn_hist[a] += 1; conn_hist[b] += 1
                has_walk = any(k in ("pave", "verge") for k, *_ in plan)
                js, je = a in CROSS_AT, b in CROSS_AT
                if has_walk and (js or je):
                    v = ce.getVertices(s)
                    ln_m = sum(math.dist((v[i], v[i + 2]), (v[i + 3], v[i + 5])) for i in range(0, len(v) - 3, 3))
                    if js and je and ln_m < 20: js = je = False; stats["crossings_skipped_short"] += 1
                    elif ln_m < 12: js = je = False; stats["crossings_skipped_short"] += 1
                    pos = "Both" if js and je else ("Start" if js else ("End" if je else None))
                    if pos:
                        cross[pos].extend(lanes)
                        stats["segment_ends_with_crossing"] += 2 if pos == "Both" else 1
                        stats["zebras"] += (2 if pos == "Both" else 1)
            for d, lst in dirs.items():
                ce.setAttribute(lst, "/ce/street/lane/travelDirection", d); stats["car_lanes_" + d] += len(lst)
            for pos, lst in cross.items():
                ce.setAttribute(lst, "/ce/rule/Crossing_Position", pos)
                ce.setAttributeSource(lst, "/ce/rule/Crossing_Position", "USER")
            idle(ce)
            ce.saveFile(SCENE)
            st["lanes_done_upto"] = done + len(chunk); st["segments_total"] = total
            st["connections"] = dict(conn_hist); st["lane_stats"] = dict(stats)
            save_state(st)
            log(f"  lanes pass {st['lanes_done_upto']}/{total} segments; crossings so far {stats['zebras']}")
        time.sleep(3)                                  # lock released between chunks - a waiting RPK compile gets in here
    st.setdefault("timings_s", {})["lanes_s"] = round(time.time() - t_all, 1)
    save_state(st)


# ------------------------------------------------------------------------------------------------------------- generate
def step_generate():
    st = state()
    org, org_src = origin()
    base = f"lab_streets_{SLUG}"
    for fn in os.listdir(OUT):
        if fn.startswith(base) and (fn.endswith(".glb") or fn.endswith(".log")):
            os.remove(os.path.join(OUT, fn))
    prep = json.load(open(os.path.join(OUT, "prep.json"), encoding="utf-8"))
    with ce_lock("generate %s" % SLUG):
        from cityengine import CE, GLTFExportModelSettings, SHPImportSettings
        ce = CE()
        L = ensure_scene(ce)
        shapes = ce.getObjectsFrom(L, ce.isShape)
        t0 = time.time(); ce.generateModels(shapes); idle(ce, 5)
        st["generate_s"] = round(time.time() - t0, 1); log(f"  generated {len(shapes)} street shapes in {st['generate_s']} s")
        s = GLTFExportModelSettings()
        s.setOutputPath(OUT); s.setBaseName(base)
        s.setMeshGranularity(GLTFExportModelSettings.INSTANCED)
        s.setOutputFormat(GLTFExportModelSettings.GLTF_GLB_WITH_SINGLE_BUFFER)
        s.setIncludeMaterials(True); s.setWriteLog(True); s.setExistingFiles(GLTFExportModelSettings.OVERWRITE)
        s.setGlobalOffset([-org[0], -org[1], -org[2]])            # exported = scene - origin  ->  scene = exported + origin
        try: s.setTerrainLayers(GLTFExportModelSettings.TERRAIN_NONE)
        except Exception: pass
        t0 = time.time(); ce.export(shapes, s); time.sleep(2)
        st["export_s"] = round(time.time() - t0, 1); log(f"  exported in {st['export_s']} s")
        st["export"] = {"base": base, "origin_ce_xyz": org, "origin_source": org_src,
                        "contract": "scene/CE-frame metres (x = easting, y = up, z = -northing, EPSG:32640) = vertex + origin_ce_xyz"}
        save_state(st)
        # snapshots: overview of the streets alone, then grey context massing + hero junction
        try:
            v = ce.get3DViews()[0]; ce.setSelection([])
            v.frame(shapes); idle(ce, 3)
            v.snapshot(os.path.join(OUT, "snap_overview_streets.png"), 1600, 1000)
            lay = ce.importFile(os.path.join(CEDIR, SLUG, "buildings.shp"))
            idle(ce, 3)
            bl = ce.getObjectsFrom(ce.scene, ce.isShapeLayer)
            bshapes = [x for lyr in bl for x in ce.getObjectsFrom(lyr, ce.isShape)]
            ce.setRuleFile(bshapes, CONTEXT_RULE); ce.setStartRule(bshapes, "Lot")
            try: ce.setAttributeSource(bshapes, "/ce/rule/bHeight", "OBJECT")
            except Exception as e: log("  bHeight source:", str(e)[:80])
            ce.generateModels(bshapes); idle(ce, 3)
            st["context_buildings"] = len(bshapes)
            v.frame(shapes); idle(ce, 3)
            v.snapshot(os.path.join(OUT, "snap_overview_with_context.png"), 1600, 1000)
            hx, hz = hero_point(prep)
            v.setCameraPerspective(True, False)
            v.setCameraPoI([hx, 0.0, hz]); v.setPoIDistance(260.0)
            v.setCameraRotation(-32.0, 35.0, 0.0); idle(ce, 3)
            v.snapshot(os.path.join(OUT, "snap_hero_junction.png"), 1600, 1000)
            v.setPoIDistance(90.0); v.setCameraRotation(-22.0, 125.0, 0.0); idle(ce, 3)
            v.snapshot(os.path.join(OUT, "snap_hero_close.png"), 1600, 1000)
            st["hero_point_scene"] = [hx, 0.0, hz]
        except Exception as e:
            st["snapshot_error"] = str(e)[:200]; log("  snapshot:", str(e)[:200])
        # the context massing is NOT saved into the lab scene's street layer and never exported
        save_state(st)


def hero_point(prep):
    """Busiest at-grade junction: the scene vertex shared by the most surface ways, nearest the street centroid."""
    c = collections.Counter()
    for f in prep["features"]:
        if f["net"] != "surface": continue
        v = f["verts"]
        for i in range(0, len(v), 3):
            c[(round(v[i], 1), round(v[i + 2], 1))] += 1
    xs = [f["verts"][0] for f in prep["features"]]; zs = [f["verts"][2] for f in prep["features"]]
    cx, cz = sum(xs) / len(xs), sum(zs) / len(zs)
    best = max(c.items(), key=lambda kv: (kv[1], -math.hypot(kv[0][0] - cx, kv[0][1] - cz)))
    return best[0]


# --------------------------------------------------------------------------------------------------------------- verify
def glb_json(path):
    b = open(path, "rb").read()
    ln = struct.unpack("<I", b[12:16])[0]
    return json.loads(b[20:20 + ln]), len(b)


def step_verify():
    st = state()
    base = st.get("export", {}).get("base", f"lab_streets_{SLUG}")
    parts = sorted(fn for fn in os.listdir(OUT) if fn.startswith(base) and fn.endswith(".glb"))
    rep = {"slug": SLUG, "parts": parts, "bytes": 0, "meshes": 0, "nodes": 0, "mesh_nodes": 0, "unique_triangles": 0,
           "rendered_triangles": 0, "materials": 0, "images": 0, "image_bytes": 0, "instances": collections.Counter(),
           "extensions": set()}
    mins = [1e18] * 3; maxs = [-1e18] * 3
    for fn in parts:
        g, nb = glb_json(os.path.join(OUT, fn))
        rep["bytes"] += nb; rep["meshes"] += len(g.get("meshes", [])); rep["nodes"] += len(g.get("nodes", []))
        rep["materials"] += len(g.get("materials", [])); rep["images"] += len(g.get("images", []))
        rep["image_bytes"] += sum(g["bufferViews"][im["bufferView"]]["byteLength"] for im in g.get("images", []) if "bufferView" in im)
        rep["extensions"] |= set(g.get("extensionsUsed", []))
        mtris = []; seen = set()
        for m in g.get("meshes", []):
            t = 0
            for pr in m["primitives"]:
                a = g["accessors"][pr["attributes"]["POSITION"]]
                pt = g["accessors"][pr["indices"]]["count"] // 3 if "indices" in pr else a["count"] // 3
                t += pt
                # CE's INSTANCED writer emits one mesh OBJECT per instance, all pointing at the same accessors:
                # count stored triangles once per (POSITION, indices) pair
                k = (pr["attributes"]["POSITION"], pr.get("indices"))
                if k not in seen:
                    seen.add(k); rep["unique_triangles"] += pt
                mins = [min(x, y) for x, y in zip(mins, a["min"])]; maxs = [max(x, y) for x, y in zip(maxs, a["max"])]
            mtris.append(t)
        for nd in g.get("nodes", []):
            if "mesh" in nd:
                rep["mesh_nodes"] += 1
                rep["rendered_triangles"] += mtris[nd["mesh"]]
                rep["instances"][g["meshes"][nd["mesh"]].get("name", "?")] += 1
    rep["mb"] = round(rep["bytes"] / 1048576, 2); rep["image_mb"] = round(rep["image_bytes"] / 1048576, 2)
    rep["extensions"] = sorted(rep["extensions"])
    inst = rep.pop("instances")
    rep["instanced_meshes"] = {k: v for k, v in inst.most_common() if v > 1}
    rep["palms"] = inst.get("Trunk", 0)
    rep["lamps"] = sum(v for k, v in inst.items() if "light" in k.lower())
    org = st.get("export", {}).get("origin_ce_xyz", [0, 0, 0])
    rep["bbox_local_mesh_space"] = [mins, maxs]
    # the export log's instance table (CE's own count, not our reading of the file)
    logs = [fn for fn in os.listdir(OUT) if fn.startswith(base) and fn.endswith(".log")]
    if logs:
        txt = open(os.path.join(OUT, logs[0]), encoding="utf-8", errors="replace").read()
        m = re.search(r"Total Polygons:\s*(\d+)", txt); rep["ce_log_total_polygons"] = int(m.group(1)) if m else None
        occ = {}
        for mm in re.finditer(r"^\s*\d+\s+'([^']+)'\s+(\d+)\s+'", txt, re.M):
            occ[mm.group(1)] = occ.get(mm.group(1), 0) + int(mm.group(2))
        rep["ce_log_instance_occurrences"] = {k: v for k, v in sorted(occ.items(), key=lambda kv: -kv[1]) if v > 1}
        ok = len(re.findall(r":\s*OK\b", txt)); bad = len(re.findall(r":\s*(?:FAILED|ERROR|WARNING)\b", txt))
        rep["ce_log_shapes_ok"] = ok; rep["ce_log_shapes_not_ok"] = bad
    # does it sit on the building tile? compare with the v5 building tile's origin + footprint extent
    bfe = json.load(open(os.path.join(CEDIR, SLUG, "buildings.geojson"), encoding="utf-8"))["features"]
    from pyproj import Transformer
    tr = Transformer.from_crs("EPSG:4326", "EPSG:32640", always_xy=True)
    bx, bz = [], []
    for f in bfe:
        gg = f["geometry"]; ring = gg["coordinates"][0] if gg["type"] == "Polygon" else gg["coordinates"][0][0]
        for x, y in ring:
            e, n = tr.transform(x, y); bx.append(e - org[0]); bz.append(-n - org[2])
    rep["buildings_bbox_local"] = [[min(bx), min(bz)], [max(bx), max(bz)]]
    rep["origin_ce_xyz"] = org; rep["origin_source"] = st.get("export", {}).get("origin_source")
    rep["build_state"] = {k: v for k, v in st.items() if k not in ("export",)}
    jdump(rep, os.path.join(OUT, "streets_verify.json"))
    log(json.dumps({k: v for k, v in rep.items() if k != "build_state"}, indent=1)[:4000])


def main():
    t0 = time.time()
    steps = ["prep", "graph", "lanes", "generate", "verify"] if STEP == "all" else [STEP]
    for s in steps:
        log(f"=== {SLUG}: {s}")
        if s == "prep":
            subprocess.run([sys.executable, os.path.join(HERE, "lab_streets_prep.py"), SLUG], check=True)
        else:
            globals()["step_" + s]()
    log(f"done {steps} in {time.time() - t0:.0f} s")
    dump_log(os.path.join(OUT, "build.log"))


if __name__ == "__main__":
    main()
