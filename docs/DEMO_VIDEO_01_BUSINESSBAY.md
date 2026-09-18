# Demo video 01 — "Business Bay, two bed, two million"

**Format:** 9:16 vertical · target 52s · client key (CLIENT_KEY tier, app pages only)
**Avatar:** HeyGen overlays Naj's twin on the finished screen capture. This document produces the
*screen* side plus the ask script and timings; HeyGen does the compositing.
**Grade:** the app already renders champagne-gold on black and needs almost nothing added — see
`data/demo/probe_bb_filtered.png`.

## Why Business Bay

Kendall asked for a decision between Business Bay and DAMAC Hills. Business Bay, on coverage:

| | Business Bay | DAMAC Hills |
|---|---|---|
| Amenities mapped | **197** | 11 |
| 3D district twin | **yes** (`najma_businessbay.gdb`, `Najma_Business`) | none |
| Buildings in `/img/map_prices` | **124** | — |
| 2BR at or under AED 2M | **37** | — |

*Later video:* a 30s DAMAC Hills film and nine cluster endings sit in KV
(`unreal_damachills_film30`, `unreal_damachills_c1..c9`), worker change committed as v161 on
`dewa-screens` but not deployed. Cinematic, not a data walkthrough — a different video.

## Keys — settled

One key opened everything until 17 Sep: `READ_KEY`, which also reaches the board, inbox, outbox,
ledger, and paths that message contacts and spend model budget. A frame showing that in a URL would
hand over Azimuth.

`CLIENT_KEY` (v155/v156, DA-AUD-005) is now **set and working**. It opens only `CLIENT_PATHS` and a
page opened with it strips its own BOARD and studio links — confirmed in the probe: the nav on
`/home` comes back with FIND, HOMES, PULSE, TWIN, MAP, PLANS, VS, CHARTS, TIME and no owner links.

Setting it was additive: `keyTier()` returns `"admin"` for `READ_KEY` and `"client"` for a client
value, `clientOk()` takes either, so every link already sent to a client kept working. The rotation
declined on 16 Sep was of `READ_KEY` itself and was never needed for this.

Two standing protections:

- `scripts/demo_capture.py` requests `/board` before filming anything and **refuses to run if it
  returns 200**, i.e. if it has been handed the owner key by mistake.
- Playwright records the **viewport only** — no address bar, tab strip or chrome — so no URL can
  reach a frame from this pipeline at all. A manual screen recording would not be safe the same way.

`scripts/set_client_key.js` sets the worker secret and the local variable to one generated value so
they cannot drift. It **overwrites** `CLIENT_KEY`, so once real client links are in the wild, add to
the comma-separated list by hand instead — the worker keeps every value alive and puts the first
into new links.

## The hero building — Peninsula One

Picked on data, not looks, and the reasoning matters: the flashiest towers (SLS 252m, Vision 195m)
are ultra-prime. Cutting to one of those right after a client says "my budget is two million" would
have the video contradict itself on the very beat meant to prove the app is honest.

**Peninsula One** (`peninsulaone`), from `/img/map_prices`:

| | |
|---|---|
| 2BR register median | **AED 2,000,000** — the client's budget, exactly |
| Bedroom ladder | studio 817k · 1BR 1.29M · 2BR **2.00M** · 3BR 3.73M |
| Rent ladder | 80k · 120k · 180k · 340k — so the brief's yield section has real numbers |
| Size | 525 units, 36 floors |
| Developer | Select Group — one of the 15 in the HOMES grid, so `/dev?d=select` carries on |
| Status | `verified` |

Runners-up: Peninsula Two (Select, 38fl, 1.69M), Elite Business Bay Residence (31fl, 1.62M),
Regalia (78fl, 921 units, 1.73M, no developer attributed).

## Verified controls

Probed live; not guesses. Output in `data/demo/probe_*.txt`.

**`/home` is a developer grid**, not the filter — "your 15 developers in five tiers". The Q074
filter panel lives on **`/map`**, which is what the bank meant by "HOMES filter panel on MAP and
twins". Beats 3 and 4 move to `/map`.

| control | id | range | notes |
|---|---|---|---|
| panel toggle | `#hh` | — | collapsed, reads "homes / set a budget ▾" |
| budget low / high | `#hlo` `#hhi` | 0–60 | **`hhi=14` → "from AED 250k to 2.0M"**, exactly the brief |
| bedrooms low / high | `#hblo` `#hbhi` | 0–6 | both to 2 → "from 2 to 2" |
| live budget label | `#hbv` | — | updates as the slider drags |
| live beds label | `#hbdv` | — | " |
| result | `#hres` | — | **"37 here · 1010 across Dubai"** |

Range inputs need an `input` event dispatched, not just a value set.

District is picked from the searchbox at the top of `/map` ("search a district, sub-community, plot,
school, hospital, mall, metro, developer…"); typing "Business Bay" offers it first.

Map labels are drawn by MapLibre to canvas, so they cannot be read from the DOM — the building data
comes from **`/img/map_prices`** (1,609 buildings: name, district, developer, units, floors, median
price per bedroom count, rents). `/img/` is keyless. Its Business Bay + 2BR + ≤2M count is **37**,
matching what the app itself displays — an independent check that the footage will tell the truth.

## Beat sheet

Measured off the cut of 18 Sep (`data/demo/raw/marks.json` plus the encoded part durations), not
planned. Total 66.6s.

| # | t | Avatar asks (client voice) | App does | Bank |
|---|---|---|---|---|
| 1 | 0:00–0:07.8 | "I'm thinking about Business Bay — what's it actually like?" | `/map`, type "Business Bay" in the searchbox, pick it; district draws, counts fill | Q067 |
| 2 | 0:07.8–0:11.8 | "What are the schools like round here?" | Schools layer on — 16 schools, 4 hospitals, 11 malls, 2 metro | Q028, Q029 |
| 3 | 0:11.8–0:16.1 | "And can I charge a car?" | EV charging layer — the ninth chip, 22 nearby, 5 in the community | **Q015** |
| 4 | 0:16.1–0:27.5 | "My budget's two million and I need two bedrooms." | Open `#hh`; drag `#hhi`→14, `#hlo`→0, `#hblo`/`#hbhi`→2. Both labels tick over live. | **Q074** |
| 5 | 0:27.5–0:30.5 | *(hold)* | `#hres` lands on **"37 here · 1010 across Dubai"** | Q098 |
| 6 | 0:30.5–0:45.4 | "So which one's the best?" | **"list them →"**, scroll the matches, pick **Peninsula One** off the end at the 2.0M ceiling; then click the tower on the map | Q096, Q048 |
| 7 | 0:45.4–0:54.6 | *(hold)* | The twin: flies to the tower, its card opens — 525 units, DLD unit mix by type with levels and rents, 36 floors, 558 car parks — and the camera orbits | Q038, Q039, Q051 |
| 8 | 0:54.6–1:06.6 | *(the close)* | **The three-pager**, 4s a page. Kendall, 17 Sep: *"that's like the gold"* | — |

Schools and EV sit ahead of the filter for a mechanical reason: clicking an amenity chip clears the
building selection, which would take the panel's onward links with it. Area questions first, then the
building, then the twin.

**AED 2.0M appears three times from two independent registers** — the filter result, the twin's DLD
unit mix, and page 1 of the PDF. Worth not cutting any of the three.

## The fly-through — pulled

`/img/videos` lists `unreal_businessbay_fly`, "20 s fly-through", live at `/video/` and keyless
(4,012,921 bytes). It was beat 2 in an earlier cut and is **out** (Kendall, 17 Sep).

It is daylight aerial against an otherwise black-and-champagne video. Grading got the canal to black
but the buildings stayed bright and the Burj lake still flared cyan — better, not fixed. Pulling it
buys 7s for the briefing to close on, which is the beat that sells.

`SPLICE_FLY = False` in `scripts/demo_capture.py` turns it back on. It is still fetched: good as a
standalone piece, and a good opener for the DAMAC Hills cinematic.

## The ask sheet for HeyGen

Five asks, in a client's voice — curious, unhurried, not a presenter. Each lands *before* the app
answers it, so the app is responding rather than illustrating.

| cue | ask |
|---|---|
| 0:00 | "I'm thinking about Business Bay — what's it actually like?" |
| 0:08 | "What are the schools like round here?" |
| 0:12 | "And can I charge a car?" |
| 0:16 | "My budget's two million, and I need two bedrooms." |
| 0:31 | "So which one's the best?" |

Leave **0:45 onward clean** — the twin orbit and the briefing close without narration.

**One line worth adding at about 1:03**, over page 3: the recent registered sales there are AED 2.24M
and 2.88M, both above the 2.0M the client named. That is a median-versus-latest gap, not an error,
and it is the most honest thing in the video — but it goes past unexplained otherwise. Something like
*"and here's what's actually been selling"* turns it from a snag into the point. If a closing line is
wanted instead, it belongs to Naj: *"That's yours to keep."*

## Beat 8 — the three-pager

`/r/<id>`, the v58 CLIENT BRIEFING page: *"a polished, client-safe page Naj builds from chat in
seconds ('report business bay for Ahmed') and forwards after a viewing. Snapshot frozen in KV (60d
TTL, unguessable id), no keys, no internal controls, satellite hero, every figure sourced."*

Sections: *The yield, honestly · What each layout actually sells for · Around the community · Who
lives here · What is being built here · Projects on the register.*

`/r/` is in `KEYLESS_PREFIXES` — confirmed live, `/r/<junk>` returns 404 not 401. **Outstanding:
Kendall to run the report for Peninsula One and send the link.** The id is an unguessable capability
URL, so the address bar stays cropped on this beat too (it is, structurally — Playwright has none).

## The avatar-safe zone

HeyGen drops the twin over the lower frame. **Keep the money shot out of the bottom 30%.** The
filtered map screenshot cooperates: panels and the `#hres` chip sit in the top third, pins in the
middle band, and the bottom is mostly empty map plus the nav strip, which the avatar can cover.

## Build pipeline

1. `scripts/demo_capture.py` — Playwright at 1080×1920, beats recorded with deliberate cursor
   travel. `probe` re-dumps the app's markup whenever it changes.
2. ffmpeg 8.0.1 cuts to the beat sheet and holds the money shots.
3. `demo01_businessbay_screen.mp4` → HeyGen for the overlay.

## Source of truth

Deployed worker is **`C:\Dev\azimuth-worker-dewa`, branch `dewa-screens`** — live v167 (`8c0d707`,
07:55 on 17 Sep). `C:\Dev\azimuth-worker` is stale at v154.7 and has no `CLIENT_KEY`.
