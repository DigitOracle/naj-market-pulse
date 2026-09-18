# Demo video 02 — "Somewhere that feels like home" (DAMAC Hills, a British family)

**Format:** 9:16 vertical · target ~75s · Naj's tool, filmed as the broker's view
**Avatar:** HeyGen overlays Naj's twin; she plays the CLIENT. Screen side from `scripts/demo_capture.py`.
**The line the video answers** (Kendall, 18 Sep): *"I want to live in an area where I will be around
stores, schools, and people that remind me of home, so the transition is easier."*
**The client:** British. Kendall's choice, 18 Sep, over the Indian client the numbers favoured — and
it turned out to be the only choice the app can finish: the Indian-heavy communities (Al Qusais 76%,
Mankhool 81%) have no building prices, no amenity files and no client sheets in the app, so that
story would have died after the people beat.

## Why DAMAC Hills

Kendall named it. On the data it holds up for every beat but one, and that one is now built:

| beat | what DAMAC Hills gives, from the app | source |
|---|---|---|
| people | British the largest European group at **13%**; Europe 26%, Arab world 30%, South Asia 15% | DEWA register, 7,000 accounts, 8% no nationality |
| schools | **five UK-curriculum schools** on the card within 3 km, two rated *Very good* by KHDA: Ranches Primary 1.9 km, Royal Grammar School Guildford 2.6 km; GEMS Metropole, South View, Horizon English | KHDA school register |
| shops | **two Spinneys inside a kilometre** — 804 m and 924 m — then Géant and Carrefour | amenities image |
| homes | 24 buildings, **19 with a two-bed median at or under AED 2M**; Carson 1,575 units at AED 1.36M | `/img/map_prices` |
| the sheet | **built 18 Sep** — see below | `scripts/build_client_sheet.py` |

The one thing it does not have is a district twin, and the DAMAC Unreal film (`unreal_damachills_film30`,
plus cluster endings `c1..c9`) is **daylight** at 720p landscape — the same grade clash that got the
Business Bay fly-through pulled from video 01. So there is no twin beat here; the residents map is the
big visual instead.

## What was built to make it work

**The Carson client sheet.** `--list-ready` refused every DAMAC Hills building. The reason was
pictures, not sales — Carson has 2,218 registered sales — and DAMAC publishes nothing openly for
Carson except one photograph on its own blog: the residents' pool deck with the tower behind it.

- `data/sheets/_assets/damac_hills_carson/hero.jpg` — that photograph cropped to the tower band
  (the sheet's hero is 3.2:1 and takes the middle of what it is given; handing it the pool would
  have put the pool on page one).
- `amenity.jpg` — the full frame, on the finish page, captioned for what it is.
- `_provenance.json` — source URL, fetch date, `reuse_basis` "developer-published: on the
  developer's own website", and the note that it is a photo, not a render or an elevation.
- `data/sheets/_facts/damac_hills_carson.json` — developer DAMAC Properties; **completed 2021**
  (Dubai Municipality record 615974: certified 29 Nov 2021, permit June 2016, G+34+2R, 125 m);
  caveats that Carson is three towers on one plot and that the parking figure is plot-wide; an
  `image_note` override saying exactly where the picture came from and that no floor plans exist.

Result: `damac_hills_carson.pdf`, **3 pages, 403 KB, checked** — built without `--force`. Page two
is titled "Interiors — the developer's renders" by the template and holds a pool-deck photograph,
which the caption and footnote correct; a better exterior would make it a better page, and DAMAC
does not publish one.

## Beat sheet (planned — timings come from the take)

| # | Avatar asks (client voice) | App does | Bank |
|---|---|---|---|
| 1 | "I want to be around people who remind me of home. Where are the British?" | **RESIDENTS** (private, `rk`): nationality United Kingdom, minimum share 10%; the map shades, the ranked list fills; **DAMAC Hills 13%**, gold outline, detail bars: Europe 26 · Arab world 30 · South Asia 15 | Q040 |
| 2 | "And the schools — are there British ones?" | `/map` DAMAC Hills → SCHOOLS: the list with curriculum and KHDA rating — Ranches Primary *Very good · UK · 1.9 km*, RGS Guildford *Very good · UK · 2.6 km* | Q028, Q029 |
| 3 | *(hold)* | **Tap Ranches Primary** → the card: phone, email, website, directions, WhatsApp share, **QR to email**. Cursor visits each. *Everything is clickable.* | Q028 |
| 4 | "Is there a Spinneys?" | SUPERMARKETS: **Spinneys 804 m, Spinneys 924 m**, Géant, Carrefour. Tap the nearest → directions, share, QR | Q001 |
| 5 | "Two bedrooms, up to one point eight million." | HOMES filter, dragged: **13 here · 879 across Dubai** | Q074, Q098 |
| 6 | "Which one?" | "list them →", scroll, pick **Carson** — 1,575 units, two-bed AED 1.36M; the card | Q096, Q051 |
| 7 | *(the close)* | **Carson's three-page sheet** — 2,218 sales, yields 7.8–8.1%, the full units register, this month's sales, completed 2021 | — |
| — | "Welcome to Azimuth. Complexity into clarity." | held on page three | — |

**Budget options** (2-bed, DAMAC Hills): 1.5M → 4 here; 1.8M → 13; 2.0M → 19. **1.8M / 13** is the
recommendation: enough for the list to be worth scrolling, still a shortlist, and a different number
from video 01's 37 so the two do not feel like one video twice.

Beat 1 runs before the map beats deliberately: the app shades the whole city by nationality first,
then the client narrows to one district. Beats 2–4 are all amenity chips, which clear the building
selection — so they sit before the filter and the building, as in video 01.

## Open items

- **The residents key.** `NAJMA_RESIDENTS_KEY` still holds the literal placeholder. Beat 1 cannot be
  probed or filmed until `node scripts/set_residents_key.js` has been run. Everything from beat 2 on
  is verified against the live app with the client key.
- **"M-0"** on the supermarket card's opening-hours line — raw data, not a schedule. Reported to the
  Azimuth session 18 Sep with the evidence; either it is fixed, or the video does not open a
  Spinneys card and the schools card carries the clickable beat alone.
- **Nationality on a client surface.** This video films the private residents page as Naj's tool.
  Publishing the footage is covered by Kendall's 17 Sep decision (methodology §11); the page itself
  is still behind `rk` and Q040 stays `held` until a client-facing screen exists.
- **A real exterior of Carson** would improve page one and page two. DAMAC publishes none; a
  developer-supplied render through a broker channel would be the honest route.

## Source of truth

Deployed worker `C:\Dev\azimuth-worker-dewa`, branch `dewa-screens`. Capture and cut as video 01,
with a `DISTRICT` / `HERO` / `BUDGET_HI` switch in `scripts/demo_capture.py`.
