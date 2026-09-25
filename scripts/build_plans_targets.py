"""Which buildings are worth chasing floor plans for, ranked, so a harvest is a list rather than an ambition.

  python scripts/build_plans_targets.py        -> data/board/plans_targets.json

Kendall, 25 Sep 2026: "scope the broader harvest." The audit put The plans at 4% of 1,996 buildings, and v256
established that the matching is not the problem - 72 of 74 bindings were already right and only 2 were fixable by
code. The gap is inventory: we hold plans for TWELVE developers and 145 Dubai projects.

WHAT THE HARVEST ROUTES ACTUALLY ARE, which decides what "broader" can mean:

  * **Developer websites do not work.** The 5 Sep harvest tried eleven developers' portfolio pages and found no
    floor-plan links in any of them. Fakhruddin's own site returned zero images, zero PDFs and six 404s across
    eleven project pages. Scraping harder will not help; the material is not published.
  * **The broker group does work.** scripts/plans_from_group.py renders plan pages out of PDFs brokers post, and it
    is the only reason any Fakhruddin plans exist anywhere in the library.
  * **Brochures over WhatsApp work.** scripts/pull_brochures.py brings a deck down and registers it.

So a broader harvest is an ASKING problem, not a crawling one - which means the useful artefact is a ranked list of
what to ask for, not another scraper.

THE RANKING IS FLOORS, AND THAT IS A DELIBERATE RETREAT. The obvious ranking is homes, and it is unusable: the
register's unit counts are a PROJECT figure repeated on every building of the project. Al Ramth 1, 21, 23, 35, 37,
39, 45 and 41 others each report 11,422 homes on nine floors. Measured across the estate, 378 of 1,862 buildings -
20.3% - carry a type-unit row set identical to another building in the same district, the largest group being 48
buildings sharing one. Ranking by that number would have put a Remraam low-rise above the Burj Khalifa Residence.
Floors come from the building's own stack and are per building.

WHAT COMES OUT: 773 buildings of twenty floors or more with no plans, led by the towers anyone would name first -
THE RESIDENCE Burj Khalifa at 177, Burj Binghatti Jacob & Co at 109, Aeternitas at 109, Tiger Sky at 108, Sobha
Central at 103, Marina 101 at 102, Princess Tower at 97. Those are the asks that change what the app can show.
"""
import collections
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKER = os.environ.get("AZ_WORKER", r"C:\Dev\azimuth-worker-dewa")
MIN_FLOORS = 20

NODE = r"""
import('./src/building_page.js').then(m => {
  const fs = require('fs'); const NAJ = %s;
  const rd = f => { try { return JSON.parse(fs.readFileSync(f, 'utf8')); } catch (e) { return null; } };
  const plans = rd(NAJ + '/board/plans_index.json');
  const slugs = fs.readdirSync(NAJ + '/board').filter(f => /^stack_.*\.json$/.test(f)).map(f => f.slice(6, -5));
  const out = [];
  for (const slug of slugs) {
    const stack = rd(NAJ + '/board/stack_' + slug + '.json'), umx = rd(NAJ + '/board/unitmix_' + slug + '.json');
    if (!stack || !umx) continue;
    const anc = rd(NAJ + '/names/anchors_' + slug + '.json');
    for (const id of Object.keys(stack.buildings_by_id || {})) {
      const D = m.buildingData(slug, id, stack, umx, null, anc, null, slug, plans, null, null, null);
      if (!D || !D.name || D.name === 'Unnamed building') continue;
      const u = umx.buildings_by_id[id] || {};
      out.push({ name: D.name, slug, i: id, floors: (D.floors || []).length,
                 has_plans: !!D.plans, project: (u.dld || {}).project || null,
                 developer: (u.developer || '').trim() || null });
    }
  }
  process.stdout.write(JSON.stringify(out));
});
"""


def scan():
    src = NODE % json.dumps((os.path.join(ROOT, "data")).replace("\\", "/"))
    # bytes, not text: Windows decodes a pipe as cp1252 and the estate holds Arabic building names, so text=True
    # dies on the first one and returns nothing at all.
    r = subprocess.run(["node", "-e", src], cwd=WORKER, capture_output=True, timeout=900)
    if r.returncode != 0:
        sys.exit("scan failed: " + (r.stderr or b"").decode("utf-8", "replace")[-600:])
    return json.loads(r.stdout.decode("utf-8", "replace"))


def main():
    rows = scan()
    miss = [r for r in rows if not r["has_plans"] and r["floors"] >= MIN_FLOORS]
    miss.sort(key=lambda r: -r["floors"])
    by_d = collections.Counter(r["slug"] for r in miss)
    by_dev = collections.Counter(r["developer"] for r in miss if r["developer"])

    out = {
        "built": "build_plans_targets.py",
        "rule": "a named building with a card, %d floors or more, and no floor plan bound to it" % MIN_FLOORS,
        "why_floors_not_homes": ("the register's unit counts are a PROJECT figure repeated on every building of the "
                                 "project - 378 of 1,862 buildings (20.3%) share an identical type-unit row set with "
                                 "another building in the same district, the largest group being 48. Ranking by homes "
                                 "puts a Remraam low-rise above the Burj Khalifa Residence. Floors are per building."),
        "how_to_harvest": ("developer websites do not publish floor plans - the 5 Sep run found none across eleven "
                           "portfolios. The routes that work are scripts/plans_from_group.py (PDFs brokers post) and "
                           "scripts/pull_brochures.py (decks over WhatsApp). This is an asking problem, not a "
                           "crawling one."),
        "counts": {"named_carded": len(rows), "with_plans": sum(1 for r in rows if r["has_plans"]),
                   "targets": len(miss)},
        "by_district": by_d.most_common(),
        "by_named_developer": by_dev.most_common(20),
        "targets": miss,
    }
    p = os.path.join(ROOT, "data", "board", "plans_targets.json")
    json.dump(out, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    print("%d named buildings carded, %d have plans, %d targets at %d+ floors"
          % (len(rows), out["counts"]["with_plans"], len(miss), MIN_FLOORS))
    print("\ntop of the list:")
    for r in miss[:12]:
        print("   %3d floors  %-38s %s" % (r["floors"], r["name"][:38], r["slug"]))
    print("\nwhere they are:")
    for s, n in by_d.most_common(8):
        print("   %-26s %4d" % (s, n))
    print("\n-> " + p)


if __name__ == "__main__":
    main()
