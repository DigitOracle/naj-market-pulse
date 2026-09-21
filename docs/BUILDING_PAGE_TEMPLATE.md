# The building page template — The Symphony standard

*21 Sep 2026. Kendall: "these kind of things should not be ad hoc. We have worked through an entire building where we've done
everything ... that needs to be the template as you roll this out across all of Dubai."*

The building is **The Symphony by Imtiaz** (Meydan Horizon, Bukadra) — the pilot built 19 Sep in the question-bank session: a
developer render with every unit drawn on it, a Revit model behind every room, the developer's availability sheet, the register,
the floor plate with the unit in red, unit cards, and the About-the-building card. That page is the standard. This file is that
standard written down so it can be **checked** rather than remembered, section by section, with the fallback for every building
that does not have what Symphony has.

`scripts/audit_building_pages.py` scores every building against this table and writes `data/board/audit_<district>.json`. The
roll-out runs it per district, so the gap list is produced, not noticed.

## The contract

| # | Section | Symphony has | Every building must have | Fallback when the data is missing |
|---|---|---|---|---|
| 1 | **Name and developer** | name, developer, district across the top | the same | the register's name; "developer not on the register" |
| 2 | **The model** | the developer's render, units drawn on it | its own textured model, cut into floors, in its real setting | floors not cut where the footprint is too short (podium); the model still stands |
| 3 | **Floors are reachable** | every floor tappable | tap a band **and** a floor picker in the panel that always works | picker alone where the model cannot be cut |
| 4 | **The floor plate** | the Revit plate, the chosen unit in red | the indicative plate: cells at registered sizes, lifts and stairs, north | the type ranges where the register cannot place homes; "not drawn" with the reason where it cannot be built |
| 5 | **The flats on the floor** | unit number, size, view, price | the register's flats: number, type, size, balcony | the types the register puts on the floor, with no numbers |
| 6 | **What it sells for** | the sheet's asking price, the register's median | the register's median per type, price per sq ft, sold against launched | omit the types the register does not price |
| 7 | **What it lets for** | — | Ejari rents per type, contracts, new vs renewed, yield | omit; the scheme has no Ejari record |
| 8 | **What has sold here** | the register's sales for the project | registered sales, median per sq ft, off-plan share, the last six | omit where the name does not bind strictly |
| 9 | **Construction** | progress from the developer's site | the register's status, percent complete, due date, escrow agent | omit where the project register has no row |
| 10 | **The plans** | the developer's floor-plan deck | the project's plans from the library, in a lightbox | omit; no plans held for this project |
| 11 | **The plot** | — | tenure, zoning, plot area, land number, what else stands on it | omit where the land registry has no row |
| 12 | **The building facts** | stack, units, height, parking, lifts | the same, from the Municipality permit and the register | show what exists |
| 13 | **Around it** | nearest of each kind | metro, mall, landmark; schools with curriculum and rating, linked to the map | omit what the district has no cut for |
| 14 | **Who lives here** | — | the community's resident mix, as a ring that drills to countries | omit below the disclosure floor |
| 15 | **What it sees over** | — | the open sides per floor, from the model | omit where the district has no neighbours modelled |
| 16 | **Every claim sourced** | each figure names its source | the same, and the caveat on anything indicative | — |

## The rules that are not negotiable

1. **Nothing is invented.** A section is omitted, never filled with a plausible number. "Omit" in the table above means the
   section does not render at all.
2. **Indicative is labelled.** The plate carries its caveat on every view: the outline is surveyed, the sizes are the register's,
   the sides are not published.
3. **No unit positions are claimed.** Only a Revit model or a developer's stacking plan can place a flat on its plate — Symphony
   has one, and says so; nothing else may imply it.
4. **A building is never a dead end.** If the model cannot be cut, the floors are still reachable through the picker.
5. **A disagreement between registers is shown, not resolved silently** — the Municipality's home count against the Land
   Department's flat count, a name conflict, a binding the id-derived names contradict.

## Scoring

The audit reports, per building: which of the 16 sections render, and why each missing one is missing (`no data` against
`not applicable`). A district's score is the share of its buildings carrying each section — which is the roll-out's progress
measure, and the list of what to ask the DDA session for next.

## Symphony's own score, and what it cost to fix

The Symphony **is** on the twin, as the district `goldensymphony`. The first thing this audit did was score it — and it came
back **9 of 16**, below the Business Bay median. The page was reading the same registers as every other building, and the Land
Department holds no units for an off-plan tower, so the template building had an empty plate and no flats card while the
developer's Revit model of that exact building sat unused in `data/stack/symphony_units.json`.

`scripts/build_symphony_level_a.py` closes that: 290 flats over floors 10-34, each with the model's own unit number, type and
its rectangle on the plate, written into the two files the page already reads. Setting the plan into the surveyed footprint is
a fit, not an assumption — the model's plate is 43.4 x 40.0 m and the footprint's minimum rotated rectangle is 43.3 x 39.9 m,
so the axes are matched by length and the scale is within a decimetre. What is **not** claimed is any flat's compass aspect:
the model's own labels are to project north, which is not true north here.

That needed a fourth basis on the plate caption, `revit` (worker patch v205): a plate drawn from a model must not be captioned
"indicative", and must not carry the "no unit numbers are shown" line. Symphony now scores **10 of 16**, and the six it still
misses are named gaps in Meydan Horizon's cuts, not defects in the page:

| Missing | Why | Who clears it |
|---|---|---|
| What it lets for | no Ejari record binds to this scheme | it is off-plan; nobody lets it yet |
| What has sold here | no registered sale binds to this name | the same |
| Construction | no row in the project register | the DDA session's `projects_<slug>` cut for this district |
| The plot | the land registry cut has no row for this parcel | `land_registry_<slug>` |
| Around it | the district has no amenities cut | `amenities_<slug>` |
| Who lives here | the community is not in the resident mix | nothing: a tower with no residents yet |

**This is the pattern for the whole roll-out.** The audit names what is missing and why; the gap is either a cut to ask for,
a level-A source to wire in, or a fact that does not exist yet — never a page to patch by hand.
