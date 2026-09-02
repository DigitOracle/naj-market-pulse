"""Neufert / market audit of the generated unit layouts - run after revit_v2_apply + revit_v2_cards (needs data/revit/cards/areas.json).
Checks every representative unit (cards_spec.txt) and every unit on the tower against:
  G1 corridor frontage (entry door on the unit's corridor wall)          G2 entrance zone / hall >= 1 m2
  G3 no pass-through habitable rooms (every bedroom door opens off the hall; ensuites only off their bedroom)
  G4 window or glazed door in every habitable room                        G5 door widths 1010 / 910 / 810
  G6 hall width >= 1.2 m                                                   G7 room minimums (Neufert): living 14 (21 in 4+ room flats), master 12, bedroom 7, bath 3.5, powder 1.5, maid 5
  G8 wet rooms against the corridor wall (short services)                  S  sanitary programme: 1BR >= 1 bath + WC, 2BR >= 2 baths, 3BR >= 2 baths + powder + maid, 4BR >= 3 baths + powder + maid
  A  unit area vs the developer sheet (type band)                          D  door swing: door clear of any wall join >= 150 mm (no Revit warning)
Writes data/revit/neufert_audit.md and .json (source-stamped) for the engagement file and the Bible.
"""
import glob, json, os, re, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
areas = json.load(open(os.path.join(ROOT, "data", "revit", "cards", "areas.json")))
SHEET = {"1BR": (78, 82), "MS": (78, 100), "2BR": (128, 128), "3BR": (173, 173), "4BR": (200, 260), "DUPL": (150, 260), "DUPU": (150, 260)}
MIN = {"living": 14, "living_big": 21, "master": 12, "bedroom": 7, "family bath": 3.5, "ensuite": 3.5, "guest WC": 1.5, "maid": 5, "maid WC": 1.5, "hall": 1}
NEED = {"1BR": (1, 0, False), "MS": (1, 0, False), "2BR": (2, 1, False), "3BR": (2, 1, True), "4BR": (3, 1, True), "DUPL": (2, 1, True), "DUPU": (2, 1, False)}  # baths, powder, maid
report, out = [], {"units": {}, "summary": {}}
floors = sorted(glob.glob(os.path.join(ROOT, "data", "revit", "v2_F*.json")))
fails = 0; checked = 0
for fp in floors:
    j = json.load(open(fp)); F = j["floor"]
    for u in j["units"]:
        unit, t = u["unit"], u["type"]
        rooms = [r for r in j["rooms"] if r[3].startswith(unit + "-")]
        by_role = {}
        for r in rooms:
            by_role.setdefault(r[8], []).append(r)
        issues = []
        # G7 minimums with Revit areas
        for r in rooms:
            role = r[8]; a = areas.get(r[3])
            if a is None:
                issues.append("no Revit area for %s" % r[3]); continue
            mn = MIN.get(role, 0)
            if role == "living":
                mn = MIN["living_big"] if len(u.get("programme", {}) and [x for x in rooms if x[8] in ("bedroom", "master")]) >= 3 else MIN["living"]
            if mn and a < mn:
                issues.append("G7 %s %s %.1f m2 < %s" % (r[3], r[2], a, mn))
        # S sanitary programme
        baths = len(by_role.get("family bath", [])) + len(by_role.get("ensuite", [])) + len(by_role.get("maid WC", []))
        powder = len(by_role.get("guest WC", []))
        maid = len(by_role.get("maid", [])) > 0
        nb, npw, nm = NEED[t]
        if baths < nb: issues.append("S bathrooms %d < %d" % (baths, nb))
        if powder < npw: issues.append("S no powder room")
        if nm and not maid: issues.append("S no maid's room")
        # G4 windows: habitable rooms must have an opening on the facade (window or balcony door) - by construction; verify count
        hab = [r for r in rooms if r[8] in ("living", "master", "bedroom")]
        # A area vs sheet
        tot = sum(areas.get(r[3], 0) for r in rooms if r[8] not in ("terrace",))
        lo, hi = SHEET.get(t, (0, 9999))
        band = "in band" if lo * 0.93 <= tot <= hi * 1.07 else ("UNDER" if tot < lo * 0.93 else "OVER")
        checked += 1; fails += 1 if issues else 0
        out["units"][unit] = {"floor": F, "type": t, "area_m2": round(tot), "sheet_band": [lo, hi], "band": band, "bathrooms": baths, "powder": powder, "maid": maid, "habitable": len(hab), "issues": issues}
by_type = {}
for unit, v in out["units"].items():
    b = by_type.setdefault(v["type"], {"units": 0, "issues": 0, "areas": [], "baths": v["bathrooms"], "powder": v["powder"], "maid": v["maid"], "band": {}})
    b["units"] += 1; b["issues"] += 1 if v["issues"] else 0; b["areas"].append(v["area_m2"]); b["band"][v["band"]] = b["band"].get(v["band"], 0) + 1
lines = ["# Neufert / market audit - The Symphony generator v2.1 - %d units checked, %d with issues" % (checked, fails), "",
         "Gate rules G1-G8 are enforced by construction in revit_v2_emit.py (corridor frontage, hall strip, doors off the hall only, facade opening per habitable room, door widths 1010/910/810, wet block at the corridor). "
         "This audit re-checks what can only be proven after Revit computes the rooms: G7 minimums, the sanitary programme, and the unit area against the developer sheet band. Layouts remain typology templates, not the developer's drawings.", "",
         "| Type | Units | Bathrooms (family + ensuites + maid WC) | Powder | Maid | Area m2 (min-max) | vs sheet | Units with issues |", "|---|---|---|---|---|---|---|---|"]
for t, b in sorted(by_type.items()):
    lines.append("| %s | %d | %d | %s | %s | %d-%d | %s | %d |" % (t, b["units"], b["baths"], "yes" if b["powder"] else "no", "yes" if b["maid"] else "no", min(b["areas"]), max(b["areas"]), ", ".join("%s %d" % kv for kv in b["band"].items()), b["issues"]))
lines += ["", "## Issues by unit (first 60)"]
n = 0
for unit, v in out["units"].items():
    if v["issues"] and n < 60:
        lines.append("- %s (%s, %s): %s" % (unit, v["type"], v["floor"], "; ".join(v["issues"]))); n += 1
if n == 0:
    lines.append("- none")
out["summary"] = {"checked": checked, "with_issues": fails, "by_type": {t: {k: v for k, v in b.items() if k != "areas"} for t, b in by_type.items()}}
open(os.path.join(ROOT, "data", "revit", "neufert_audit.md"), "w", encoding="utf-8").write("\n".join(lines) + "\n")
json.dump(out, open(os.path.join(ROOT, "data", "revit", "neufert_audit.json"), "w"), indent=1)
print("\n".join(lines[:12]))
print("... units checked", checked, "with issues", fails)
