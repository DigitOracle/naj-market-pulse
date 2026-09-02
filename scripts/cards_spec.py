"""Card spec for revit_v2_cards.cs: representative unit per card type -> floor, crop box (bay + balcony side + margin), highlight numbers."""
import json, os
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.join(HERE, "..")
# representative unit per type = a unit that is ON the developer availability sheet where one exists (1907, 2902, 2410, 3307)
CARDS = [("MasterSuite_1BR", "1101", "F11"), ("1BR", "1907", "F19"), ("2BR", "2902", "F29"), ("3BR", "2410", "F24"), ("4BR", "3201", "F32"),
         ("4BR_Duplex_lower", "3307", "F33"), ("4BR_Duplex_upper", "3407", "F34")]
rows = []
for key, unit, F in CARDS:
    j = json.load(open(os.path.join(ROOT, "data", "revit", "v2_%s.json" % F)))
    u = next(x for x in j["units"] if x["unit"] == unit)
    x0, y0, x1, y1 = u["bay"]; b = u["back"]; m = 700; bal = 1600
    if b == "S": y1 += bal
    if b == "N": y0 -= bal
    if b == "W": x1 += bal
    if b == "E": x0 -= bal
    rows.append("%s|%s|%s|%d|%d|%d|%d|%s" % (key, unit, F, x0 - m, y0 - m, x1 + m, y1 + m, unit))
open(os.path.join(ROOT, "data", "revit", "cards_spec.txt"), "w").write("\n".join(rows) + "\n")
print("\n".join(rows))
