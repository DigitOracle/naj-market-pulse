"""LAB (register thread, research only): make najma_v4_register.cga = najma_v4.cga + the register block, and the
unified diff that IS the production patch (so what was tested and what would be applied are the same bytes).

Reads   najma/rules/najma_v4.cga                                  (never written)
Writes  najma/rules/lab/register/najma_v4_register.cga
        data/lab/register/PATCH_najma_v4_register.diff

  python scripts/lab_register_make_rule.py
"""
import difflib
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
WS = r"C:\Users\kwils\OneDrive\Documents\CityEngine\Default Workspace\najma\rules"
SRC = os.path.join(WS, "najma_v4.cga")
DST_DIR = os.path.join(WS, "lab", "register")
DST = os.path.join(DST_DIR, "najma_v4_register.cga")
PATCH = os.path.join(ROOT, "data", "lab", "register", "PATCH_najma_v4_register.diff")

ATTR_ANCHOR = 'attr wallH         = 1.8'   # END of the attr section: CGA @Group is sticky, so a
                                          # register block placed earlier pulled every design control into "Register"
LOT_ANCHOR = '    cleanupGeometry(all, 0.3)\n    report("Footprint_m2", geometry.area)'

ATTRS = r'''
// ---------------------------------------------------------------- register (the digital thread)
// The building's register details travel ON the model. Two ways in, one way out:
//   in (1)  object attrs pushed per building (PyPRT shape attrs / CE setAttribute + source OBJECT), from
//           data/lab/register/register_<slug>.csv. A pushed value always wins.
//   in (2)  regTable = that CSV: the rule finds its own row by the building id (reg_id, else the b<i> prefix of
//           initialShape.name) - Tutorial 21's readStringTable. Fills only the fields nothing was pushed for.
//   out     report("reg.<field>") once per building (RegReports, from Lot) -> PyPRT reports (-> glTF node extras),
//           the CE export callback, Datasmith <MetaData> (metadata = reports | all).
// Empty string / -1 = unknown: nothing is reported for it, so an unknown never reads as a value.
@Group("Register", 90) @Order(0) @Description("b<footprint index>; empty = the prefix of the shape name")
attr reg_id         = ""
@Group("Register", 90) @Order(1)
attr reg_duid       = ""
@Group("Register", 90) @Order(2)
attr reg_name       = ""
@Group("Register", 90) @Order(3)
attr reg_dev        = ""
@Group("Register", 90) @Order(4)
attr reg_project    = ""
@Group("Register", 90) @Order(5)
attr reg_status     = ""          // register status: verified | partial | placeholder
@Group("Register", 90) @Order(6)
attr reg_floors     = -1          // with reg_floors_src: dm_floors | dm_permit | estimate
@Group("Register", 90) @Order(7)
attr reg_floors_src = ""
@Group("Register", 90) @Order(8)
attr reg_units      = -1          // THIS building's units only (never a multi-building project total)
@Group("Register", 90) @Order(9)
attr reg_floor_uses = [""]         // DM per-floor use, ground up (Tutorial 21 per-floor array). [""] = unknown, NOT
                                  // stringArray(): an EMPTY array default crashes PyPRT 1.12 (int divide by zero)
                                  // on every shape the attr is not pushed for - measured 30 Sep
@Group("Register", 90) @Order(10) @Description("register_<slug>.csv - looked up by building id for fields not pushed")
attr regTable       = ""

regNameKey    = case find(initialShape.name, "_", 0) > 0 : substring(initialShape.name, 0, find(initialShape.name, "_", 0))
                else : initialShape.name
regKey        = case reg_id != "" : reg_id  else : regNameKey
regTbl        = readStringTable(regTable)
regRow        = case regTable == "" : -1
                else : findFirst(regTbl[0:nRows(regTbl) - 1, 0], regKey)
regCol(h)     = findFirst(regTbl[0, 0:nColumns(regTbl) - 1], h)
regCellAt(r, c) = case c < 0 : ""  else : regTbl[r, c]
regCell(h)    = case regRow < 1 : ""  else : regCellAt(regRow, regCol(h))
regStr(v, h)  = case v != "" : v  else : regCell(h)
regNum(v, h)  = case v >= 0 : v
                case regCell(h) == "" : -1
                else : float(regCell(h))
regUsesFrom(k) = case k >= size(reg_floor_uses) - 1 : reg_floor_uses[k]
                 else : reg_floor_uses[k] + "|" + regUsesFrom(k + 1)
regHasUses    = size(reg_floor_uses) > 1 || reg_floor_uses[0] != ""
regUses       = case regHasUses : regUsesFrom(0)  else : regCell("floor_uses")
regSrc        = case reg_id != "" || reg_name != "" : "attrs"
                case regRow >= 1 : "table"
                else : "none"
'''

LOT_ADD = '    [ RegReports ]\n'

RULES = r'''
// ---------------------------------------------------------------- register reports (the digital thread)
RegReports -->
    RegStr("reg.id", regKey)
    RegStr("reg.src", regSrc)
    RegNum("reg.table_rows", case regTable == "" : -1  else : nRows(regTbl))   // did regTable resolve? (0 = no)
    RegStr("reg.duid", regStr(reg_duid, "duid"))
    RegStr("reg.name", regStr(reg_name, "name"))
    RegStr("reg.developer", regStr(reg_dev, "developer"))
    RegStr("reg.project", regStr(reg_project, "project"))
    RegStr("reg.status", regStr(reg_status, "status"))
    RegNum("reg.floors", regNum(reg_floors, "floors"))
    RegStr("reg.floors_src", regStr(reg_floors_src, "floors_src"))
    RegNum("reg.units", regNum(reg_units, "units"))
    RegStr("reg.floor_uses", regUses)
    RegUse(0)
RegStr(k, v) --> case v == "" : NIL  else : report(k, v) NIL
RegNum(k, v) --> case v < 0 : NIL  else : report(k, v) NIL
// one tick per DM floor under its use, e.g. reg.use.homes = 7 (Tutorial 21 / Space_Colored_By_Use "GFA." + use)
RegUse(k) -->
    case k >= size(reg_floor_uses) : NIL
    case reg_floor_uses[k] == "" : RegUse(k + 1)
    else : report("reg.use." + reg_floor_uses[k], 1) RegUse(k + 1)
'''


def main():
    raw = open(SRC, "rb").read().decode("utf-8")
    nl = "\r\n" if "\r\n" in raw else "\n"
    src = raw.replace("\r\n", "\n")
    assert src.count(ATTR_ANCHOR) == 1, "attr anchor not unique in najma_v4.cga"
    assert src.count(LOT_ANCHOR) == 1, "Lot anchor not unique in najma_v4.cga"
    i = src.index("\n", src.index(ATTR_ANCHOR)) + 1
    out = src[:i] + ATTRS + src[i:]
    j = out.index(LOT_ANCHOR) + len("    cleanupGeometry(all, 0.3)\n")
    out = out[:j] + LOT_ADD + out[j:]
    out = out.rstrip("\n") + "\n" + RULES
    os.makedirs(DST_DIR, exist_ok=True)
    open(DST, "wb").write(out.replace("\n", nl).encode("utf-8"))
    diff = difflib.unified_diff(src.splitlines(True), out.splitlines(True),
                                "a/najma/rules/najma_v4.cga", "b/najma/rules/najma_v4.cga", n=3)
    os.makedirs(os.path.dirname(PATCH), exist_ok=True)
    open(PATCH, "w", encoding="utf-8", newline="\n").write("".join(diff))
    print("  wrote %s (%d lines, +%d vs najma_v4.cga)" % (DST, out.count("\n"), out.count("\n") - src.count("\n")))
    print("  wrote %s" % os.path.relpath(PATCH, ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
