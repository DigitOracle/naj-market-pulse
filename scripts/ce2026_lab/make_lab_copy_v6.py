"""Build ce2026_batch_v6.py: the lab v3 copy (make_lab_copy.py) re-pointed at the new facade rule najma_v6.cga.

Separate FILE on purpose: the running 24-district parity batch re-imports ce2026_batch.py in every fresh CityEngine, so
it must never change mid-batch. This writes a different module and touches nothing the batch uses.

Differences from ce2026_batch.py:
  - rule          /najma/rules/najma_v6.cga (staged from C:\\Dev\\ce2026_lab\\rules_v6, next to the repo rules)
  - outputs       C:\\Dev\\ce2026_lab\\data_ce_v6 (own GLB/report folder; the v3 parity outputs are untouched)
  - Datasmith     after each glTF export, an Unreal export of the same shapes when CE2026_DATASMITH=1, with the 2026
                  exporter's UseUnrealBaseMaterials + metadata, to check that PBR and names reach Unreal
Shape names, attributes, LOD ladder and every other step are the production v3 build's.
"""
import os
import subprocess
import sys

LAB = r"C:\Dev\ce2026_lab"
# base = the EXISTING v3 lab copy, read only - never regenerated from here, so the running batch is untouched
src = open(os.path.join(LAB, "ce2026_batch.py"), encoding="utf-8").read()

subs = [
    ('CEDIR = r"C:\\Dev\\ce2026_lab\\data_ce"; GLB',
     'CEDIR = r"C:\\Dev\\ce2026_lab\\data_ce_v6"; GLB'),
    ('RULE_WS = f"/najma/rules/najma_{VER}.cga"; ',
     'RULE_WS = "/najma/rules/najma_v6.cga"; '),
    ('            if fn.endswith(".cga"): shutil.copy2(os.path.join(root, fn), os.path.join(dst, fn))\n',
     '            if fn.endswith(".cga"): shutil.copy2(os.path.join(root, fn), os.path.join(dst, fn))\n'
     '    for fn in os.listdir(r"C:\\Dev\\ce2026_lab\\rules_v6"):   # lab: stage the v6 facade rule beside the repo rules\n'
     '        if fn.endswith(".cga"): shutil.copy2(os.path.join(r"C:\\Dev\\ce2026_lab\\rules_v6", fn), os.path.join(proj, "rules", fn))\n'),
    ('        t0 = time.time(); ce.export(shapes, s); te = time.time() - t0\n',
     '        t0 = time.time(); ce.export(shapes, s); te = time.time() - t0\n'
     '        if os.environ.get("CE2026_DATASMITH") == "1":   # lab: the same shapes to Unreal, 2026 exporter\n'
     '            try:\n'
     '                import cityengine as _cem\n'
     '                u = _cem.UnrealExportModelSettings(); u.setOutputPath(os.path.join(CEDIR, "_datasmith")); u.setBaseName(f"{slug}_v6")\n'
     '                for _m, _v in (("setUseUnrealBaseMaterials", True), ("setMeshMerging", "perInitialShape"), ("setInstancing", "disabled"), ("setMetadata", "all")):\n'
     '                    try: getattr(u, _m)(_v)\n'
     '                    except Exception as _e: log(f"  datasmith {_m}: {str(_e)[:80]}")\n'
     '                os.makedirs(os.path.join(CEDIR, "_datasmith"), exist_ok=True)\n'
     '                t1 = time.time(); ce.export(shapes, u); log(f"  datasmith export {time.time() - t1:.1f}s")\n'
     '            except Exception as _e:\n'
     '                log(f"  datasmith export FAILED: {str(_e)[:200]}")\n'),
]
for a, b in subs:
    assert src.count(a) == 1, "no unique match for: " + a[:70]
    src = src.replace(a, b)
open(os.path.join(LAB, "ce2026_batch_v6.py"), "w", encoding="utf-8").write(src)
print("wrote", os.path.join(LAB, "ce2026_batch_v6.py"))
