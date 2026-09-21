# What to build, film and ask about — driven by the 2026 market, not by what we modelled first

**21 Sep 2026.** Kendall: *"When you did Sanctuary, it was perfect because it was pre-launch — anybody I'd speak to would have
seen an advert. I've got 64,000 buildings and it's going to take forever. I need to prioritise: get all the releases from 2026,
and that creates the priority list for building out the digital twins and the digital thread. And the question bank should come
from 2026 — things that are off-plan that are selling."*

He is right, and this document replaces the ordering used until now.

> **Corrected 21 Sep, same evening.** The first version of this read from our 45 district files — **2,645 of the 3,039 projects
> in the register, 87% of Dubai.** Kendall asked whether it was all of Dubai. It was not, and the missing 13% mattered: it hid
> **Bukadra** and **Wadi Al Safa 2 / Liwan**, both in the top thirteen and neither modelled, and it hid **Trump Tower**. Every
> figure below is now read from the full register, `data/raw_downloads/dda/prod/dld__dld_projects-open-api.json` (3,039 rows),
> joined to the CityEngine models and the area alias table.

---

## 1. The premise checks out

**Off-plan is 67.5% of Dubai sales in the current window** — 15,808 off-plan against 7,616 ready, 23,424 in total
(`public/pulse.json`, `transactions.offPlanSplit`). Kendall said 68%. That is the number.

So two thirds of the buyers Naj is talking to are buying something that does not exist yet. The question bank has been weighted
for the other third.

---

## 2. Where the market actually is

**471 projects launched in 2025–26 and are still selling or building — 131,875 units.** Ranked by units, against the districts
we have a 3D model for:

| # | Market name | DLD area | Units | Projects | Model |
|---|---|---|---|---|---|
| 1 | **City of Arabia** | Wadi Al Safa 4 | 10,925 | 13 | ✓ |
| 2 | **Jumeirah Village Circle** | Al Barsha South Fourth | 10,806 | 42 | ✓ |
| 3 | **Dubai Land Residence Complex** | Wadi Al Safa 5 | 9,889 | 39 | ✓ |
| 4 | **Al Furjan** | Jabal Ali First | 9,622 | 31 | ✓ |
| 5 | **Dubai World Central** | Madinat Al Mataar | 9,612 | 38 | ✓ *(filmed — video 03)* |
| 6 | **Dubai Maritime City** | Madinat Dubai Almelaheyah | 7,059 | 19 | ✓ |
| 7 | Dubai Investment Park Second | — | 6,165 | 13 | ✓ |
| 8 | **Jumeirah Village Triangle** | Al Barsha South Fifth | 5,623 | 16 | ✓ |
| 9 | **Palm Deira** | Palm Deira | 5,332 | 55 | ✓ |
| 10 | **Majan** | Wadi Al Safa 3 | 4,683 | 21 | ✓ |
| **11** | **Business Bay** | Business Bay | **4,194** | 11 | ✓ *(filmed — 01, 04, 05)* |
| **12** | **Bukadra** *(the Meydan / Sobha Hartland corridor)* | Bukadra | **3,397** | 8 | ✗ **NO MODEL** |
| **13** | **Liwan 1** | Wadi Al Safa 2 | **3,373** | 8 | ✗ **NO MODEL** |
| 14 | International Media Production Zone | Me'Aisem First | 3,026 | 10 | ✓ |
| 15 | Arjan | Al Barshaa South Third | 2,825 | 8 | ✓ |
| 16 | Motor City | Al Hebiah First | 2,819 | 6 | ✓ |
| 17 | Dubai Science Park | Al Barshaa South Second | 2,657 | 3 | ✓ |
| 18 | **Dubai Creek Harbour** | Al Khairan First | 2,351 | 5 | ✓ |
| 19 | Dubai Hills Estate | Hadaeq Sheikh Mohammed Bin Rashid | 2,309 | 5 | ✓ |
| 20 | Dubai Sports City | Al Hebiah Fourth | 2,081 | 6 | ✓ |
| 21 | Silicon Oasis | Nadd Hessa | 1,782 | 5 | ✓ |
| 22 | Town Square | Al Yelayiss 2 | 1,728 | 11 | ✓ |
| 23 | DMCC master community | Al Thanyah Fifth | 1,526 | 4 | ✓ |
| 24 | **Meydan One community** | Al Merkadh | 1,428 | 12 | ✓ |

**Kendall named Meydan, and he was right.** It does not show as one district because the register splits it:
**Meydan Group has 36 live launches and 5,259 units**, second only to Nakheel by project count — spread across **Al Merkadh**
(Meydan One, modelled) and **Bukadra** (not modelled). Bukadra alone is twelfth in Dubai and we cannot draw it.

**Two things fall out of that table.**

1. **Business Bay is eleventh, and DAMAC Hills is not in the top twenty.** Three of the five films made so far are Business Bay,
   one is DAMAC Hills. We have been filming where we modelled first, not where the market is.
2. **Twenty-two of the top twenty-four have a CityEngine model. Two do not** — Bukadra (12th) and Liwan 1 (13th), together
   6,770 launched units. Everywhere else the modelling is *not* the bottleneck and the work is **thread, sheets and filming**,
   not geometry. Those two are the only places geometry is the blocker, and one of them is Meydan.

3. **Units are not attention.** *Trump Tower* — Trade Center First, 574 units, Dar Global, started 15 Jan 2026 — will generate
   more client questions than ten thousand units in Dubailand. Rank by units for where to *build*; rank by brand and advertising
   for what to *film*. The two lists are different and both matter.

---

## 3. The launches people have seen adverts for

Started 2025–26, still selling, largest first. These are the names a client will recognise.

| Project | Market area | Units | % built | Due |
|---|---|---|---|---|
| **Azizi Milan Heights** | City of Arabia | 2,852 | 0% | 2028-09 |
| **Sobha Central Phase I** | Al Furjan | 2,383 | 0% | 2030-06 |
| **Sobha Central Phase II** | Al Furjan | 2,143 | 0% | 2030-06 |
| **Azizi Venice 15** | Dubai World Central | 1,855 | 0% | 2027-05 |
| **Skyhills Astra by HRE** | Dubai Science Park | 1,700 | 34% | 2028-06 |
| Binghatti Aquarise | Business Bay | 1,584 | 0% | 2026-10 |
| Azizi Milan 18 | City of Arabia | 1,541 | 0% | 2027-04 |
| **Breez by Danube** | Dubai Maritime City | 1,200 | 0% | 2029-06 |
| Timez by Danube | Silicon Oasis | 1,142 | 1% | 2028-07 |
| **Chelsea Residences 2 by DAMAC** | Dubai Maritime City | 958 | 0% | 2029-12 |
| **DAMAC Riverside Views — Capri 1 / Azure 1** | DIP Second | 824 each | 0% | 2029-03 |
| Terra Heights | Dubai World Central | 1,004 | 1% | 2029-03 |
| DAMAC District | DAMAC Hills | 1,008 | 0% | 2029-03 |

**Started in 2026 itself: 29 projects, 9,909 units.** Largest first:

| Project | Market area | Units | Developer | Model |
|---|---|---|---|---|
| **Skyhills Gardens** | Liwan 1 / Wadi Al Safa 2 | 1,429 | HRE | ✗ |
| **Breez by Danube** | Dubai Maritime City | 1,200 | Dubai Maritime City | ✓ |
| **DAMAC District** | Al Hebiah Third | 1,008 | DAMAC Crescent | ✓ |
| Rise by Athlon 1 | Dubai Land Residence Complex | 650 | Dubailand | ✓ |
| **Trump Tower** | Trade Center First | 574 | **Dar Global** | ✗ |
| **Akala Hotels & Residences** | Zaabeel Second | 546 | Arada | ✗ |
| Soulever' by Beyond | Dubai Maritime City | 517 | Dubai Maritime City | ✓ |
| Mayfair Nexus | Wadi Al Safa 7 | 473 | Seven Mayfair | ✗ |
| Rise by Athlon 2 | Dubai Land Residence Complex | 407 | Dubailand | ✓ |
| Talea · SERA 1 · SERA 2 · Aurea | Dubai Maritime City | 912 combined | Maritime City / Mina Rashid | ✓ |

**Six of the twenty-nine 2026 starts are in Dubai Maritime City — 2,829 units.** That is the single newest concentration in the
city, it has a model, and we have never touched it.

**⚠️ The register's `developer_name` is the LANDOWNER, not the brand.** Tested: it gives *Dubai Properties* for **Binghatti
Aquarise** and *Dubai Maritime City* for **Breez by Danube**. It is only right where the brand owns its own land — *Sobha* for
Sobha Central, *DAMAC Crescent* for DAMAC District. So a league table built on that field ranks master communities, not
developers, and must be read that way:

**Master communities by units launched 2025–26:** Nakheel 17,532 (85 projects) · DHAM free zone 9,008 (26) · Kaldari 8,733 (9) ·
Jumeirah Village 7,573 (31) · Dubailand Residences 6,893 (31) · **Sobha 6,777 (4, and genuinely the developer)** · Liwan 6,483
(24) · Dubai Aviation City 6,374 (28) · DAMAC Meray 6,165 (13) · Dubai Maritime City 5,395 (9) · **Meydan Group 5,259 (36)**.

**To rank actual developers** we need the brand, which lives in the project name — or the `/dev` board's own entity list. Worth
doing properly before anyone quotes a developer league table from this.

## 4. Two corrections to what I told Kendall earlier today

**4.1 The escrow episode does not work as I pitched it.** I said a project on the Business Bay register list had no escrow tick
and that the absence was the reveal. Checked properly: **143 of 2,645 projects have no escrow agent named, and 140 of them are
FINISHED** — completed schemes that no longer need an escrow account. Only two PENDING and one ACTIVE lack one, and **100% of the
417 live 2025–26 launches have a named escrow agent.**

So an absent tick almost always means *finished*, not *dodgy*. Putting "watch for the one without a tick" on camera would have
been misleading and, aimed at a named company, worse than that. **Killed.**

The honest version is a better film anyway: *escrow is not the question, because everything live has it — here is what actually
varies.* What varies is percent built against handover date, the developer's record, and units registered against units launched.

**4.2 The slate was ordered by our geometry, not by the market.** Corrected in §6.

---

## 5. The question bank, re-weighted for an off-plan market

If two thirds of buyers are buying off-plan, the bank's answered questions split into those that serve them and those that serve
the other third. The off-plan set should lead.

**Off-plan questions — serve 67.5% of the market:**

| Bank | Question | Where |
|---|---|---|
| Q105 | How far along is construction? | `/dev` and `/area` % built; twin colours |
| Q106 | Is the project registered, with an escrow account? | `/area` and `/r` escrow ✓ |
| Q107 | Is handover on schedule? | twin panel Handover — **the date is shown; keeping to it is not measured** |
| Q056 | When is handover? | twin panel; unit-mix completion |
| Q092 / Q093 | What is the payment plan? Is there a post-handover plan? | twin panel; `/dev`; `/avail` |
| Q103 | What is the developer's track record? | `/avail` *Verify the developer* — 4 developers only |
| Q114 | Is the developer's licence valid? | `/avail` → the official DLD licence page |
| Q097 / Q102 | How many units are left, and on which floors? | unit-mix *left*; `/avail` unit list |
| Q120 | What share of sales here are off-plan? | twin panel; PULSE; `/area` |
| Q044 / Q117 | What is being built nearby? How much supply is coming? | twin construction colours; PULSE supply |
| **Q049** | **Could a future building block the view?** | twin views name the blocker |

Q049 is worth calling out: for an off-plan buyer it is **the** question. You are paying for a view that does not exist yet, and
the thing that might block it does not exist yet either. Nobody else in Dubai can answer it.

**Ready-market questions — serve the other 32.5%, and stay on the slate but below:** rent and yield (Q071, Q072, Q138), what it
sold for (Q069), price fairness (Q075, Q128, Q149).

**Who lives here (Q040, Q038) is neither — it is a fixed beat in every episode** (template §8.1), whichever market the episode
serves.

---

## 6. The rebuilt slate

Ordered by **market relevance first**, then by the five-axis score from the template.

| # | Episode | Where to shoot it | Why now |
|---|---|---|---|
| **1** | **"It doesn't exist yet. How do I know it will?"** *(Q105, Q106, Q107, Q103)* | **Al Furjan — Sobha Central**, 4,526 units across two phases, 0% built, due 2030 | Two thirds of the market is buying exactly this. Escrow is universal, so the film is about % built against handover date and the developer's record |
| **2** | **"Could someone build in front of me?"** *(Q049, Q048)* | ONE River Point, Business Bay — the blocker is 344 m away and 87 m taller | Ready now, no dependencies, and it is the format's signature occlusion reveal. The only Business Bay episode that stays near the top on merit |
| **3** | **"Six towers launched here since January."** *(Q044, Q117, Q120)* | **Dubai Maritime City** — half the 2026 launches, never filmed | The newest concentration in Dubai. First mover on a district with adverts running and no broker content |
| **4** | **"What am I actually paying, and when?"** *(Q092, Q093, Q056)* | A named launch with a published plan — **Azizi Milan Heights**, City of Arabia, 2,852 units | The off-plan buyer's second question after "is it real". Payment plans are held for 29 of 726 projects plus developer sheets — pick one we hold |
| **5** | **"There's no school in Business Bay."** *(Q028, Q013)* | Business Bay, honest negative | Trust play, ready now, and it is the one a competitor will never copy |

Dropped from the earlier list: the escrow-tick reveal (§4.1). "Who lives here" is no longer a separate episode because it is now
a beat in all of them.

---

## 7. What to build out, in order

Geometry exists for twenty-two of the top twenty-four. What does not exist is the **thread** — the sheets, availability and
per-building binding that make a district filmable.

**Model first (geometry is the blocker):**

0. **Bukadra** — 3,397 units, 8 projects, 12th in Dubai, and it is the Meydan / Sobha Hartland corridor Kendall named. No model.
0b. **Liwan 1 / Wadi Al Safa 2** — 3,373 units, 8 projects, including Skyhills Gardens, the largest 2026 start in the city.

**Then thread, in this order:**

1. **Dubai Maritime City** — six 2026 launches, 2,829 units, never touched. Highest attention-to-work ratio in the city.
2. **Al Furjan** — Sobha Central Phase I and II, 4,526 units, the largest single launch we hold.
3. **City of Arabia** — biggest by launched units; the Azizi Milan series is heavily advertised.
4. **Jumeirah Village Circle** — 42 live projects, the most fragmented and most searched.
5. **Dubai World Central** — already threaded and filmed (video 03), so cheapest to revisit.

**Worth a separate look regardless of rank: Trade Center First**, for Trump Tower alone.

Business Bay and DAMAC Hills are **done** for now. They are eleventh and outside the top twenty.

---

## 8. Data questions this raised — for the DDA session, not for a video

- **`percent_completed` looks stale.** 35 projects have a handover date before Jan 2027 and are recorded under 10% built —
  7,348 units, led by Binghatti Aquarise (1,584 units, 0% built, due Oct 2026). Either the field is not maintained or a lot of
  schemes are very late. **Do not build a film on it until we know which.** It also makes Q107's own note — *"the date is shown;
  keeping to it is not measured"* — the most important caveat in the bank.
- **Payment plans cover 29 of 726 projects.** For an off-plan-led series that is the biggest single data gap.
- **`/avail` *Verify the developer* exists for four developers.** Track record is an off-plan essential and it reaches almost none
  of the launches above.
- **`/dev` carries no cancelled or on-hold counts.** Those live only on `/avail`.

---

*Sources: `data/raw_downloads/dda/prod/dld__dld_projects-open-api.json` (the full register, 3,039 projects — **not** the 2,645
in our 45 district files), `data/dld/area_alias.json` (marketing name → DLD area),
`data/ce/*/buildings.geojson` (41 models), `public/pulse.json` (`transactions.offPlanSplit`), `questions/bank.json`. Read
21 Sep 2026.*
