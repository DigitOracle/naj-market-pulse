# Roadmap — the building page across all of Dubai

*21 Sep 2026. Kendall: "this needs to be implemented for all of Dubai, district by district, so you will create a roadmap, that
will run continuously ... you will keep moving forward if you hit a roadblock."*

Business Bay and DAMAC Hills are live. This is how the other 38 districts follow, what each one needs, and what happens when one
of them cannot be finished.

## The runner

`scripts/rollout_districts.py` — resumable, and a failure never stops the run.

```
python scripts/rollout_districts.py              every district on the twin's rail, resuming where it stopped
python scripts/rollout_districts.py --only a,b   just these
python scripts/rollout_districts.py --from plates start at a step
python scripts/rollout_districts.py --dry        say what it would do
```

State: `data/board/_rollout_state.json`, one row per district with the result of each step. A step that fails writes its error
there and the run carries on to the next district; re-running picks up only what is unfinished. Log: `logs/rollout_*.log`.

**Order is not per district, because two of the registers are gigabytes and are scanned once per run:**

| Step | Script | Scans |
|---|---|---|
| 1 stack | `build_floor_stack.py <all>` | DM floor register, 4.2 M rows, once |
| 2 views | `build_view_openness.py <all>` | the district's own anchors |
| 3 links | `build_scheme_links.py <all>` | Ejari, projects, land registry, Makani, permits, names, schools |
| 4 units | `build_unit_level.py <units file> <all>` | DLD units register, 3.1 GB, once |
| 5 plates | `build_floor_plates.py <one>` | per district (shapely; the slow one) |
| 6 publish | view pass `--push`, `push_units.py`, `push_plates.py` | to the app, per district |

Nothing in the worker changes per district: `/building/<district>/<id>` and the twin already read whatever keys exist.

## What every district already has

All 40 districts on the twin's rail carry the four inputs the chain needs: `unitmix_<d>.json`, `data/ce/<d>/buildings.geojson`,
`data/names/anchors_<d>.json` and `data/dld/rent_projects_<d>.json`. So every one of them can ship floors, open sides, rents,
units where coverage allows, and plates — today, without waiting for anything.

## What only two districts have, and who supplies it

These are the DDA session's per-district cuts. The page reads them where they exist and simply omits the section where they do
not, so a district ships without them and gains them later:

| Cut | File | Gives |
|---|---|---|
| schools + health | `amenities_<slug>.json` | KHDA schools with curriculum and rating, DHA facilities |
| project register | `projects_<slug>.json` | escrow, percent complete, due date — **joined by id** |
| land registry | `land_registry_<slug>.json` | tenure, zoning, plot area |
| Makani | `makani_<slug>.json` | the navigable address, bound to our duid |
| permits | `permits_<slug>.json` | the plot's building permit |
| id-derived names | `names_<slug>.json` | names reached through parcel ids, which adjudicate our name bindings |
| parcel → buildings | `parcel_buildings_<slug>.json` | what else stands on the plot |

**Asked for, 21 Sep:** the same seven cuts for the remaining 38 districts. Slug convention is theirs (`business_bay`,
`damac_hills`), and `build_scheme_links.py` maps district → slug in `SLUG`; a district missing from that map reads nothing and
still ships.

## The roadblocks we already know about

| Roadblock | Effect | What would clear it |
|---|---|---|
| **No parcel geometry anywhere in the DDA catalogue** | footprint → register stays matched by name; one wrong binding found so far (footprint 53) and 4 more flagged by id-derived names | a cadastral layer on the iPaaS subscription — **Kendall's to request** |
| **No unit-to-plate geometry in any register** | plates are indicative: sizes to scale, sides not published | a Revit model or a developer's stacking plan, per building |
| **Units coverage** | 53% of units citywide carry a parent that meets the building register; a district at half will fall back to floor level | nothing; the 80% guard is doing its job |
| **Identity** | DAMAC Hills has 1 of 1,006 footprints named against Business Bay's 228 | the id-derived names cut, per district |
| **Ground imagery** | `ground_<district>` is missing for most districts, so the page's hero has no aerial | `scripts/ground_imagery.py` per district |
| **Some districts have no model tile** | a district off the rail cannot be plated at all | CityEngine import (`data/ce/<d>/README_CE.md`) |

## Cadence

- `scripts/refresh_all_districts.ps1` already rebuilds and republishes Business Bay and DAMAC Hills nightly. Once a district has
  been through the roll-out once, it joins that list.
- The roll-out itself is re-runnable at any time; it only redoes what is unfinished or newly possible (a district gains its
  schools cut, say, and `links` runs again for it).

## Order of work

1. **Now:** run the roll-out over all 40 rail districts. Floors, open sides, rents, units, plates, published.
2. **As the cuts land:** re-run `links` per district for the seven extras.
3. **Then:** ground imagery per district, so every hero has its aerial.
4. **Then:** districts not yet on the rail — CityEngine import first, then the same chain.
5. **Continuous:** the nightly refresh keeps every district current as the registers move.
