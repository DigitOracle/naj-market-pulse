# najma.duckdb — the truth store

*Started 8 Sep 2026. Built by `scripts/graph_build.py`. Schema 1.1 (role rule, aliases, canonical view). Golden gate: `scripts/graph_golden_check.py` — 7 pass · 0 fail · 1 known-open (Symphony) on 9 Sep 2026.*

One database, three kinds of table. Every script that learns a fact writes here; the Worker reads exported views. Nothing else is the source of truth any more — the JSON files under `data/board` and `data/enrich` become inputs and caches.

## Node tables

| Table | Rows (8 Sep) | Key | From |
|---|---:|---|---|
| `building` | 64,230 | `duid` (DXB-…, persistent) | identity resolver (`data/identity/resolved`) |
| `sub_community` | 1,834 | `sub_id` | DLD land registry clusters |
| `plot` | 1,254 | `plot_no` | DLD land registry, footprint-bound |
| `project` | 5,608 | `project_key` | unit-mix cards (DLD units register) |
| `sheet_project` | 37 | `sheet_key` | developer availability sheets + fallback registry |
| `developer` | 14 | `dev_key` | Kendall's segment table |
| `amenity` | 2,730 | `amenity_id` | KHDA, ESE, DHA, RTA, DM malls, Overture/OSM parks and beaches — with `access` |
| `water_body` | 127 | `body_id` | Overture water, named where OSM knows the name |
| `district` | 41 | `slug` | districts_geo |

## Edge tables

`building_waterfront` (building → water body, distance), `sub_community_amenity` (place → amenity, relation `NEAREST_TO` or `NEAREST_PUBLIC`, `distance_m`, `access`), `project_developer`, `sheet_project_register`. Relationship type and measurement are stored, never just "nearest".

## The ledger: `evidence`

Append-only. 80,174 rows on the first run. One row per claim: `entity_type, entity_id, attribute, value, role, source, source_record_id, method, confidence, score, dist_m, inside, captured_at, status, schema_version, resolver_version, valid_from, valid_to, run_id`. Statuses: `DISCOVERED`, `ACCEPTED`, `REJECTED`, `SUPERSEDED`, `MANUALLY_VERIFIED`. Rows are never updated or deleted; a correction is a new row plus a status change on the old one. A rerun appends only claims it has not seen (`evidence_id` is the claim's own fingerprint).

## Policy tables

- `source` — the registry: 20 sources with publisher, dataset, authority level, scope.
- `source_authority` — the matrix: weight 0–100 per (source, attribute). DLD units register is 100 for `name`, `plot`, `units`; Google Places is 95 for `tenant` and 25 for `name`; OSM is 90 for `name`, 85 for `water_name`. Resolution picks the highest weight, then confidence, then spatial distance. `v_name_by_matrix` shows what the matrix would choose for every building with competing name claims.
- `golden` — the test set: 160 rows seeded from the beach poll (with Naj's answers as they arrive), the park poll draft, every DA-AUD-004 flag, and the known errors (Seacliff office geocode, W Residences → Orra Harbour footprint, Masaar → JVC, Symphony ×3, Building 4 → Apple Office, Chelsea waterfront). A resolver change is not accepted until every `VERIFIED` and `PASS` row still holds.

## Views for the Worker (exported to KV, never queried live)

`v_building_identity`, `v_unresolved_towers`, `v_conflicting_names`, `v_place_card`, `v_name_by_matrix`.

## Rules

1. Write facts as evidence rows first; derive node columns from them. Never write a name straight onto a building.
2. Building names are `BUILDING_NAME` role only. Tenants and amenities are edges, never names.
3. External identifiers (DLD, DM, Makani, OSM, Overture GERS) go in `evidence` as `attribute='identifier'` with the namespace in `source`; the DUID never encodes them.
4. Temporal: `valid_from` / `valid_to` on every evidence row; a rename is a new row.
5. Bilingual: Arabic and English are separate rows of the same attribute, never transliterated into one field.
6. Kùzu (Cypher) is a projection of the gold tables, added only once the golden set passes cleanly.
7. Hand rejections live in `data/names/dev_bindings.json` → `rejected_by_hand` (district, project, why, when). `build_projfacts.py` never uses a rejected name as an alias and `map_prices.py` blanks the developer on a rejected (district, name). A rejection is a MANUALLY_VERIFIED negative: record it there, never by editing an output file.
8. Place sources (Overture places, Google Places) never supply a BUILDING_NAME; their name claims are kept in the ledger as `TENANT` / `REJECTED`.

## Run

```
python scripts/graph_build.py            # rebuild nodes and edges, append new evidence
python scripts/graph_build.py --fresh    # schema change only — drops the ledger
```

The daily refresh runs it after `remaining_inventory.py`. After any binding or resolver change run, in order: `build_projfacts.py` → `build_search_index.py` → `map_prices.py` → `graph_build.py` → `graph_golden_check.py` (exit 1 stops the chain). Raw DLD/DM exports the scripts read live in `data/raw_downloads/` (moved out of Downloads on 9 Sep 2026).

## Step 4 — the graph query layer and the app (started 9 Sep 2026)

- `scripts/graph_kuzu.py` projects the gold tables into **Kùzu** (`data/graph/najma.kuzu`, rebuilt from scratch each run, 3 s): nodes District, Building, SubCommunity, Plot, Project, Developer, Amenity, WaterBody; rels IN_DISTRICT, NEAREST (kind, relation, distance_m, access), WATERFRONT (cls, distance_m), DEVELOPED_BY. Smoke queries and counts land in `kuzu_stats.json`. Cypher is for questions; DuckDB stays the truth.
- `scripts/graph_export.py` runs the gate first (exit 1 = nothing exported), then writes `canonical_names.json` (the matrix winners that differ from the resolver, 272 on 9 Sep) and pushes three KV views: `graph_place_cards`, `graph_unresolved_towers`, `graph_identity_summary`.
- `scripts/apply_identity.py` now reads `canonical_names.json`: a matrix winner from a source weighted >= 90 (DLD, OSM, register) replaces the resolver's display name; pinned names still win; nothing is deleted. First full write 9 Sep 2026: 41 districts, 6,899 named on the twin, 206 matrix corrections, 52 newly named, 1,183 replaced (mostly the register being more exact than the survey name), 82 KV pushes ok.
- Order after any change: `graph_build.py` -> `graph_golden_check.py` -> `graph_export.py` -> `apply_identity.py <slugs>` -> `graph_kuzu.py`.
- DuckDB is single-writer. The daily refresh's `graph_build.py` holds the file for several minutes; the gate and the export wait for the lock (20 x 30 s) rather than fail.

## Field answers as golden rows (9 Sep 2026)

Naj's poll answers are the field truth. `poll_score.py` writes `data/board/<poll>_answers.json`; `graph_build.py` seeds them into `golden` (beach01: 10 beach claims; waterpark01: 2 water, 3 beach, 5 park claims) with status PASS / FAIL / FIELD: not sure / PENDING_FIELD. The gate checks every PASS row the way the claim was made: from the priced record's own point against the amenity register, access class must agree, distance within 35 percent (R8 beaches, R9 parks). Water rows are held for an R10 against `building_waterfront`. 9 Sep: 8 pass, 0 fail, 1 known-open (Symphony).

## Raw sources (9 Sep 2026)

`scripts/datadubai_pull_all.py` pulls every dataset the data.dubai metadata API lists (592 on 9 Sep, against 265 in the 6 Sep catalogue export) into `data/raw_downloads/dd/` with `MANIFEST.json` (id, rows, columns, bytes, fetched). Dubai Statistics Center tables live there too (the DSC site now redirects into data.dubai). Nothing in `dd/` is truth; it is the evidence shelf the loaders read from.

## DM geography (9 Sep 2026, `scripts/graph_load_dm.py`)

- `dm_community`: the 224 official community polygons (extract 15 Aug 2026), with English and Arabic names and community numbers. Every building and every DLD sub-community is located by point-in-polygon; `district_dm_community` / `v_district_crosswalk` map the 41 market districts to the legal communities (Arjan = Al Barsha South Third, Damac Hills = Al Hebiah Third, JLT = Al Thanyah Fifth ...). Evidence rows: attribute `dm_community`, role LOCATION, source `dm_community`.
- `dm_address`: the register published as "address" on data.dubai is the **DET business-licence address register** (one row per licensed premises: Arabic address line, DM plot id "346-451", community number, floor, unit; coordinates mostly empty), not a residential unit register. Loaded as businesses per plot (`dm_address_parcel`, `building_parcel_dm`, `v_plot_businesses`), position taken from the DLD plot when the row has none. Evidence: `plot_no` and `businesses_addressed`, source `dm_address`.
- Run order: graph_build.py → graph_load_dm.py → graph_golden_check.py → graph_export.py → apply_identity.py → graph_kuzu.py.

## Villas are places, not names (9 Sep 2026, `scripts/villa_labels.py`)

Low-rise buildings (three storeys or under, or below 12 m) are 65% of the twin (41,734) and 38,872 of them had no name. They never will: a villa is known by its community, cluster and plot. The rule gives each a KIND (villa / townhouse by footprint area, 160 m² threshold, area from the district footprints) and a PLACE LABEL: inside a DLD cluster → "Juniper villa, Damac Hills 2" (9,637 buildings, confidence 0.8); otherwise the official DM community → "Al Hebiah Third villa" (29,235, confidence 0.6); the plot number joins when DM's parcel layer arrives. Stored as `villa_label` + evidence (attribute `place_label`, role LOCATION, source `resolver_villa_rule`), carried onto anchors by `apply_identity.py` as `kind` / `place_label` / `place_basis` / `cluster_name`; the twin panel falls back to the place label when a building has no name. First run: 22,250 villas, 16,622 townhouses. The unnamed problem is now the 75 towers and ~18,000 mid-rise buildings.

## Step 5 - Dubai Municipality permits and projects (11 Sep 2026)

Two loaders add the municipality's own record of what is being built. Both are append-only for the ledger (tables are re-landed
from the file, evidence is never deleted; a superseded row is closed with status SUPERSEDED and a valid_to).

- `scripts/graph_load_dm_permits.py` - Building Permits Applications register (data.dubai, 2026-08-31 extract, 778k rows, 114k parcels)
  -> `dm_building_permits` (raw), `dm_parcel_permits` (per parcel: permits, last permit, last NEW-BUILDING permit, building type,
  buildings and area permitted, construction_signal = new-building or addition permit delivered in the 30 months before the extract),
  evidence source `dm_permits` (permit_last, new_building_permit, permit_building_type, permit_building_count, permit_total_area_sqm,
  construction_signal), views `v_plot_permits`, `v_building_permits`, `v_construction_signal`.
- `scripts/graph_load_dm_projects.py` - Project Information (481k projects: parcel, Open/Closed, permit / work-start / expected /
  completion dates, contractor, consultant) + Project Building Information (209k DM buildings with construction stage and cost) +
  Building Floor Level Information (4.2M floor rows, 484k DM buildings) -> `dm_project`, `dm_project_building`, `dm_building_floor`,
  `dm_building_floors`, `dm_parcel_projects`, evidence source `dm_project` (construction_status, construction_stage, expected_completion,
  project_completed, contractor, consultant, dm_floors, dm_units, dm_main_usage), views `v_parcel_projects`, `v_building_construction`.

Rule learned the first time round: an OPEN DM project alone is not construction - towers keep adjustment projects open for years
(502 of our 464+ linked Marina/Business Bay buildings had one). Works are called only on a construction STAGE, or on a new-building
permit delivered within 3 years while the project is open; otherwise the row is "open project - works not evidenced" and DISCOVERED.

Coverage limit: our footprints reach DM parcels only through the DET address register (721 buildings) and the DLD plots (1,156).
Widening needs the DM parcel polygon layer (requested from data.dubai) or DM building_id coordinates; until then the 124k-parcel
roll-ups are queryable by parcel, and 14,851 parcels citywide carry a stage-evidenced "under construction".

Parcel key: community x 10000 + plot. Permits/projects '2621465.00' -> 2621465; plot.parcel_id '6830847.00'; building_parcel_dm '392-434' -> 3920434.
