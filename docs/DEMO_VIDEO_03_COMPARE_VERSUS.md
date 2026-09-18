# NAJMA DEMO 03 — the developers, then the world (18 Sep 2026)

**The line it answers:** *"I've heard Emaar and Sobha are the good developers — can you put them side by
side, for a two-bedroom? … I'm also considering London. Tell me why Dubai."*

**What it shows that 01 and 02 did not.** Neither earlier video opened an engine: 01 was a buyer on the
map, 02 a family on the map. This one opens on the whole city turning and then goes straight to a developer, not the map (Kendall, 18 Sep:
*"it will start off with a developer … can you pull up a side-by-side … then the query moves towards
London or New York … tell me why I should choose Dubai"*). Two engines carry it — **COMPARE** (two
developers, every row re-cut by bedroom and price band) and **VERSUS** (Dubai against a world city at
the client's budget: what the money buys, the taxes at the door, what you keep each year, the things a
family asks about) — and it closes on a floor plan from **PLANS**, the two-bed she came in asking for.

Both engines and the plans open on the CLIENT_KEY tier (`/compare`, `/versus`, `/plans` are on the
client path list); PULSE and the residents page are not needed.

---

## The screens, as probed 18 Sep (client key, 1080×1920)

**COMPARE — Emaar vs Sobha, all homes** (the two-bed cut is read off the take):

| row | Emaar | Sobha |
|---|---|---|
| registered sales 2026 | 7,561 | 2,765 |
| median price | AED 2.55M | AED 2.01M |
| typical range (P10–P90) | 1.34M – 5.00M | 1.07M – 3.41M |
| median AED/m² | 20,816 | **25,241** |
| off-plan share | 37% | 65% |
| where the sales are | Madinat Al Mataar · Burj Khalifa · Creek Harbour | Sobha Heartland · Bukadra · DMCC |
| median rent, all homes | 160,000/yr | 90,000/yr |
| gross yield proxy | 6.3% | 4.5% |
| projects trading 2026 | 217 | 47 |

Page's own caption: *"not a verdict: a higher AED/m² is a pricier product, a higher off-plan share is a
younger pipeline."* Source line: DLD Open Data transactions Jan–Aug 2026 on each developer's own
projects; rents = Ejari on the same projects. Updated 2026-09-17.

**VERSUS — Dubai against three cities** (budget tile 2m; the page's "on AED 5M" lines are its own):

| line | Dubai | London | New York | Monaco |
|---|---|---|---|---|
| prime AED/sq ft | 4,260 | 7,200 (1.7×) | 9,920 (2.3×) | 22,790 (5.3×) |
| what AED 5M buys at the top end | 84 m² | 45 m² | 46 m² | 22 m² — "about a Rove hotel room" |
| tax and fees at the door | 4% | up to 19% (foreign second home) | up to 3.9% mansion tax | ~6.25% duty + notary |
| paid at the door on AED 5M | 200,000 | 950,000 | 195,000 | 312,500 |
| top rate of income tax | 0% | 45% | 52% | 0% |
| holding it, every year | no property tax; 5% housing fee on rent | council tax band H ~£2,100 | ~1.1% of value a year | no property tax |
| what the flat pays you, gross | 5.5% | **6.6%** | 5% | 3.3% |
| tax on the gain when you sell | 0% | 24% | 23.8% federal | 0% |
| sunshine hours a year | 3,570 | 1,526 | 2,535 | 2,575 |
| safety, crowd-sourced rank | 6 of 401 | 298 | 261 | n/a |
| flight from Dubai, non-stop | home | 8h10 | 14h10 | 6h50 |

Honesty notes the narrative respects: London's *gross* yield is higher than Dubai's — on screen, not in
the voice (there were not the seconds for it); the tax lines are where Dubai wins, and the page makes that case on its own. Several "life and
culture" rows (Michelin totals, event crowds) are marked *not verified* on the page and stay out of the
narration.

**PLANS — Emaar → Marina Cove at Dubai Marina → 2 BED.** 27 plan entries on file for Marina Cove; the
two-bed opens inline as a full-width plan (`Type 2 BED · unit · level 01`). Most other Emaar projects
hold brochure pages or 3/4-bed plans only (Greenway's single "plan" is a brochure cover — checked and
avoided).

---

## Beat sheet (planned — timings come from the take)

| # | Avatar asks (client voice) | App does |
|---|---|---|
| 1 | "I've heard Emaar and Sobha are the good developers — side by side, two bedrooms." | **COMPARE**: tap Emaar, tap Sobha, tap *2 bed*; the rows re-cut; scroll the table |
| 2 | "I'm also looking at London. Why Dubai?" | **VERSUS**: London, budget 2m; scroll money → the door → every year → living |
| 3 | "And New York?" | tap New York; the same lines re-answer |
| 4 | "Monaco, then." | tap Monaco — five times the price per square foot, a hotel room's worth of floor |
| 5 | "Fine — Emaar. Show me the two-bed." | **PLANS**: Emaar → Marina Cove → 2 BED; the plan held for the sign-off |
| — | "Welcome to Azimuth. Complexity into clarity." | held on the plan |

Harness: `NAJMA_VIDEO=3 python scripts/demo_capture.py capture` then `cut` (`journey3` in
`scripts/demo_capture.py`; the close is a held freeze of the plan, `freeze_close`, since there is no
PDF). Assertions per beat: the COMPARE URL carries `a=emaar&b=sobha&bed=2`; each VERSUS page contains
"<city> costs"; a plan image over 500 px wide with "2 BED" in its alt is on screen.

## As cut - take 3, 18 Sep, 1:20 (`NAJMA_DEMO03_COMPARE_VERSUS_SCREEN_9x16_18SEP2026.mp4`)

Take 1 (1:07) opened straight on COMPARE and a word-card variant tried a four-second hook; Kendall
asked instead for the whole map turning - *Dubai is a big place, it seems overwhelming, let me walk you
through how Azimuth guides you.* The all-Dubai twin (`/skyline?all=1`, on the client tier) is exactly
that: 64,238 buildings, 41 districts, coloured by district, and it turns under the same drag orbit as
video 01's twin. It records in slow motion (96.9 s for the turn) and `cut()` now plays an orbit span at
speed wherever it sits in the take (`orbit_start` / `orbit_end`, `ORBIT_TARGET` = 11 s).

| time | beat | on screen | checked |
|---|---|---|---|
| 0:00-0:11 | the city turning | the all-Dubai twin, camera drawing in over the districts | buildings count read off the page |
| 0:11-0:30 | COMPARE | Emaar, Sobha, *2 bed* - every row re-cut; the table scrolled | URL carries a=emaar&b=sobha&bed=2 |
| 0:30-0:44 | VERSUS London | budget 2m; money, the door, every year, living, London's own card | page contains 'London costs' |
| 0:44-0:52 | New York | the same lines re-answer | 'New York costs' |
| 0:52-0:59 | Monaco | 5.3x per sq ft; nine square metres for two million | 'Monaco costs' |
| 0:59-1:10 | PLANS | straight to Marina Cove's page (no ALVA grid), then 2 BED inline | plan image > 500 px with '2 BED' alt |
| 1:10-1:20 | the close | the plan held 9 s for the sign-off | frame |

Take 3 replaced take 2 on Kendall's note that the ALVA brochure pages in Emaar's default list sat
off-centre: the PLANS beat now opens Marina Cove's page directly, so the only plans in frame are its own.

## Open items

- The COMPARE two-bed figures are read off the take, not the all-homes table above.
- If the Azimuth session ships the enlarged EV card today it does not affect this video (no map beat).
