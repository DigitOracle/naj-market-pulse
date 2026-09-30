"""lab_streets_probe3.py -- third probe (LAB scene only): lab lane rules + street configuration round trip + node merge +
crossings + generate + glTF export of a 3-segment T junction. Proves the pieces lab_streets_build.py chains together.
Usage: python scripts/lab_streets_probe3.py
"""
import json, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lab_streets_ce import ce_lock, log, idle, LAB, jdump, RULE_WS

LANE_RULES = {"pave": "/ESRI.lib/rules/Streets/Lane/Sidewalk/Sidewalk_Lane.cga",
              "verge": "/najma/rules/lab/streets/Dubai_Verge_Lane.cga",
              "car": "/ESRI.lib/rules/Streets/Lane/Vehicle/Car_Lane.cga"}


def attrs(ce, o, n=70):
    try:
        return {str(a): str(ce.getAttribute(o, str(a)))[:n] for a in ce.getAttributeList(o)}
    except Exception as e:
        return {"ERR": str(e)[:100]}


out = {}
with ce_lock("probe3"):
    from cityengine import CE, CleanupGraphSettings, GLTFExportModelSettings
    ce = CE()
    info = ce.getRuleFileInfo(LANE_RULES["verge"])
    out["verge_rule_info"] = str(info)[:1500]
    log("verge rule info:", str(info)[:400])
    ce.newFile("/najma/scenes/lab_streets_probe3.cej")
    idle(ce)
    ce.setSceneCoordSystem("EPSG:32640")
    T = ce.addGraphLayer("template")
    x0, z0 = 325931.0, -2786402.0
    seg = ce.createGraphSegments(T, [x0, 0, z0 + 300, x0 + 50, 0, z0 + 300])[0]
    plan = [(1.5, CE.SIDEWALK_LEFT, "pave", None), (1.5, CE.SIDEWALK_LEFT, "verge", None),
            (3.5, CE.ROADBED, "car", "Reverse"), (3.5, CE.ROADBED, "car", "Forward"),
            (1.5, CE.SIDEWALK_RIGHT, "verge", None), (1.5, CE.SIDEWALK_RIGHT, "pave", None)]
    for i, (w, hint, kind, d) in enumerate(plan):
        ce.addLane(seg, i, w, hint)
    lanes = ce.getObjectsFrom(seg, ce.isLane)
    log("template lanes", len(lanes))
    for ln, (w, hint, kind, d) in zip(lanes, plan):
        ce.setRuleFile(ln, LANE_RULES[kind])
        ce.setStartRule(ln, "Start")
        if d:
            try:
                ce.setAttribute(ln, "/ce/street/lane/travelDirection", d)
            except Exception as e:
                out.setdefault("dir_err", []).append(str(e)[:120])
    idle(ce)
    out["template_lanes"] = [attrs(ce, ln) for ln in ce.getObjectsFrom(seg, ce.isLane)]
    cfg = ce.createStreetConfiguration(seg)
    out["cfg_methods"] = [m for m in dir(cfg) if not m.startswith("_")][:60]
    try:
        cfg.setName("lab_probe_cfg")
    except Exception as e:
        out["cfg_setName"] = str(e)[:120]
    out["cfg_name"] = str(cfg.getName()) if hasattr(cfg, "getName") else str(cfg)
    log("config", out["cfg_name"], out["cfg_methods"])
    G = ce.addGraphLayer("net")
    a = ce.createGraphSegments(G, [x0, 0, z0, x0 + 80, 0, z0], cfg)
    b = ce.createGraphSegments(G, [x0 + 80, 0, z0, x0 + 160, 0, z0 - 10], cfg)
    c = ce.createGraphSegments(G, [x0 + 80, 0, z0, x0 + 80, 0, z0 - 90], cfg)
    idle(ce)
    out["new_seg_lanes"] = [attrs(ce, ln) for ln in ce.getObjectsFrom(a[0], ce.isLane)]
    out["n_nodes_before"] = len(ce.getObjectsFrom(G, ce.isGraphNode))
    cs = CleanupGraphSettings()
    cs.setIntersectSegments(False); cs.setMergeNodes(True); cs.setMergingDist(0.5)
    cs.setSnapNodesToSegments(False); cs.setResolveConflictShapes(False)
    t0 = time.time(); ce.cleanupGraph([G], cs); out["cleanup_s"] = round(time.time() - t0, 2)
    idle(ce)
    segs = ce.getObjectsFrom(G, ce.isGraphSegment)
    nodes = ce.getObjectsFrom(G, ce.isGraphNode)
    out["after_cleanup"] = {"segments": len(segs), "nodes": len(nodes), "valency": [str(ce.getAttribute(n, "valency")) for n in nodes],
                            "conn": [(str(ce.getAttribute(s, "connectionStart")), str(ce.getAttribute(s, "connectionEnd"))) for s in segs]}
    log("after cleanup", out["after_cleanup"])
    shapes = ce.getObjectsFrom(G, ce.isShape)
    out["n_shapes"] = len(shapes)
    out["shape_kinds"] = {}
    for s in shapes:
        k = "%s|%s|%s" % (ce.getName(s), ce.getRuleFile(s), ce.getStartRule(s))
        out["shape_kinds"][k] = out["shape_kinds"].get(k, 0) + 1
    log("shapes", len(shapes), out["shape_kinds"])
    node_shapes = [s for s in shapes if str(ce.getName(s)) != "Lane"]
    out["node_shape_attrs"] = [attrs(ce, s) for s in node_shapes[:2]]
    # crossings: every lane of a segment whose end is a junction
    for s in segs:
        st, en = str(ce.getAttribute(s, "connectionStart")), str(ce.getAttribute(s, "connectionEnd"))
        js, je = st not in ("DEAD_END", "STREET", "None"), en not in ("DEAD_END", "STREET", "None")
        pos = "Both" if js and je else ("Start" if js else ("End" if je else "None"))
        lns = ce.getObjectsFrom(s, ce.isLane)
        ce.setAttribute(lns, "/ce/rule/Crossing_Position", pos)
        ce.setAttributeSource(lns, "/ce/rule/Crossing_Position", "USER")
    # latency
    t0 = time.time()
    for _ in range(100):
        ce.getAttribute(segs[0], "connectionStart")
    out["bridge_ms_per_call"] = round((time.time() - t0) * 10, 2)
    t0 = time.time(); ce.generateModels(shapes); out["generate_s"] = round(time.time() - t0, 2)
    idle(ce)
    s = GLTFExportModelSettings()
    s.setOutputPath(LAB); s.setBaseName("probe3_streets"); s.setMeshGranularity(GLTFExportModelSettings.INSTANCED)
    s.setOutputFormat(GLTFExportModelSettings.GLTF_GLB_WITH_SINGLE_BUFFER); s.setIncludeMaterials(True); s.setWriteLog(True)
    s.setExistingFiles(GLTFExportModelSettings.OVERWRITE)
    try:
        s.setGlobalOffset([-x0, 0.0, -z0])
    except Exception as e:
        out["offset_err"] = str(e)[:120]
    try:
        s.setTerrainLayers(GLTFExportModelSettings.TERRAIN_NONE)
    except Exception:
        pass
    t0 = time.time(); ce.export(shapes, s); out["export_s"] = round(time.time() - t0, 2)
    try:
        v = ce.get3DViews()[0]; ce.setSelection([]); v.frame(shapes); idle(ce)
        v.snapshot(os.path.join(LAB, "probe3_snapshot.png"), 1400, 900)
    except Exception as e:
        out["snap_err"] = str(e)[:150]
    ce.saveFile("/najma/scenes/lab_streets_probe3.cej")
jdump(out, os.path.join(LAB, "probe3_api.json"))
print(json.dumps({k: v for k, v in out.items() if k not in ("template_lanes", "new_seg_lanes")}, indent=1)[:6000])
print(json.dumps(out.get("new_seg_lanes"), indent=0)[:3000])
