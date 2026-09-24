# data/ce/&lt;slug&gt;/height_overrides.json

An explicit, reviewed decision about one building's height. It beats every other source — the geojson
`bHeight`, the `heights_register.json` estimate, and the stub rule — and it is the only place a number is set
by judgement rather than by rule.

```json
{
  "generated": "2026-09-24",
  "heights": {
    "620": {"height_m": 153.6, "why": "Canal Heights 2, 48 floors; massed 88.0 is a part-built OSM capture"},
    "154": {"hold": true,      "why": "register row is Tiger Sky Tower (122 fl); this footprint is UPSIDE Living"}
  }
}
```

`height_m` sets the height. `hold: true` pins whatever the geojson says and stops the register and stub rules
touching it — for buildings where a rule would otherwise "fix" something into being wrong.

## Why this file exists

Three sources disagree about how tall a building is and none of them can arbitrate:

* `buildings.geojson` `bHeight` — 79% of the estate is the 12.0 m placeholder; where it is real it usually has
  no recorded provenance.
* `heights_register.json` — DLD units register, floors x 3.2. An estimate. It misses podium, parking and
  plant, so it reads LOW against a real height; and it is bound per parcel, so on a multi-building plot it can
  carry a **different building's** floor count.
* OSM (`osm_geom`, `osm_export`) — real in the sense that something measured it, and frequently captured while
  a tower was part-built, so it reads far LOW for anything under construction.

## The test that decided the four in Business Bay

Compare the name in `buildings.geojson` against the name in `data/board/bldgfacts_<slug>.json`:

| building | geojson name | facts name | massed | register | decision |
|---|---|---|---|---|---|
| b620 | "2" | Canal Heights 2 | 88.0 | 153.6 (48 fl) | **lift** — same building, massed value part-built |
| b589 | One River Point | ONE River Point | 88.0 | 140.8 (44 fl) | **lift** — same building |
| b650 | Aquarise | Binghatti Aquarise | 32.0 | 96.0 (30 fl) | **lift** — same building |
| b154 | UPSIDE Living by SRG | Tiger Sky Tower | 110.0 | 390.4 (122 fl) | **hold** — different buildings |

Where the two names agree, the register describes the same building and the low massed figure is a
part-built capture. Where they disagree, the register row is bound to a neighbour on the same parcel and
applying it would put one tower's height on another's footprint — the same failure as `dm_building_id`
meaning "tallest building on the plot".

b154 is the one that matters: it is the most conspicuous building in Business Bay, and the wrong fix there
would have been far more visible than the placeholder it replaced.

## Rule of thumb

A name agreement is evidence the two rows are the same building. A name disagreement is evidence they are
not. Neither is proof, which is why this file records *why*, and why anything recorded here should be
readable by a person who was not in the conversation.
