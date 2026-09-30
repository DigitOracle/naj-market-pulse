"""lab_streets_probe.py -- one-off probe of the CE 2025.1 street-graph API in a throwaway LAB scene.

Creates /najma/scenes/lab_streets_probe.cej (never a production scene), draws one 3-vertex graph polyline in the Business Bay
UTM frame, and prints what CityEngine exposes on segments / lanes / street shapes so lab_streets_build.py can set widths from
the streets.geojson attributes. Holds data/ce/.ce_lock for the whole (short) run. Research only.
Usage: python scripts/lab_streets_probe.py
"""
import json, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lab_streets_ce import ce_lock, log, idle, LAB, jdump

out = {}
with ce_lock("probe"):
    from cityengine import CE
    ce = CE()
    out["version"] = str(ce.getVersionString())
    log("CE", out["version"])
    ce.newFile("/najma/scenes/lab_streets_probe.cej")
    idle(ce)
    out["crs_before"] = str(ce.getSceneCoordSystem())
    try:
        ce.setSceneCoordSystem("EPSG:32640")
    except Exception as e:
        log("setSceneCoordSystem:", str(e)[:120])
    out["crs_after"] = str(ce.getSceneCoordSystem())
    log("crs", out["crs_before"], "->", out["crs_after"])
    L = ce.addGraphLayer("probe")
    x0, z0 = 325931.0, -2786402.0
    segs = ce.createGraphSegments(L, [x0, 0, z0, x0 + 60, 0, z0, x0 + 120, 0, z0 - 40])
    log("segments created", len(segs))
    s = segs[0]
    out["seg_attrs"] = {str(a): str(ce.getAttribute(s, str(a)))[:80] for a in ce.getAttributeList(s)}
    log("segment attrs", json.dumps(out["seg_attrs"])[:1500])
    lanes = ce.getObjectsFrom(s, ce.isLane)
    out["lanes"] = []
    for ln in lanes:
        out["lanes"].append({str(a): str(ce.getAttribute(ln, str(a)))[:60] for a in ce.getAttributeList(ln)})
    log("lanes", json.dumps(out["lanes"])[:1500])
    cfgs = ce.getStreetConfigurations()
    out["street_configs"] = [str(c.getName()) if hasattr(c, "getName") else str(c) for c in (cfgs or [])]
    log("street configurations", out["street_configs"])
    shapes = ce.getObjectsFrom(L, ce.isShape)
    out["n_shapes_layer"] = len(shapes)
    out["shapes"] = [{"name": str(ce.getName(sh)), "start": str(ce.getStartRule(sh)),
                      "attrs": {str(a): str(ce.getAttribute(sh, str(a)))[:60] for a in ce.getAttributeList(sh)}} for sh in shapes[:6]]
    log("shapes in layer", len(shapes), json.dumps(out["shapes"])[:2500])
    out["shapes_under_segment"] = len(ce.getObjectsFrom(s, ce.isShape))
    # try widening through the classic street parameters
    for key, val in (("/ce/street/streetWidth", 14.0), ("/ce/street/sidewalkWidthLeft", 3.0), ("/ce/street/sidewalkWidthRight", 1.0)):
        try:
            ce.setAttribute(s, key, val)
            out["set " + key] = str(ce.getAttribute(s, key))
        except Exception as e:
            out["set " + key] = "ERR " + str(e).splitlines()[0][:120]
    idle(ce)
    out["lanes_after"] = [{str(a): str(ce.getAttribute(ln, str(a)))[:60] for a in ce.getAttributeList(ln)} for ln in ce.getObjectsFrom(s, ce.isLane)]
    out["seg_attrs_after"] = {str(a): str(ce.getAttribute(s, str(a)))[:80] for a in ce.getAttributeList(s)}
    log("after width set", json.dumps({k: v for k, v in out.items() if k.startswith("set ")}))
    log("lanes after", json.dumps(out["lanes_after"])[:1500])
    nodes = ce.getObjectsFrom(L, ce.isGraphNode)
    out["nodes"] = len(nodes)
    out["node_attrs"] = {str(a): str(ce.getAttribute(nodes[0], str(a)))[:60] for a in ce.getAttributeList(nodes[0])} if nodes else {}
    log("nodes", len(nodes), json.dumps(out["node_attrs"])[:800])
    try:
        ce.saveFile("/najma/scenes/lab_streets_probe.cej")
    except Exception as e:
        log("save:", str(e)[:100])
jdump(out, os.path.join(LAB, "probe_api.json"))
log("wrote", os.path.join(LAB, "probe_api.json"))
