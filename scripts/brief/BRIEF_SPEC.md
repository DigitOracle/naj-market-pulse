# THE BRIEF — "tell me what you're looking for" as the front door (spec v1, 30 Sep 2026)

Owner: Kendall (DigitAlchemy). Integrator: the "Rings" session (it holds the deploy queue for the azimuth-2 worker).
Why: a client of Naj's (Najjuko, a Dubai broker; the app is "Najma") asked "three options in JVC, one bedroom, AED 65K rent".
Answering it took a session of hand work: a sweep of every Ejari letting, a ranked list, tenant dossiers, a one-sheet of
ten cards, a LOD 100 map, a full pack. Kendall: that must be what the app's START does — pick from drop-downs, get the list,
then choose the outputs. Scalable: any district, rent or buy, any bedroom count.

## The flow
1. /start gets a new FIRST way in, above the five existing angles (NAJ_ANGLES in src/index.js, route /start ~line 3073):
   "00 · THEY TELL YOU WHAT THEY WANT" with the brief form inline (or a button to /brief).
2. The brief form (/brief): drop-downs / chips —
   - I'm looking to: Rent | Buy
   - Bedrooms: Studio | 1 | 2 | 3+
   - Budget: min–max (Rent: AED a year; Buy: AED) — sensible presets + free entry
   - Where: one or more districts (the app's district slugs + names), or "Anywhere in Dubai"
   - Home type: Apartment | Villa & townhouse | Any
   - Non-negotiables (chips): balcony · near a metro · pool · gym · parking · newer building (2020+) · schools nearby
3. Results (/brief?…): a ranked list of buildings (default 10), each row selectable, then OUTPUT buttons:
   Share this list (a link) · Individual PDFs · Compare 5 · Compare 10 (one-sheet + map) · Full pack.

## Contract A — search: GET /brief_api (client-key gated like the other client pages; see clientOk / CLIENT_PATHS in src/index.js)
Query: mode=rent|buy, beds=studio|1|2|3, min=<AED>, max=<AED>, areas=<slug,slug> (empty = all), type=apartment|villa|any,
       musts=<comma list of: balcony,metro,pool,gym,parking,new,schools>, limit=<n, default 10, max 50>
Response JSON:
{ "query": {…echo…}, "as_of": "<date of the evidence>", "source": "<file/key>", "total_matched": <n>,
  "results": [ {
     "rank": 1, "key": "<district>:<appId>" or "dld:<normalised DLD project name>",   // stable id for documents
     "name": "Binghatti Nova", "aliases": ["…also filed as…"], "district": "jumeirahvillagecircle", "district_name": "Jumeirah Village Circle",
     "app_id": 1490 | null, "building_url": "/building/<district>/<id>" | null,
     "evidence": { "basis": "ejari" | "dld_sales", "median": 63000, "q1": 60000, "q3": 68000, "n": 18, "n_new": 15,
                   "sqm": 59, "latest": "2026-09-28" },
     "verdict": "within" | "a_little_above" | "above" | "below",      // vs the budget (within = median within +3% of max and >= min)
     "musts": { "balcony": true|false|null, "metro": true|false|null, … },   // null = we do not know - never guessed
     "completeness": { "record": bool, "layouts": bool, "photos": bool },
     "why": "most lettings; full layout data" } ],
  "notes": ["bedrooms read from size - Ejari rarely records them", …] }
Ranking: buildings whose median is inside the budget first, then by evidence count (n), then completeness. Drop n < 3.
Evidence (rent): the live rent index img_rent_index (naj-market-pulse/scripts/build_rent_index.py; worker serves /img/rent_index)
— per building per bedroom band, contracts counted once, names that share contracts merged ("also filed as").
Evidence (buy): the sale data the HOMES panel's Buy mode already uses (find it in MAP_CHROME_JS: homeMatches / HB / map_prices),
or a per-building sale index built the same way from DLD transactions if the Buy data is not per building per bedroom.

## Contract B — documents: GET /brief_pdf?kind=onesheet|compare|dossier|pack&keys=<key,key,…>&mode=&beds=&min=&max=  -> application/pdf
Rendered in the worker with the Browser Rendering binding (env.BROWSER, @cloudflare/puppeteer - already used to render cards).
- onesheet: ALL chosen buildings (up to 10) as CARDS on ONE page (A4 landscape; A3 if needed): map number, name, small photo
  (or "photo to follow"), typical rent + middle half, lettings, typical size, 2-3 amenities, nearest metro. "For driving around."
- compare: the one-sheet + an overview MAP page: every chosen building as a simple LOD 100 block (footprint + height) or a
  footprint outline on its plot, numbered to match the cards, a few streets for context, north arrow, scale bar.
- dossier: one tenant dossier per building (see naj-market-pulse/scripts/build_building_dossier.py --audience rent for the
  approved layout: developer photo, what the budget gets you, the bedroom TYPES table from the units register where it exists
  else the registered lettings, amenities, views, plain English, no buyer material).
- pack: onesheet + map + a dossier per building + an appendix table of every matched building.

## Document layouts as approved by Kendall, 30 Sep 2026 (the reference build is scratchpad/build_pack11.py + map/make_map.py; match it)
- "Individual PDFs" is the primary output. Send each building on its own, NOT as a pack. Each has 3 pages:
  p1 the building: developer photo, name, facts, typical rent and middle half, what the budget gets you, amenities, where it is, nearby.
  p2 "Where it is": a single-building LOD 100 map (make_map.py with ONLY=n) showing the whole district in grey and this building in gold,
     PLUS the box "ESTIMATED ONE-BEDROOMS LEFT: about N of T" (see the next rule).
  p3 photos (tenant order: pool, gym, living room, bedroom, kitchen, lobby) and the bedroom-type layouts table.
- The one-sheet has 2 pages (A4 landscape): p1 all chosen buildings as cards; p2 the overall LOD 100 map, numbered to match.
- The estimate of bedrooms left. No government source records vacancy (confirmed by the DDA iPaaS session on 30 Sep: DEWA is per building
  (Makani), never per flat). So the figure is T minus R, rounded to the nearest 10, where T is the flats of that bedroom count in the
  Land Department units list and R is the tenancy contracts of that count running today in the Ejari register. Always label it
  "an estimate, not a count" and explain that owner-occupiers and unregistered renewals are included, so the real number is lower.
  Never state it as flats available. The one-sheet card carries only the qualitative line "Still filling: most of its 1-beds have
  no running tenancy on the government register*".
- Budget verdicts (Kendall 30 Sep; this REPLACES the +3% rule in Contract A): "within" means from the minimum up to the maximum, strictly.
  "a little over budget" means up to 5% over; "above" means more than that. Within buildings are listed first.
- Where the "left" estimate comes from (Kendall 30 Sep): KV img_beds_left_<district>, built by the DDA session from the full Ejari
  register plus the Land Department units register. The fallback is the app's gated tenancy path. Publishing the key needs Kendall's go.
- There is one estimate function (estimateLeft in src/brief.js), used by both the list and the PDFs. The "Still filling" card line shows only
  when (T-R) > T/2. The PDFs never print "about 0".
- /start heading reads "Six ways in"; 00 comes first. The Full pack takes at most 10 buildings.
- Header image: Najjuko leaning on the Najma N, from Kendall's still with the background removed
  (naj-market-pulse/data/brand/najjuko_with_n_cutout.png). Header 122 px tall, image 112 px. The one-sheet header image is 68 px.

## Kendall's changes after seeing v275 live (1 Oct 2026, ~04:00) - built as v277
- The way in starts simple: the "00" card is two buttons only, THEY WANT TO RENT / THEY WANT TO BUY. /brief is then one question per
  screen (bedrooms → budget → where → must-haves, skippable). Home type and how-many are no longer asked (Any, 10; "Show 20 / 50" on results).
- The register "left" estimate is OFF the client face (the "Still filling" card line, the page-2 ESTIMATED LEFT box, the results-row box).
  Kendall: "this isn't helpful". estimateLeft() and the API field stay, unused on screen. In its place: developer availability from the
  WhatsApp developer-group sheets (the avail pipeline) where a building has one; otherwise nothing.
- Blocks needs a way in: a "Blocks" button on /map, "See them in blocks" on the Brief results (gold = the ticked buildings), a link on
  each building page.
- v278, Kendall's GO (1 Oct, ~04:30): "map, zoom into a district ... stay in that format with the blocks until I'm ready to zoom in ...
  everything is in blocks when I first go into the twin, then when I go into a particular area it automatically loads massing. I still
  want the super high level of detail (the Palm: every single building) but not that super fast transition." So: /map no longer
  auto-jumps to the twin at district zoom; the district's blocks appear in place; the detailed twin loads on tap, close zoom or a
  "Detail" button, opening at the same camera; the twin itself shows blocks first and streams the detailed tile in.

## Rules every client document follows (hard - each one comes from a past incident or an explicit Kendall instruction)
- Footer ONLY: "Curated by Najjuko · Dubai Decoded" + WhatsApp symbol + "+971 56 548 4397". Najma logo in the header
  (C:\Users\kwils\OneDrive\Desktop\DigitAlchemy_31MAY2026\Brand_and_Legal\Logos\Najma_Logo.png; a cropped 189x360 copy is at
  C:\Dev\naj-market-pulse\data\brand\najma_logo.png).
- Photos and amenities ONLY from the developer's own project page, credited under each picture. Never a listing portal.
- A building's name must agree with the record. (JVC footprint 1503 is Binghatti Amber: Kendall confirmed it on 30 Sep, and the
  records have been corrected through the hand decisions in data/identity/decisions.json.)
- Listing limits: results go up to 15% over the top of the budget and down to 10% under the bottom; anything further out is not listed.
- Plain English on the client face; sources in small print where used. No walking or drive times - straight-line distances only.
- Rent evidence is "what homes here actually let for" - never availability; say availability is confirmed with the leasing team.

## Photos / amenities store
naj-market-pulse/data/brand/buildings/<district>_<id>/brochure.json (+ photo files) — shape:
{"name","developer","source_url","retrieved","amenities":[…],"photos":[{"file","caption","source_url"}],"plans":[…]}
Published to KV as img_brochure_<district>_<id> (the JSON, with photo keys rewritten) and img_brochure_<district>_<id>_<file>
(the images), via POST /ingest_market like every other img_* key (see scripts/build_avail_index.py push()).

## Engineering rules
- Worker: C:\Dev\azimuth-worker-dewa, branch dewa-screens, live at v274 (e5fbaec). NEVER edit that checkout. Make your own
  worktree from origin/dewa-screens, junction node_modules (cmd //c "mklink /J <wt>\node_modules C:\Dev\azimuth-worker-dewa\node_modules";
  remove with cmd //c rmdir before git worktree remove). Put ALL your logic in YOUR new module file; the only change to
  src/index.js is an import line plus a clearly marked route dispatch (the integrator merges those).
- Tests in test/*.mjs, run with node test/run_all.mjs (all must pass), worker.fetch harness (see test/test_v274_rent_mode.mjs,
  test/test_v186_floor_stack.mjs), and a NEGATIVE CONTROL actually run. Any browser JS you ship must parse (node --check the
  served scripts) - a broken script blanks the page on phones.
- Build and test ONLY: no git push, no deploy, no production KV write, no message to anyone.
