"""Build ce2026_batch.py: the production ce_batch_v2.py with lab-only paths, for the CityEngine 2026.1 beta test.
The production script is read, never written."""
import shutil

SRC = r"C:\Dev\naj-market-pulse\scripts\ce_batch_v2.py"
DST = r"C:\Dev\ce2026_lab\ce2026_batch.py"
src = open(SRC, encoding="utf-8").read()

LOGLINE = '    open(os.path.join(GLB, f"ce_batch_{VER}_last.log"), "w", encoding="utf-8").write("\\n".join(log_lines))\n'
subs = [
    ('HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, ".."))',
     'HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = r"C:\\Dev\\naj-market-pulse"'),
    ('CEDIR = os.path.join(ROOT, "data", "ce"); GLB = os.path.join(CEDIR, "_glb")',
     'CEDIR = r"C:\\Dev\\ce2026_lab\\data_ce"; GLB = os.path.join(CEDIR, "_glb")'),
    ('    ce = CE(); ws = ce.toFSPath("/"); proj = os.path.join(ws, "najma")\n',
     '    ce = CE(); ws = ce.toFSPath("/"); proj = os.path.join(ws, "najma")\n'
     '    if "najma" not in [str(p) for p in (ce.listProjects() or [])]:\n'
     '        ce.importProject(r"C:\\Dev\\ce2026_lab\\najma"); log("  lab: imported the najma project copy")\n'
     '    log("  lab: CityEngine", ce.getVersionString())\n'),
    (LOGLINE,
     LOGLINE +
     '    if os.environ.get("CE2026_UNATTENDED") == "1":\n'
     '        log("  lab: unattended run finished - closing CityEngine without saving")\n'
     '        open(os.path.join(GLB, f"ce_batch_{VER}_last.log"), "w", encoding="utf-8").write("\\n".join(log_lines))\n'
     '        ce.exit(False)\n'),
]
for a, b in subs:
    assert src.count(a) == 1, "no unique match for: " + a[:70]
    src = src.replace(a, b)
open(DST, "w", encoding="utf-8").write(src)
for helper in ("ce_report_v2.py", "glb_merge_per_building.py", "glb_merge_parts.py", "facade_classes.py"):
    shutil.copy2(r"C:\Dev\naj-market-pulse\scripts\\" + helper, r"C:\Dev\ce2026_lab\\" + helper)
print("wrote", DST, "and copied helpers")
