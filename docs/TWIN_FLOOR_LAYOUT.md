# The building page — every register-bound building, not just Symphony

*19–20 Sep 2026. Kendall: "the process for this building, we have similar in the digital twin, but not as nice, what does that
transition look like to get all of the building, starting in business bay and damac hills to look and act like this whilst
maintaining revit and arcgis integrity" — then, on the twin's side panel: "instead of opening a panel, it should open a new pop
up or page within the ecosystem", pointing at the Symphony viewer: "this is what i wanted to open up".*

The Symphony pilot (`data/stack/symphony_viewer.html`, Imtiaz) is a developer render with the units drawn over it, a Revit model
behind every room, the developer's availability sheet and the register. One building has all four. **Tapping any building in the
twin now opens the same page for it**, built from the registers, with the building's own CityEngine model cut into floors in
place of a render nobody published.

## What each building can show

| Level | What it shows | What it needs | Where it stands |
|---|---|---|---|
| **A · unit** | Tap a unit: its plan, price, view, its place on the floor | Revit model or a developer stacking plan, plus sheets | Symphony only (pilot, not deployed) |
| **B · floor** | Tap a floor: its use, how many homes, which types, what they settle at | The registers alone | **164 Business Bay, 24 DAMAC Hills** |
| **C · massing** | Height and name | A footprint | everything else, unchanged |

## The chain (all by id, never by name — except the one link that still is)

```
footprint id  ==  unitmix_<district>.buildings_by_id key  ==  the twin's window.BYFP key
      |
      +-- dm_building_id --> DM building_floor_level_information : every floor, its use, its units, its area
      +-- property_id ------> DLD units register : per type, the FLOOR RANGE, size, price, rent, yield
      +-- dld.parcel -------> parcel_buildings_<slug>.json (DDA session) : every building on the same plot
```

**The weak link is footprint → register, which is still matched by name** (Twin Bible §6). There is no parcel or plot id on our
footprints — `plot_id` is null on all 654 Business Bay records — and the DDA session confirmed on 20 Sep that **no cadastral or
land-plot layer exists in the 509 datasets on the iPaaS subscription**, and that the DET address register's coordinates are too
sparse to substitute (29 of 393 Business Bay parcels, none in DAMAC Hills). Closing it needs a cadastral layer added to the
subscription: **an action for Kendall**, not something either session can do.

## The pipeline

| Script | What it writes |
|---|---|
| `scripts/build_floor_stack.py` | `data/board/stack_<district>.json` — floors, types, plot facts, the guards below |
| `scripts/build_view_openness.py` | merges the open sides into the same file, and **publishes** (it runs last) |

Both are in `scripts/refresh_all_districts.ps1`, after `build_unit_mix.py`, whose output they read. The floor register is read
straight from the DDA pull's merged export (a `results` array of 4.2 M rows, streamed); a `.part` file mid-pull is never read.

## The page

`/building/<district>/<id>` — a client-key page, Najma's ink and gold, the Symphony layout:

- **FILTERS**, top right: bedroom chips, size, **price per sq ft**, **homes on the floor**, and **open view** as eight compass
  buttons. Floors that match stay lit on the model; the rest go dark.
- **Sold so far** — the register's sold-by-type against units launched.
- **About the building** — the facts, the stack, sold to date, what it sees over, who lives in the community, what else is on
  the plot, and what is around it.
- **Tap a floor** — on the model or in the layout chart — for its use, homes, area, types and what they settle at.

The twin's own top-right HOMES control was **replaced** by the same filter in Najma chrome (Kendall, 20 Sep: "the current
interface on the top right for homes, i do not like it"), so one filter drives buildings and floors together.

## The four filters nobody else has (Kendall's picks, 20 Sep)

1. **Open view.** For each floor and each of eight sectors, how much of that side is walled off by neighbours within 700 m, from
   the model's own surveyed heights. A neighbour blocks the slice it subtends, not the whole quadrant, and anything within 150 m
   fills its side. Al Habtoor Tower: south-west never (Safa Two, 348 m, 133 m away), north-east only from floor 87 (the Marriott
   pair at 355 m), east from floor 3. It does **not** know what lies beyond the roofs, assumes flat ground, and counts only this
   district's footprints.
2. **Homes on the floor** — the Municipality's unit count per floor.
3. **Price per sq ft** — register median price against median size, per type.
4. **Who lives here** — the DEWA register for the community. Community grain only, groups under 5% pooled, and stated as context
   about an area, never a reason to choose one (methodology §11, Kendall's decision of 17 Sep).

Also on the card, from the DDA session's per-building rollup: **mixed use** (15 in Business Bay), **retail podium** (77),
**registered floor area**, and **labour or staff accommodation in the same building** — which fixed a real error, since both were
being counted as "homes" until 20 Sep.

## The guards — what the page refuses to do

- **A footprint too short to hold its floors.** Where the model stands under 60% of the register building's height, **the floors
  are not cut into it** and both surfaces say why. 25 in Business Bay, 1 in DAMAC Hills. Al Habtoor City is the case that found
  it: a 346 m register record bound to a footprint standing 20 m in the model, and the twin was cutting 91 floors into it. Cause
  is either a podium footprint or a podium height on the tower (Twin Bible §4); the two are not yet told apart per case.
- **A name conflict.** Footprint 53 carries Enara By Omniyat's floors on the footprint the map calls The Binary By Omniyat. The
  card says so rather than drawing one building's floors as another's. Neither name is in the DLD building register yet — both
  are too new — so nothing can resolve it today.
- **A better match on the plot.** 12 bindings where another building on the same parcel fits the model height better; each keeps
  `height_flag` with the candidate's building id, ready for a hand re-bind.
- **Impossible register rows** — floor numbers past 200 and floor areas over 100,000 m² are dropped (the DDA session's caps,
  independently the same as mine).
- **No unit positions.** A type on a floor is the register's floor range. Unit positions exist only at level A.

## Where it stands, 20 Sep 2026

- **Business Bay** — 164 stacks, 160 of them on the model. 82 share a plot with another building.
- **DAMAC Hills** — 24 stacks built and correct, but **the app still has no 3D model of the district**, so nothing can be cut.
  The CityEngine import comes first (`data/ce/damachills/README_CE.md`), and only 1 of its 1,006 footprints is named.
- **DLD units** take a building from floor level to unit level without a Revit model: unit number, floor, area and type per
  flat. The pull stalled 199 pages short on 20 Sep in a DDA service outage (404 on every dataset, 04:25-06:31) and resumed once
  the service returned — our subscription was never suspended, so no ticket is needed.
  `scripts/build_unit_level.py` is written and dry-run against the documented shape, ready for the cut. Its guard: a building
  whose rows cover less than 80% of its registered units **stays at floor level**, because half a building shown as the whole of
  it is worse than not showing it. A unit is placed on its floor, never on the plate — which side of the corridor a flat sits on
  is not published, and only a Revit model or a developer stacking plan can say.

## The worker side

Branch **`twin-floor-stack`** in `C:\Dev\azimuth-worker-stack` (a worktree, so the deploying checkout is untouched).

| File | What it is |
|---|---|
| `src/building_page.js` | the building page: its data, its chrome, and `view()` — shipped as source text, so it carries its own helpers |
| `scripts/v186_floor_stack.js` | the twin's floor block, inserted by `scripts/v186_apply.py` above the tap handler |
| `test/test_v186_floor_stack.mjs` | 23 assertions through the real worker, in `npm test` |
| `test/check_building_page.mjs` | a hand check of the page against the real register files (not in `npm test`) |

Two traps worth remembering: the block sits **inside a template literal**, so `node --check src/index.js` cannot see its syntax —
the apply script checks it on its own first; and the worker is bundled with esbuild's `keepNames`, so anything stringified must
not lean on module-level helpers, which get renamed.

## To go live

1. `python scripts/build_floor_stack.py businessbay damachills` then `python scripts/build_view_openness.py businessbay damachills --push`
2. Deploy the branch (the Azimuth session is the usual deployer; it deploys on Kendall's go).
3. The nightly `refresh_all_districts.ps1` keeps both districts current from then on.
