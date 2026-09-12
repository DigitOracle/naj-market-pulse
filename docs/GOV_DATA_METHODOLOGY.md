# How a government dataset earns its way into her feed

The pipeline from a Dubai Data pull to a sentence Najjuko posts, written down after a day of
applying it. Nine gates. A dataset that fails one stops there; it stays registered so the failure is
on record, but nothing downstream reads it.

The principle behind all nine: **a number she posts must be traceable to a public body, a date, and a
row that a person can open.** Every gate exists because a way was found for that to silently stop
being true.

## 1. Register everything, including the failures

`scripts/load_gov_datasets.py` writes one row to `gov_dataset` for every dataset the pull
*attempted*: entity, title, status, rows, file, and whether it was materialised. The 84 that came
back service-unavailable and the 77 the firewall blocked are rows too. A missing dataset that is
named is a retry; a missing dataset that is not named is a blind spot.

## 2. Materialise into the truth store

Landed rows go into `gov_<entity>__<dataset>` tables in `data/graph/najma.duckdb`. The payload shape
is one object carrying a `results` array, and `select unnest(results)` yields a single anonymous
struct column rather than the fields; the struct has to be expanded in a second step. Nothing above
two million rows is loaded without a decision.

## 3. The realness gate, row by row

`scripts/gate_gov_realness.py`. The staging environment does not only serve stale data; it serves
**some rows of otherwise real datasets with the values scrambled**. The visitor-region field holds
hundred-character strings, fifty random letters then fifty random digits. The Salik tariff's months
are HAU, OBZ, ZGN. Nine of the 235 bus-coverage rows are fill; the other 226 are genuine communities.

Judged per dataset, that register is either wholly accepted, importing nine fabricated communities,
or wholly rejected, discarding 226 real ones. So it is judged per row, and every table gets a
companion view `g_<entity>__<dataset>` carrying only rows that pass. `v_gov_usable` names that view.
**Nothing downstream may read a base table.**

Two signatures, and they do not deserve the same unit of judgement:

| Signature | Example | Judged per |
|---|---|---|
| twelve or more characters of uppercase letters and digits, no break, few vowels | `SVJERDHTONGYTIBNUJRGKCJZMBZRFX…` | row |
| a 3–8 letter vowel-poor uppercase word in a column whose *name* promises a word | month = `HAU` | column, and only if most of the column is like it |

The second is column-level because MIRDIF is six letters with two vowels and looks exactly like
HAU to a row test. It was dropped as fake on the first pass. DXB and GBR are real and vowel-poor,
so code-named columns are exempt.

## 4. Currency: structural or time-series

Every candidate is asked *when it stops*. `dm_building_permits` holds 1.1 million rows and dies in
2016: 51,145 permits that year, nine in 2019, four in 2026. Every broker licence in the DLD register
has expired. Neither can carry a "this month" post.

The rule: a **time-series** fact (permits issued, sales, index moves) must be current, or it is not
posted as current. A **structural** fact (where the metro stations are, which communities the bus
network reaches, which hour the airport is busiest) does not go stale week to week, and is posted
with its report date. The block carries that date, and the caution travels inside the data, not in
a footnote.

## 5. Geography: three classes, one forbidden move

| Class | Example | How it binds |
|---|---|---|
| DLD area names | land registry `area_name_en`, transactions `AREA_EN` | joins the register directly; same geography |
| coordinates | metro stations, bus stops, food businesses, taxi stands | distance to her 41 district centroids; a flat approximation with a cosine correction is accurate to tens of metres at this latitude |
| foreign community names | RTA and Municipality community registers | **reported by their own names, never mapped onto her board** |

Five of 226 bus-coverage community names match her district labels exactly. A fuzzy match would
invent a geography. The 07:02 feed proved the risk in prose: the model welded "no bus stop in this
whole community" to a sales count from the register, naming no community at all. The guard in
`dailyFeedTick` now drops any city angle that does not name a place present in its block, or that
borrows a figure from another section.

The Valley registers under its legacy name, Al Yufrah 1. Ghaf Woods still has no mapping; do not
guess it.

## 6. Relevance: does it change what a buyer or resident does

Customs commodity codes, registered detergents and food additives pass every gate above and fail
this one. Bus coverage passes: a community with 7,350 residents and zero percent coverage changes
what someone who does not drive decides. The test is whether the fact belongs in a conversation
with a client, not whether it is interesting.

## 7. Into the pulse, with its provenance inside

`scripts/build_city_block.py` and `scripts/build_inventory_moves.py` write blocks into
`public/pulse.json`. Each block carries `asOf`, the body, the report date, a `caution` line, and
`basedOn` with the rows used **and the fill rows excluded**. The bus-speed section leads with the
median because the raw column runs to 201 km/h, and says so in the block. The professions section
says it counts titles, not residents. If the feed writes an angle from either, the caveat travels
with the number.

## 8. Into the prompt, with a family and a rule, enforced after

The brief the model receives is a curated object. A block that is not named in it does not exist to
the model; the city data sat live on the Worker for a morning and produced nothing until it was
listed. Each new block gets a `FEED_FAMILIES` entry so an angle can land somewhere and the no-repeat
memory can track it, a sentence in the instructions saying what it is for, a floor ("at least one of
the five"), and a post-generation check that enforces the geography rule rather than trusting it.

The inventory rule is spelled out because a model gets it wrong by default: **a count that rose was
released by the developer, never call it a sale.**

## 9. Every posted number names its body and its date

"RTA bus network coverage, 31 Dec 2024." "Developer inventory moves, Beyond, 24 Aug–2 Sep 2026."
The source is part of the angle, not decoration, and the QA pass rejects an angle without one.

## What this has produced so far

- Metro access by district: 11 of her 41 within two kilometres, 23 beyond five.
- Bus coverage by community: 3,549,900 residents, 88% within reach; fifteen communities of over a
  thousand people with no stop at all.
- Developer inventory movement: Beyond released eight three-beds in nine days while three two-beds
  were taken up. The one post no other broker can write.
- The airport's busiest hour, the median bus speed, and the profession register.

## What it has refused

- 1.1 million building permits, because they end in 2016.
- 16,850 broker licences, because every one has expired.
- 19 datasets whose every row is fill, and 71,783 fill rows out of 25 mixed datasets.
- A metro-to-bus-community join, because the names are different geographies.
- The sales count that the 07:02 angle tried to attach to a bus-coverage community.
