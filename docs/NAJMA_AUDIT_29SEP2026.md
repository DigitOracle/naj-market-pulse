# Najma building wiring — full audit

**Prepared for Dr. Digital Abbot · 29 September 2026**
Sources: four workstream sessions reporting on themselves, plus an independent measurement run against the files and the truth store. Where a reported number and a measured number disagree, both are shown and the disagreement is explained. Nothing here is estimated: a figure that could not be obtained is named as such.

---

## 1. The headline

The app is not short of data. It is short of **carriage**: in place after place the data exists, is computed, and is then discarded before it reaches the screen.

- The building id was worked out to place a map label, then dropped before saving.
- Floors and indicative homes were fetched and parsed, then thrown away by a single guard.
- The heat map step failed every morning for six days on a missing setting, and the chain carried on past it.
- Four scripts read a file every day that **nothing in the repo writes**.
- `key_bridge.py` exits 0 and writes nothing when run directly, because it is a job module, not a script.

Each of these was invisible from the screen. None was found by reading output; all were found by counting what the code discards, or by checking that a producer exists for every consumer.

**The single most valuable habit to adopt: for every artefact the app reads, name the job that writes it, and fail loudly when it is older than its source.**

---

## 2. What works

| Area | State |
|---|---|
| Government data | 523 datasets; ~95% pull cleanly. Core registers current: 257,269 buildings, 230,475 parcels, 2.37M units, 4.18M rent contracts, 1.78M transactions (to 17 Sep) |
| The twin's geometry | 45 districts, 70,443 footprints; 44 of 45 have a live tile; all 45 rebuilt headless today in ~80 minutes |
| Building tap | 95% of buildings open a real page (v266, deployed today). It was 3% this morning |
| Plot → building | 1,267 of 1,267 resolve, by id |
| The key bridge | 257,039 DLD buildings; 97.8% reachable by at least one other key |
| Question bank | 151 questions, 74 (49%) answered on a live screen from official registers, no hand-written answers |
| Daily pipeline | 32 steps, 29–30 ok every day this week |

## 3. What does not work

| # | Problem | Measured | Owner |
|---|---|---|---|
| 1 | Municipality building records reach only **43.1%** of DLD buildings (parcel reaches 97.7%). Floors, permits and usages live there, so this is the hard ceiling on what any building page can say | 110,720 / 257,039 | Gov data |
| 2 | Not a data limit — a **join that collapses in specific districts**: Al Thanayah Fourth 99.9%, Al Yelayiss 1 0.07%, Madinat Hind 4 0.04%, Al Yufrah 1 0.03% | measured today | Gov data |
| 3 | **89% of buildings have no name.** Their pages read "Unnamed building" | 7,116 named / 67,811 | 3D + data |
| 4 | Only **2.5%** of footprints carry a register id and **1.2%** a Municipality id in the enrichment files | 1,705 / 822 of 67,811 | Data (mine) |
| 5 | Map decides which building you tapped by **nearest centre within 30 m**, though each mesh carries its id | — | Rings (built, awaiting go) |
| 6 | A download **reported success with a stale count** while still running (985,946 vs the true 5,222,714) | 28 Sep | Gov data (**fixed**) |
| 7 | The pull process **died twice with no error line at all** | 28, 29 Sep | Gov data (heartbeat added; cause unknown) |
| 8 | Downloads hold whole datasets in memory, spiking to **7–8 GB**, twice forcing other work to pause on a 32 GB machine | — | Gov data |
| 9 | Heat map step failed **6 of 6 mornings** on a missing setting | 24–29 Sep | Mine (**fixed**) |
| 10 | Enrichment files a **week** behind the data they enrich | 7.1 d | Mine (**fixed**) |
| 11 | Per-district bridge files had **no producer**; read daily by four scripts | hand-made 22 Sep | Mine (**fixed**) |
| 12 | **No video published**; six episodes and a 5-minute film sit internal | 0 published | Question bank |
| 13 | **Nobody owns the merge plan** for five worker trees that all deploy to one app. A wrong-tree deploy on 12 Sep rolled the live app back 57 commits | — | **Open — needs your decision** |
| 14 | **No Cloudflare usage figures** have ever been pulled: storage size, browser rendering, image cost | — | **Open — needs dashboard access** |
| 15 | CityEngine leaks memory (83 MB → 13 GB; a build went 44 s → 57 min), cannot be driven automatically, and must take turns with Unreal | — | 3D (PyPRT proven) |
| 16 | 31% of the question bank (45 of 151) needs data we do not hold | — | Question bank |

## 4. Corrections made during the audit

Recording these because each was a confident claim that turned out to be wrong.

1. **"The repo you read was stale."** It was not; ancestry showed the tree I read was ahead of the one the other session called live. Acting on that claim would have put edits in the wrong tree.
2. **My own claim that stale files explained the low Municipality match.** Rebuilt from scratch, the figure is identical (21.8% across the map's districts). The real cause is that those districts genuinely match worse than the city as a whole.
3. **A "duplicated read" I reported on 22 Sep** no longer exists; it was fixed in between. Rings was right to refuse to touch it.
4. **An alarming-looking configuration warning** turned out to be a deliberate off-switch plus a secret, not a defect.
5. **My first fix ran a module that exits 0 and writes nothing** — the very failure this audit is about. Caught by checking the file was actually written.

## 5. Fixed today

- Heat map pushing again after six silent failures.
- Enrichment files rebuild when stale, not only when a developer sheet lands.
- Key bridge rebuilt daily rather than weekly.
- Per-district bridge files now have a producer (`scripts/emit_key_bridge_cuts.py`); all 45 rebuilt.
- Building tap: 3% → 95% (v266, live).
- The false-success download bug, plus a 30-second heartbeat so the next silent death leaves a trace.
- All 45 districts rebuilt headless; four coverage gaps closed; one district onboarded that never had been.
- Two more questions answerable, from layers that were never set up on our account and turned out to be public downloads.

## 6. What we should be doing better

1. **Every artefact needs a named producer and a staleness rule.** Three of today's four fixes were this one problem.
2. **Count what is discarded, not what is produced.** Both big wiring wins came from that.
3. **Settle the deploy trees.** Five trees, one live app, no owner for the merge plan. This has already cost a 57-commit rollback.
4. **Pull the Cloudflare numbers.** We do not know our own limits.
5. **Finish the move off CityEngine's interactive app.** The headless route is proven and removes the memory leaks, the crashes and the contention with Unreal.
6. **Stream large downloads.** One job should not be able to take the machine away from the others.
7. **Authorise HeyGen** so video renders stop being a manual paste.
8. **Do not let a join's citywide average stand in for a district.** 99.9% and 0.04% average to a number that describes nowhere.

## 7. Needs you

| Decision | Why |
|---|---|
| Who owns merging the five worker trees | One app, five trees, no plan; a wrong-tree deploy already cost a rollback |
| Authorise the HeyGen connection | Removes the manual step from every video |
| CityEngine 2026.1 beta | 3D session recommends installing side by side, production staying on 2025.1 + headless |
| Cloudflare dashboard figures | Nobody has ever pulled usage; we cannot see the ceiling we are heading for |
| Publishing videos | Six episodes and a film are finished and internal |
