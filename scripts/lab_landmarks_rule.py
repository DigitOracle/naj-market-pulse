"""LAB (landmarks, research only): make the lab copy of najma_v4.cga with the landmark hook applied, and the patch.

The hook is three small edits to najma_v4.cga - an import, a group of per-building attrs, and one case line in
Building - so a shape whose `landmark` attr names a family is built by rules/lab/landmarks/landmarks.cga at LOD 3
instead of the generic tower grammar (the same place the Akoya hero family hooks in). Everything else is untouched,
so with landmark = "" the copy must build every building exactly as najma_v4 does (lab_landmarks_build.py checks).

Writes (never touches najma_v4.cga itself):
  <CE workspace>/najma/rules/lab/landmarks/najma_v4_landmarks.cga   the rule the lab builds use
  data/lab/landmarks/INTEGRATION_rule.diff                           unified diff against najma/rules/najma_v4.cga
                                                                      (assembled into data/lab/landmarks/INTEGRATION.patch)

  python scripts/lab_landmarks_rule.py
"""
import difflib
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
WS = r"C:\Users\kwils\OneDrive\Documents\CityEngine\Default Workspace\najma"
SRC = os.path.join(WS, "rules", "najma_v4.cga")
LAB = os.path.join(WS, "rules", "lab", "landmarks", "najma_v4_landmarks.cga")
OUT = os.path.join(ROOT, "data", "lab", "landmarks")

IMPORT_ANCHOR = 'version "2023.0"\n'
ATTR_ANCHOR = 'attr heroStyle     = ""\n'
CASE_ANCHOR = '    case LOD >= 3 && heroStyle == "akoya" : Akoya3(v, c)'

ATTRS = '''// landmark family (LAB, 30 Sep): a named landmark gets a hand-authored Facade-Wizard-style build instead of the tower
// grammar. Which building, which family and the footprint-bound numbers come from data/lab/landmarks/landmark_table.json
// (keyed <slug>:<footprint index>); "" = generic. lmAz* / lmLen* are measured from the footprint by
// scripts/lab_landmarks_table.py - see rules/lab/landmarks/landmarks.cga for what each family reads.
@Group("Landmark", 90)
@Enum("", "spiral_setback", "twist", "void_cube")
attr landmark      = ""
@Range(min=0, max=2, stepsize=1, restricted=true)
attr lmLOD         = 2            // Facade Wizard LOD inside the landmark: 0 tile texture, 1 flat splits, 2 depth
attr lmFloors      = 0            // published storeys (0 = the family's reference value)
attr lmAz0         = 0            // footprint directions, deg, CE frame (spiral_setback: 3 wings; void_cube: long axis)
attr lmAz1         = 0
attr lmAz2         = 0
attr lmLen0        = 0            // spiral_setback: metres trimmed off each wing over its setbacks
attr lmLen1        = 0
attr lmLen2        = 0
'''
CASE = ('    case LOD >= 3 && landmark != "" : lmk.Landmark      // LAB 30 Sep: named landmarks (landmark_table.json) win over\n'
        '                                                            // every generic grammar, the hero family included\n')


def patched(src, import_path):
    for a in (IMPORT_ANCHOR, ATTR_ANCHOR, CASE_ANCHOR):
        if src.count(a) != 1:
            sys.exit("anchor not found exactly once in najma_v4.cga: %r" % a)
    src = src.replace(IMPORT_ANCHOR, IMPORT_ANCHOR + '\nimport lmk : "%s"\n' % import_path, 1)
    src = src.replace(ATTR_ANCHOR, ATTR_ANCHOR + ATTRS, 1)
    src = src.replace(CASE_ANCHOR, CASE + CASE_ANCHOR, 1)
    return src


def main():
    src = open(SRC, encoding="utf-8").read()
    os.makedirs(OUT, exist_ok=True)
    lab = patched(src, "landmarks.cga")                         # the lab copy sits next to landmarks.cga
    with open(LAB, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(lab.replace("Najma district rule v4 —", "LAB COPY (landmarks hook applied, research only) of najma_v4.cga.\n * Najma district rule v4 —", 1))
    real = patched(src, "lab/landmarks/landmarks.cga")          # what najma/rules/najma_v4.cga would import
    diff = difflib.unified_diff(src.splitlines(True), real.splitlines(True),
                                "a/najma/rules/najma_v4.cga", "b/najma/rules/najma_v4.cga")
    with open(os.path.join(OUT, "INTEGRATION_rule.diff"), "w", encoding="utf-8", newline="\n") as fh:
        fh.writelines(diff)
    print("wrote %s\nwrote %s" % (LAB, os.path.join(OUT, "INTEGRATION_rule.diff")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
