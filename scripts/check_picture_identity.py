"""Do a sheet's PICTURES belong to the building whose PRICES it quotes? Strict version.

The subset rule that is right for card joins is wrong here. "Bellevue Towers-1" and "Bellevue
Towers" reduce to the same distinctive words ({bellevue}) because TOWER and a bare number are
generic - that is a tower within a development and its pictures are fine. "Treppan Vision" against
"Treppan Tower" reduces to {treppan, vision} against {treppan}: the picture side carries a NAME the
sheet does not, and a name is a different project. Subset passes it; equality catches it.

Run with --check to prove it: it reports what the SUBSET rule would have said too, so the difference
is visible rather than asserted.
"""
import glob
import io
import json
import os
import sys

sys.path.insert(0, r"C:\Dev\naj-market-pulse\scripts")
os.chdir(r"C:\Dev\naj-market-pulse")
from build_unit_mix import distinctive, same_building  # noqa: E402
from build_client_sheet import find_building  # noqa: E402

bad, ok = [], []
for f in sorted(glob.glob("data/sheets/_assets/*/_provenance.json")):
    slug = os.path.basename(os.path.dirname(f))
    d = json.load(io.open(f, encoding="utf-8"))
    pic = (d.get("project") or "").strip()
    rows = find_building(slug.replace("_", " "))
    sheet = (rows[0].get("project") if rows else slug.replace("_", " ")) or ""
    a, b = distinctive(pic), distinctive(sheet)
    agree = bool(a) and a == b
    (ok if agree else bad).append((slug, sheet, pic, a, b, same_building(pic, sheet)))

print("sheets with wired pictures: %d | agree: %d | DISAGREE: %d" % (len(ok) + len(bad), len(ok), len(bad)))
print()
for slug, sheet, pic, a, b, subset_said in bad:
    print("  %-26s prices %-26s pictures %-26s" % (slug[:26], (sheet or "?")[:26], pic[:26]))
    print("       words %s vs %s%s" % (sorted(a), sorted(b),
                                       "   <-- the SUBSET rule called this fine" if subset_said else ""))
