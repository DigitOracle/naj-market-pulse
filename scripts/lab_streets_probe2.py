"""lab_streets_probe2.py -- second API probe (LAB scene only): how CE 2025.1 lanes turn into street shapes.

A: segment + built-in configuration 'Road_Generic_2VL_10m'; B: bare segment + addLane(sidewalk | roadbed | sidewalk);
C: a T junction so a node shape appears. Dumps lanes, shapes, start rules and rule files to data/lab/streets/probe2_api.json.
Usage: python scripts/lab_streets_probe2.py
"""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lab_streets_ce import ce_lock, log, idle, LAB, jdump


def attrs(ce, o, n=70):
    try:
        return {str(a): str(ce.getAttribute(o, str(a)))[:n] for a in ce.getAttributeList(o)}
    except Exception as e:
        return {"ERR": str(e)[:100]}


out = {}
with ce_lock("probe2"):
    from cityengine import CE
    ce = CE()
    ce.newFile("/najma/scenes/lab_streets_probe2.cej")
    idle(ce)
    ce.setSceneCoordSystem("EPSG:32640")
    L = ce.addGraphLayer("probe2")
    x0, z0 = 325931.0, -2786402.0
    cfgs = {str(c.getName()).strip(): c for c in ce.getStreetConfigurations()}
    # A
    sa = ce.createGraphSegments(L, [x0, 0, z0, x0 + 80, 0, z0], cfgs["Road_Generic_2VL_10m"])
    idle(ce)
    out["A_seg"] = attrs(ce, sa[0])
    out["A_lanes"] = [attrs(ce, ln) for ln in ce.getObjectsFrom(sa[0], ce.isLane)]
    # B
    sb = ce.createGraphSegments(L, [x0, 0, z0 - 100, x0 + 80, 0, z0 - 100])
    b = sb[0]
    for i, (w, hint) in enumerate(((3.0, CE.SIDEWALK_LEFT), (7.0, CE.ROADBED), (2.0, CE.SIDEWALK_RIGHT))):
        try:
            ce.addLane(b, i, w, hint)
        except Exception as e:
            out.setdefault("B_err", []).append(str(e).splitlines()[0][:160])
    idle(ce)
    out["B_seg"] = attrs(ce, b)
    out["B_lanes"] = [attrs(ce, ln) for ln in ce.getObjectsFrom(b, ce.isLane)]
    # C: T junction off segment B's midpoint region
    sc = ce.createGraphSegments(L, [x0 + 40, 0, z0 - 100, x0 + 40, 0, z0 - 160], cfgs["Road_Generic_2VL_10m"])
    idle(ce)
    out["C_seg"] = attrs(ce, sc[0])
    shapes = ce.getObjectsFrom(L, ce.isShape)
    out["n_shapes"] = len(shapes)
    out["shapes"] = [{"name": str(ce.getName(s)), "start": str(ce.getStartRule(s)), "rule": str(ce.getRuleFile(s)),
                      "attrs": attrs(ce, s, 50)} for s in shapes]
    out["segments"] = len(ce.getObjectsFrom(L, ce.isGraphSegment))
    out["nodes"] = [attrs(ce, n) for n in ce.getObjectsFrom(L, ce.isGraphNode)]
    out["shapes_under_B"] = [str(ce.getName(s)) for s in ce.getObjectsFrom(b, ce.isShape)]
    out["lane_shapes_B"] = [[str(ce.getName(s)) for s in ce.getObjectsFrom(ln, ce.isShape)] for ln in ce.getObjectsFrom(b, ce.isLane)]
    # classic width parameters on B
    for key, val in (("/ce/street/streetWidth", 10.5), ("/ce/street/sidewalkWidthLeft", 2.5)):
        try:
            ce.setAttribute(b, key, val)
        except Exception as e:
            out["setB " + key] = "ERR " + str(e)[:100]
    idle(ce)
    out["B_seg_after"] = attrs(ce, b)
    out["B_lanes_after"] = [attrs(ce, ln) for ln in ce.getObjectsFrom(b, ce.isLane)]
    ce.saveFile("/najma/scenes/lab_streets_probe2.cej")
jdump(out, os.path.join(LAB, "probe2_api.json"))
print(json.dumps(out, indent=1)[:9000])
