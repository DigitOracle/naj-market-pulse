"""CityEngine export-callback script — collects the najma_v2.cga reports per building.

Runs INSIDE CityEngine (staged by ce_batch_v2.py to /najma/scripts/ce_report_v2.py and passed to
GLTFExportModelSettings.setScript / ScriptExportModelSettings.setScript). CityEngine calls
initExport / finishModel / finishExport; Model.getReports() is only available in finishModel.

Target file comes from /najma/scripts/ce_report_v2_target.json  {"csv": "...", "json": "..."} which
ce_batch_v2.py writes before each export (the callback has no other channel to the caller).

CSV columns: shape, class, variant, footprint_m2, height_m, storeys, storeys_est, gfa_m2, reports_json
"""
from scripting import *
import json, os

ce = CE()
_ROWS = []
_ERR = []


def _target():
    p = ce.toFSPath("/najma/scripts/ce_report_v2_target.json")
    try:
        with open(p, "r") as f:
            return json.load(f)
    except Exception as e:
        _ERR.append("target file: %s" % e)
        return {"csv": ce.toFSPath("/najma/scripts/report_v2_fallback.csv")}


def _num(v):
    try:
        return float(v)
    except Exception:
        return 0.0


def initExport(exportContextOID):
    del _ROWS[:]
    del _ERR[:]


def finishModel(exportContextOID, shapeOID, modelOID):
    try:
        shape = Shape(shapeOID)
        model = Model(modelOID)
        rep = model.getReports() or {}
        try:
            name = ce.getName(shape)
        except Exception:
            name = shape.getName()
        cls = ""
        for k in rep:
            if str(k).startswith("Class."):
                cls = str(k)[6:]
        if not cls and "_" in str(name):
            cls = str(name).split("_", 1)[1]
        gfa = sum(_num(x) for x in rep.get("GFA", []))
        storeys = int(sum(_num(x) for x in rep.get("Storeys", [])))
        row = {
            "shape": str(name), "class": cls,
            "variant": int(_num(rep.get("Variant", [0])[0])) if rep.get("Variant") else "",
            "footprint_m2": round(_num(rep.get("Footprint_m2", [0])[0]), 2) if rep.get("Footprint_m2") else "",
            "height_m": round(_num(rep.get("Height_m", [0])[0]), 2) if rep.get("Height_m") else "",
            "storeys": storeys, "storeys_est": int(_num(rep.get("Storeys_est", [0])[0])) if rep.get("Storeys_est") else "",
            "gfa_m2": round(gfa, 1),
            "reports": {str(k): ([round(_num(x), 3) for x in v] if len(v) <= 8 else {"n": len(v), "sum": round(sum(_num(x) for x in v), 3)}) for k, v in rep.items()},
        }
        _ROWS.append(row)
    except Exception as e:
        _ERR.append("finishModel: %s" % e)


def finishExport(exportContextOID):
    t = _target()
    csv_path = t.get("csv")
    try:
        d = os.path.dirname(csv_path)
        if d and not os.path.isdir(d):
            os.makedirs(d)
        with open(csv_path, "w") as f:
            f.write("shape,class,variant,footprint_m2,height_m,storeys,storeys_est,gfa_m2,reports_json\n")
            for r in _ROWS:
                rj = json.dumps(r["reports"], separators=(",", ":")).replace('"', '""')
                f.write('%s,%s,%s,%s,%s,%s,%s,%s,"%s"\n' % (r["shape"], r["class"], r["variant"], r["footprint_m2"], r["height_m"],
                                                          r["storeys"], r["storeys_est"], r["gfa_m2"], rj))
        if t.get("json"):
            with open(t["json"], "w") as f:
                json.dump({"n": len(_ROWS), "errors": _ERR, "rows": _ROWS}, f, indent=0)
    except Exception as e:
        _ERR.append("finishExport: %s" % e)
    if _ERR:
        try:
            with open((csv_path or "report_v2") + ".err", "w") as f:
                f.write("\n".join(_ERR))
        except Exception:
            pass
