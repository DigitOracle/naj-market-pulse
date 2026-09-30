"""CityEngine 2026.1 beta - unattended smoke test (runs as -DpythonStartupScript, in CE's built-in CPython).

Isolated lab workspace C:\\Dev\\ce2026_lab (never the production workspace). Imports alyufrah1's 63 footprints, assigns
najma_v4.rpk at LOD 3, generates, exports one GLB, records every step's timing and any error to out/result.json,
then closes CityEngine without saving anything.
"""
import json
import os
import time
import traceback

OUT = r"C:\Dev\ce2026_lab\out"
R = {"started": time.strftime("%Y-%m-%dT%H:%M:%S"), "steps": []}


def step(name, fn):
    t = time.time()
    try:
        v = fn()
        R["steps"].append({"step": name, "ok": True, "s": round(time.time() - t, 2), "value": v})
        return v
    except Exception as e:
        R["steps"].append({"step": name, "ok": False, "s": round(time.time() - t, 2), "error": repr(e)[:400],
                           "trace": traceback.format_exc()[-1500:]})
        raise


def dump():
    R["finished"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    json.dump(R, open(os.path.join(OUT, "result.json"), "w", encoding="utf-8"), indent=1, default=str)


ce = None
try:
    import cityengine
    from cityengine import CE, GLTFExportModelSettings, SHPImportSettings
    R["api_package"] = cityengine.get_api_package_version()
    ce = step("connect", lambda: CE())
    R["ce_version"] = step("version", lambda: str(ce.getVersionString()))
    step("workspace_root", lambda: str(ce.getWorkspaceRoot() if hasattr(ce, "getWorkspaceRoot") else ce.toFSPath("/")))
    step("import_project", lambda: str(ce.importProject(r"C:\Dev\ce2026_lab\lab")) if "lab" not in [str(p) for p in (ce.listProjects() or [])] else "already")
    step("new_scene", lambda: str(ce.newFile("/lab/scenes/test_2026.cej")))
    try:
        ce.waitForUIIdle()
    except Exception:
        time.sleep(2)

    def do_import():
        fs = ce.toFSPath("/lab/data/buildings.shp")
        s = SHPImportSettings()
        s.setFile(fs)
        return str(ce.importFile(fs, s))
    step("import_shp", do_import)
    shapes = step("find_shapes", lambda: ce.getObjectsFrom(ce.scene, ce.isShape))
    R["shapes"] = len(shapes)
    step("assign_rule", lambda: (ce.setRuleFile(shapes, "/lab/rules/najma_v4.rpk"), ce.setStartRule(shapes, "Lot"))[1])
    step("set_lod3", lambda: [ce.setAttribute(s, "/ce/rule/LOD", 3.0) for s in shapes][:1])
    step("generate", lambda: str(ce.generateModels(shapes)))

    def do_export():
        s = GLTFExportModelSettings()
        s.setOutputPath(OUT)
        s.setBaseName("alyufrah1_ce2026")
        s.setOutputFormat(GLTFExportModelSettings.GLTF_GLB_WITH_SINGLE_BUFFER)
        s.setIncludeMaterials(True)
        s.setExistingFiles(GLTFExportModelSettings.OVERWRITE)
        return str(ce.export(shapes, s))
    step("export_glb", do_export)
    R["ok"] = True
except Exception:
    R["ok"] = False
finally:
    dump()
    if ce is not None and os.environ.get("CE2026_KEEP_OPEN") != "1":
        try:
            ce.exit(False)          # documented safe shutdown without saving; no closeFile (it can prompt to save)
        except Exception as e:
            R["exit_error"] = repr(e)[:200]
            dump()
