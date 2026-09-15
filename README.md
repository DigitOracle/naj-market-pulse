# Najma نجمة — Market Pulse

Dubai property market pulse + content engine for Naj, built ONLY on official data.
**Read [HANDOVER.md](HANDOVER.md) before changing anything** — it carries the sanity-gate
doctrine, the data schemas, and the licence rules. This README is the operating guide.

## The loop

```
DLD open data (official gateway / manual CSV)          MEED corpus (FIXED snapshot,
        │                                              via Digital Abbot Cloud API)
        ▼                                                        │
scripts/fetch_dld.py  ── weekly, read-only ──► data/*.csv        │
        ▼                                                        ▼
scripts/build_pulse.py ── sanity gates, FAIL CLOSED ──► public/pulse.json
        │
        ├─► dashboard (public/mockup.html → production page)
        ├─► weekly Azimuth WhatsApp update to Naj
        └─► content angles → HeyGen podcast · LinkedIn · Instagram
```

## Cadence: Windows scheduled tasks on this PC

The weekly GitHub Action was abandoned on 1 Sep 2026 (the DLD gateway does not serve cloud IPs; the governed API answers
UAE addresses only), so everything runs from scheduled tasks, each a thin `.ps1` over `scripts/refresh_runner.py`:

| Task | When | Chain | What it does |
|---|---|---|---|
| `Najma_Daily_Refresh` | 06:30 daily | `daily` | DLD windows → pulse (+ `cityLife`) → ingest → heat map → listener check → availability + volume check → DNA chain → cards → truth store → golden gate + graph export → governed-API contract (quick) |
| `Najma_Avail_Sweep` | 2-hourly 07:00–21:00 + on resume | `sweep` | new sheets → volume check → index, remaining, unit mix, search (only when something changed) → twin audit → acknowledgement to Naj (only when something new was parsed) |
| `Najma_Gov_Weekly` | Fridays 03:00 | `gov-weekly` | governed-API pull → load → contract (full duplicate scan) → realness gate → lake publish → the eight joined portal registers, every part → portal manifest contract → register key joins |
| `Najma_Edge_Backup` | 02:30 daily | `edge-nightly` | Azimuth's edge-only key–value state copied to `data/edge_backup/` (14 days) |

The register **back-fills**, so each daily run re-pulls its whole window and dedupes — late registrations are caught,
not missed. Dry-run any chain with `python scripts/refresh_runner.py <chain> --dry`; run single steps with `--only`.

These tasks run only while Kendall is signed in to a laptop that sleeps. Moving them to an always-on machine inside the
UAE is [docs/ALWAYS_ON_HOST.md](docs/ALWAYS_ON_HOST.md): task definitions exported to `ops/scheduled_tasks/` with a
restore script that registers them to run with nobody signed in, and pinned packages in `ops/requirements-host.txt`.

## Contracts and the run ledger (Data Spine Phase 1, 13 Sep 2026)

Every failure in the 8–12 Sep handovers was silent: a pager that wrapped to record 1 and doubled a third of the rows,
a brochure that pushed 48 units off the board, a refresh that ignored exit codes. So:

- **Run ledger** — every chain writes `data/runs/<date>/<chain>_<time>.json` (each step: status, exit code, seconds) and a
  line in `data/runs/runs.jsonl`. `python scripts/run_ledger.py` lists the last runs. A step whose inputs failed is
  **skipped**, never run on stale files. Pushes to the Workers (`ingest_pulse`, `push_heatmap`, `push_cards`,
  `push_twin_audit`, `group_links`) get one more try after 30 s: a sweep that starts as the laptop wakes can meet a closed
  connection. The same failure again within 6 hours is logged but not re-sent (`data/runs/alerts_sent.jsonl`).
- **One line to Kendall** — when a step fails, a feed is held or something needs an eye, `notify_owner.py` sends one
  WhatsApp line through meeting-capture `/owner_note` (never to Naj). Until that route answers, alerts wait in
  `data/runs/alerts_pending.jsonl` and leave together on the next successful send.
- **Contracts** — a feed that breaks its promise is **held**, not published:
  - `gov_contract_check.py` — governed API: landed vs loaded vs in-table rows, duplicates (weekly), shrink under 80% of
    the last accepted load, freshness. Held datasets leave `v_gov_usable` (see `gov_contract`, `v_gov_contract_holds`).
  - `portal_manifest_check.py` — data.dubai downloads: every part of the newest extract on disk, or the register is
    `partial` (`data/raw_downloads/dd/CONTRACT.json`). The pull now takes one format per part (CSV), not CSV + JSON.
  - `avail_volume_check.py` — a sheet reading with under half the units of the one it replaces is held in
    `data/avail/_held.json` until a later sheet agrees; `build_avail_index.py` skips held readings.
- **Clean views only** — untestable government datasets now get pass-through `g_` views, so `v_gov_usable` never names a base table.
- **Edge copy-back** — `edge_backup.py` keeps what exists only in Cloudflare KV (market record, feed history, polls,
  ledgers, chat ingest, her style photos). Credentials and rebuildable pushed assets are skipped on purpose.

Plan and reasoning: the Najma Data Spine deep dive (DigitAlchemy tree `Operations/Research/Najma_Data_Spine_DeepDive_13SEP2026.md`).

## The published store and two dates (Data Spine Phase 2, 13 Sep 2026)

- **Work in progress vs published.** Builders keep writing `data/graph/najma.duckdb`. After the golden gate,
  `graph_export.py` publishes the checked data into **`data/lake/`** (DuckLake 1.0: SQLite catalogue + Parquet) as one
  numbered snapshot, and exports from the lake. Readers (`build_city_block.py`, `graph_export.py`) attach the lake
  read-only and never wait on a builder. `python scripts/lake.py status | publish | expire`. Snapshots kept 30 days.
- **Two dates on register rows.** `register_versions.py` loads every DLD window file as versions:
  `lk_dld_transactions` carries `happened_at` (valid time) and `recorded_from` / `recorded_to` (the pulls that carried
  each version), in two series — `window` (the daily API pulls, one row per number) and `export` (manual CSV and
  year-to-date extracts, where multi-unit deals repeat a number). Views: `dld_transactions_now`, `transactions`
  (naj.duckdb's shape), `dld_rents_now`, `rents`. "As known at" = `recorded_from <= ts and (recorded_to is null or recorded_to > ts)`.
- **Window contracts.** A window pull under 85% of the last loaded one, or one missing more than 0.2% of known
  transactions, is **held**: not loaded, and the daily chain then skips `build_duck` and `build_pulse`, so yesterday's
  pulse stays live. The hold releases when the next pull agrees: its own vanishes are under the limit, or at least 80%
  of them are transactions the held pull lacked too (`lk_vanish_holds`). Found on the first replay: the 2 Sep manual pull
  (25,009 rows), and pulls on 3 Sep (79 missing) and 9 Sep (427 missing, all back on 10 Sep).
- **A short pull is pulled again (14 Sep 2026).** The 06:30 pull lacked 1,496 transactions and was held; the same windows
  pulled at 14:40 held all but one, and 99.8% of the portal register's copy against 95.0% for the morning pull (and 97.8%
  for the 13 Sep pull already loaded). `fetch_dld.py` now checks each pull against the transactions its last three pulls
  held and, when more than the contract's limit are missing, waits two minutes and pulls again, keeping the union.
- **Back-fill is real and large.** 8 Sep read 526 transactions on 9 Sep and 641 by 10 Sep (+22%); 3 Sep read 754, then 798.
  A "yesterday" figure is not final until the second morning.
- **Availability as intervals.** `avail_intervals.py` → `lk_avail_units` (first/last seen, prices, `left_after`, and
  `id_break_after` when a developer rewrote its unit ids) and `lk_avail_types`.
- **`naj.duckdb` is refreshed daily** (`build_duck.py` in the chain) — it had been frozen at 1 Sep while the DNA, board,
  project-facts and compare builders read it. It is now a derived cache; readers move to the lake over time.

## Identity and claims (Data Spine Phase 4, 13 Sep 2026)

- **Sales project names → registered `project_id`** (`identity_match.py`, daily). The DLD projects register names projects
  in Arabic (27 of 3,008 sales names met it); the buildings/units/land registers carry `project_id` with both English and
  Arabic names, so they are the bridge. Order: hand decisions (`data/identity/decisions.json`) → exact normalised name
  (unique, or disambiguated by area) → Splink 4 on the rest (name similarity, the numbers in the name, area; m-probabilities
  set from the register, u estimated by Splink) → accepted ≥ 0.95, review 0.50–0.95. First run: 2,992 of 3,008 names,
  142,792 of 142,844 named sales rows linked; 1 in review (`data/identity/review_tx_project.csv`); 15 are launches not yet
  registered. Lake: `lk_identity_xref`, `lk_project_alias` (English + Arabic), `lk_dld_projects`, `v_transactions_project`.
- **The register corrects the area aliases.** `data/identity/area_alias_evidence.csv` lists, per sales area label, the DLD
  area its projects are registered in; 44 labels disagree with `data/dld/area_alias.json` (City of Arabia is Wadi Al Safa 4,
  not 2 — 1,463 residential sales in the current window sit under the wrong area in the yield table). A merge-ready
  `area_alias_proposed.json` (31 changes) awaits Kendall's approval; nothing is applied automatically.
- **Metric registry + claims.** `metrics/registry.json` defines each pulse figure once (transcribed from `build_pulse.py`)
  plus the writing rules. `claims.py` turns every figure into a claim — metric, value, scope, window, sample, source,
  `settling_after` / provisional — in `public/claims.json` and `lk_claims`, and cross-checks the city figures against the
  lake (first run within 0.1%). Claims are not yet in `pulse.json`: they reach the Worker with the "cite only claims" guard.

## Register keys (Data Spine, 14 Sep 2026)

The 13 Sep audit found 556 of 579 downloaded portal registers never read, and the rest joined by name.
`register_joins.py` joins on the numbers the registers publish. It runs weekly in `gov-weekly`, after `portal_pull_joined` fetches
every part of the eight registers it reads.

| Job | Key | First run |
|---|---|---|
| `community` | DLD `lkp_areas.municipality_number` = the Municipality community number | 224 of 301 DLD areas; population 224 of 226, bus coverage 224 of 227, DEWA move-ins 99.9% on the number |
| `sales_projects` | the portal's copy of each sale (its id `group-procedure-year-serial` is ours `procedure-serial-year`) → `project_number` → `project_id` | 99.1% of current sales paired (price or size agrees); every paired sale reaches a community number through its register area; the register and `identity_match` agree on 102,464 of 102,472 rows |
| `parcels` | one parcel key, community × 10,000 + plot, from `6830847`, `6830847.00` and `683-847` | twin-linked parcels reaching the Municipality building summary: 9 → 513; plots 0 → 471 |
| `service_charges` | `project_id` | 674 of 694 projects; residential median 12 AED per sq ft a year (2019–2023 budgets; 2024 holds 5 projects) |
| `makani` | DEWA Makani number → Municipality entrance → nearest twin building within 50 m | 67% of Makani numbers on an entrance, 19% on a twin building |

Lake: `lk_community`, `lk_area_community`, `lk_txn_register`, `lk_project_number_names`, `v_transactions_register_project`
(`project_link` = register row, register name or name match), `lk_dm_buildings`, `lk_parcel_keys`, `v_twin_building_dm`,
`v_plot_dm_buildings`, `lk_service_charges`, `v_service_charge_rate`, `v_service_charge_latest`, `lk_makani_entrances`,
`lk_dewa_moveins_makani`, `v_building_moveins`, `lk_join_log`. A match rate under 80% of the last accepted run is held (exit 4).
The eight single-sale disagreements between the register and the name matcher are in `data/identity/register_vs_name.csv`.

- **Two-part registers.** The portal publishes transactions and DEWA customers in two parts; the 9 Sep copies held part 1.
  Re-pulled 14 Sep: 1,780,648 sales rows, 1,156,050 move-ins. `identity_match.py` now reads every part through
  `register_files`. The 14 Sep re-pull of units (3 parts) stopped on a 403 at part 3 and land registry on a reset, so both
  stay on their 9 Sep copies until the weekly pull succeeds.
- **One format per part.** The portal publishes a part in up to three formats (CSV, JSON, Excel). On 14 Sep the pull
  saved the Excel copy of the one-part buildings register as "part 2" (the same 256,468 rows; set aside in
  `dd/_superseded`). It now keeps CSV, else JSON, else Excel, and converts a part published only as a workbook. Nine
  registers from the 9 Sep pull still list a JSON or Excel copy as an extra part (address, commerce_registry,
  container_of_the_consignments, employment, food_health_certificate, licence, map_requests, marine_ridership,
  tradename); none feeds the joins, and a re-pull cleans them.
- **The entrance layer is cut at 256 MiB at its source** (124,244 points; `portal_manifest_check.py` already marks it). No
  open full copy exists: full Makani coverage needs the production-access request or a Dubai Municipality GeoHub application.
- **DEWA rows carry nationality and identity type.** The joins keep counts per Makani number and community only;
  nationality is handled by `dewa_accounts.py` below.
- **Not on her board.** Section 5 of `docs/GOV_DATA_METHODOLOGY.md` still decides what reaches the pulse.

## DEWA accounts (14 Sep 2026)

The DEWA customer register is the list of **active** accounts (1,156,050 in the 6 Jan 2026 extract, data through 4 Jan),
not a history of moves: people who left are absent, so counts by move-in year overstate recent growth. `dewa_accounts.py`
(weekly, `gov-weekly`) keeps each new extract once, stamped by the register's own `load_timestamp`:

- `lk_dewa_extracts`, `lk_dewa_accounts_building` (Makani number, community, use, move-in date; **no nationality**) and
  `lk_dewa_accounts_nationality` (residential accounts by community, nationality, move-in month).
- `v_dewa_new_residents_nationality` — newest extract, per community and move-in quarter, nationalities with 20+ accounts
  and their share (first load: 12,948 rows, 169 communities). Internal: Naj's targeting.
- `v_dewa_flows_community` and `v_dewa_flows_nationality` — arrivals, late additions and departures between consecutive
  extracts. Empty until DEWA publishes a newer extract; the portal says monthly, and its newest is still 6 Jan 2026.
  Tested on a synthetic earlier extract: planted arrivals, departures and late additions returned exactly.

Rules (methodology section 11): nothing below 20 accounts leaves the store, never nationality at building level,
nationality framed as where new residents come from in anything published or client-facing. We do not sell data;
attribution still applies on anything published.

**For the app's screens (14 Sep afternoon, Kendall's choices)**, `register_joins.py` jobs + `build_dewa_views.py`, weekly:
- `building_activity` → `lk_building_dewa_activity` → `data/board/building_activity.json`: TWIN colour modes with **no
  nationality**, for buildings with 20+ accounts (1,386): how fast towers handed over since Jan 2024 fill (211), residents
  against businesses, and move-ins in the last six months against the six before, judged against Dubai's own ratio (1.46)
  because both halves carry the active-accounts tilt (a flat threshold read 517 "more" against 74 "fewer").
- `resident_mix` → `lk_community_resident_mix`, `lk_community_resident_bands`, `lk_community_resident_regions` →
  `data/internal/community_resident_mix.json`: internal only, for Kendall and Naj. 137 communities, groups at 5%+ rounded,
  18 nationalities in the filter, and (15 Sep) `regions`: ten regions from `nationality_regions.py`, each with its
  countries at 1%+, nothing under 20 accounts shown (median 13 countries named per community). Never in a client link,
  card or answer.
- Both reach the app weekly (`gov-weekly`): `push_building_activity` → azimuth-2 `/img/building_activity` (public; no
  nationality; read back and compared), and `push_resident_mix` → `/ingest_private` (v152.1, 15 Sep), which stores it
  privately for the MAP Residents layer behind `RESIDENTS_KEY`. Account counts are removed before sending; the route
  reports communities and outlines stored, and the pipeline holds no residents key. Laptop preview of both:
  `data/internal/dewa_views.html` (market names from `lk_community_names`, the app's own map).

## Running locally

```bash
python scripts/fetch_dld.py        # optional: refresh data/ from the API (reads only)
python scripts/build_pulse.py      # gates + aggregates -> public/pulse.json
```

- `build_pulse.py` uses the **newest** `data/transactions-YYYY-MM-DD.csv` (pin with `PULSE_STAMP`).
- §9 known-good validation runs only against the pinned 2026-08-25 capture.
- MEED/handover blocks come from the local snapshot dir (`MEED_SNAPSHOT_DIR`) or are
  **carried forward** from the previous `pulse.json` — the MEED layer is deliberately static.

## Hard rules (from HANDOVER.md — do not relax)

1. **Every source passes a fail-closed sanity gate.** Quarantined sources never ship.
2. **Reads only, always.** No write to any endpoint, ever.
3. **No raw-row redistribution** — publish aggregates + attribution only. `data/` is gitignored.
4. **No individual is ever named** — brokers file is counts-only; Ejari rows singles-only.
5. **Every published figure carries source + period.**
6. Rent rows with `TOTAL_PROPERTIES > 1` are bulk leases — excluded (the 48.9% phantom-yield lesson).
7. The official DLD price index (RPPI) is **cite-only** — its terms exclude commercial repackaging.

## Secrets

| Name | Where | Purpose |
|---|---|---|
| `DAC_KEY` | local `.env` (gitignored) · GitHub Actions secret | Digital Abbot Cloud — MEED corpus freshness. Fails soft if absent. |
| `INGEST_TOKEN` (azimuth-2) | `C:\Dev\azimuth-listener-naj\.env` | pushes to Naj's Worker (`/ingest_market`) |
| `INGEST_TOKEN` (meeting-capture) | `C:\Dev\azimuth-listener\.env` | pipeline alerts to Kendall (`/owner_note`) |
| Cloudflare API token | `C:\Users\kwils\.cf_token` | nightly read-only key–value backup (`edge_backup.py`) |

## Attribution (must appear on every published surface)

> Source: Dubai Land Department (DLD) Open Data. Contains information from the Government of Dubai.
> Project data licensed from MEED Projects (GlobalData), served via Digital Abbot Cloud.
