# Dubai Land Department exports — deep dive (6 September 2026)

What Kendall downloaded on 4–6 September, what each file actually contains, what it fills in the knowledge graph, how it joins, and what it cannot do. Every claim below was measured on the files with DuckDB, not read off a portal page.

## The digital thread (measured, not assumed)

```
units.parent_property_id  ==  buildings.property_id          1,260,968 of 2,375,712 units join (the rest are villas / land / unregistered stock)
buildings.project_name_en ==  transactions.building_name_en  the tower name, same register spelling (PRINCESS TOWER, SULAFA TOWER ...)
buildings.project_name_en ==  rent_contracts.project_name_en same key on the Ejari side (filled for 15 % of contracts, the towers that matter)
buildings.parcel_id       ==  building_permits.parcel_id      49,537 parcels (Dubai Municipality permits on the same land)
```

So one building row carries: its name, area, parcel, land number, flats / offices / shops, floors, car parks, lifts, pools (buildings table) → every registered unit with rooms type, size, floor, parking (units table) → what sold and for how much by type (transactions) → what it rents for by type (Ejari). That is the "N units across M asset classes" card, plus levels per type, plus price, rent and gross yield per type, from the register alone.

**Proof:** PRINCESS TOWER (property 1753409401, parcel 3920192): buildings table says 763 flats, 89 floors; the units table yields 771 units — 286 × 1 B/R (floors 5–90), 298 × 2 B/R, 148 × 3 B/R, 22 × 4 B/R (80–90), 9 × 5 B/R (91–96), 8 shops. Transactions give median AED 1.00 M (1 B/R) … 6.74 M (5 B/R); Ejari gives AED 85 k … 450 k; gross yield 8.5 % → 6.7 %. Sulafa 702 flats / 703 units; Marina Pinnacle 764 / 772; Elite Residence 697 / 700; The Torch 676 / 682. The two tables agree to within the shops.

**What does NOT join:** `building_floor_level_information.building_id` is not the DLD property id (46 hits in 483,923), not the parcel (0), not the permit application or project number for the same parcel (tested on three Marina towers: wrong buildings). It is a Dubai Municipality building id; it needs a DM building master (Makani / building register) to bridge. Not needed any more: the units table gives units per floor directly.

## 1. units_2026-09-04 (three CSV parts, 2,375,712 rows) — THE UNIT REGISTER

**Grain:** one registered unit. `property_id` (unit), `parent_property_id` (building), `grandparent_property_id` (plot / master), area, master project, project, `rooms_en` (Studio, 1–6 B/R, PENTHOUSE, Office, Shop, Single Room), `floor`, `unit_number`, `actual_area`, balcony area, common area, `unit_parking_number`, parking allocation type, freehold / leasehold flags, parcel, land number, municipality number and zip, `is_registered`, creation date.

**In the modelled districts:** 474,534 units in 2,483 buildings (Marina 409 buildings / 64,158 units; Business Bay 310 / 83,367; Downtown 215 / 36,785; JVC 565 / 99,550; JLT 186 + 81 / 49,843; Palm 172 / 22,810; Motor City 120 / 17,843; JVT 91 / 19,922; Al Wasl 126 / 10,944; Sobha 139 / 10,982; Jaddaf 94 / 37,004; Dubai Islands 167 / 21,326).

**What it fills:** units by type per building (the true mix, not a lower bound), median size per type, the floors each type sits on (min–max and count of levels), parking allocated per unit, freehold status. Rolled up by `scripts/dld_units_buildings.py` → `data/dld/units_buildings_<slug>.json`.

**Cannot:** name a building whose `project_name_en` is blank (Marina: 225 of 409 buildings, mostly older stock and podium parcels — those still have parcel and land number), or place a building on the map (no coordinates). Binding to a footprint is by name, through the transactions bindings.

## 2. buildings_2026-09-04 (CSV, 256,441 rows) — THE BUILDING REGISTER

**Grain:** one property of type Building (towers, villas-as-buildings, podiums). `property_id` (= units.parent_property_id), `parent_property_id`, project, master project, area, parcel, land number, building number, **flats / offices / shops** (filled for ~3,500 buildings, the multi-unit stock), floors, `bld_levels`, built-up and common area, car parks, elevators, swimming pools, freehold / leasehold, creation date.

**What it fills:** the asset-class split and building facts (floors, parking, lifts) as the register states them. Marina: 154 towers with counts — Marina Pinnacle 764 flats, Princess 763, Sulafa 702, Elite 697, Torch 676.

## 3. transactions_2026-09-04 (two CSV parts, 1,776,930 rows, 2019 → 4 Sep 2026)

**Grain:** one registered transaction. Sales 1.36 M · Mortgages 350 k · Gifts 66 k. Property type: Unit 1.27 M, Villa 308 k, Land 158 k, Building 37 k. Rooms: Studio, 1–5 B/R, Office, Shop. Registration: Existing 1.13 M, Off-plan 646 k. Identity columns: area (258), master project, project (3,405), **building_name_en (5,025)**, nearest metro / mall / landmark, parking flag, procedure area, actual worth, price per m².

**What it fills:** the register's name for 1,887 buildings with ≥3 unit sales in our districts, bound to footprints by name match (548) then place geocoding under a tight gate (609; 730 still unbound, mostly off-plan schemes with no built footprint yet). Sold-by-type per building with median size and price per type. Asset classes from usage. Nearest metro / mall / landmark.

**Cannot:** give total units (the units table does now) or coordinates.

## 4. rent_contracts_2026-09-04 (eight JSON parts, ~1.04 M contracts each, 2021 → 2026)

**Grain:** one Ejari contract line. Sub-type = bedroom type; project filled for 15 % (the towers); annual amount, actual area, start / end, new vs renewal, usage, nearest metro / mall / landmark.

**What it fills:** median annual rent and size by type per project since 2024; new vs renewal share; gross yield per type when joined to sales (`dld_rent_buildings.py` → `rent_projects_<slug>.json`, 646 projects). Marina 2025 medians: studio AED 63 k, 1 B/R 95 k, 2 B/R 140 k, 3 B/R 200 k, 4 B/R 270 k.

## 5. building_floor_level_information_2026-08-31 (five CSV parts, ~4.2 M rows, 483,923 buildings)

One floor of one building with units on the floor and usage. Keyed by a Dubai Municipality building id that joins nothing in the DLD exports (see thread above). Parked; superseded by the units table's `floor` field for our purpose.

## 6. building_permits_2026-08-31 (two CSV parts, 1,556,283 rows)

Dubai Municipality permits: `application_id`, `project_no`, `parcel_id`, building count, area, permit date. Joins the buildings table on `parcel_id` (49,537 parcels). Use: construction activity on a parcel (renovation, additions) — a "what is being built next to you" signal, not a unit source.

## 7. land_registry_2026-09-04 (CSV / JSON / xlsx)

Plots: parcel, land number, area, master project, land type, registration. Bridge from parcel to master plan; profiling for the twin's plot layer is pending.

## 8. real_estate_permits_2026-09-04 (xlsx)

Trakheesi advertising permits by broker licence and brokerage. Use: check Najjuko's brokerage holds a live electronic-advertising permit before any sponsored or developer-tagged post. Not a building source.

## 9. residential_sale_index_2026-09-01 (xlsx)

DLD's official residential sale price index (monthly / quarterly / yearly; all / flat / villa). Use: the one macro line the feed can quote with the register's authority.

## 10. map_requests_2026-09-04 (xlsx, 82 MB)

Being profiled; likely site-plan requests by parcel. Recorded when known.

## 11. Dubai Municipality building_summary_information (CSV, 533,411 rows, 31 Aug 2026) — THE BRIDGE TO THE MUNICIPALITY

Downloaded 6 Sep from data.dubai (Housing and Buildings, dataset 459523). **Grain:** one municipality building record per permit revision (New / Permit Delivered / Completed / Expired). Columns: `building_id` (= the floor-level file's building_id, all 483,923 join), `parcel_id`, `community_no`, `project_no`, `permit_no`, `building_floor_height` (written "6B+ G +94 +1P +1R"), `typical_floors_count`, `building_height` (filled on 277 k rows, 0 on most towers), `no_of_lifts`, indoor / outdoor parking, `building_usages_english`, building type, status, permitted / completion / demolition dates, plot area, total area, `no_of_buildings_on_plot`, green flag.

**The join:** `DM parcel_id == DLD parcel_id` (both are community × 10,000 + plot). In our districts 4,829 of 20,209 DLD buildings meet a municipality record on the same parcel; 350 of 607 towers with ≥50 flats. Princess Tower: 6 basements + G + 94 + podium + roof, 13 lifts, 957 indoor parking, permit delivered, completed 2013; floor-level file lists residential on floors 1–94 (88 levels) and commercial on 1. Sulafa 4B+G+76; Torch 4B+G+84; Pinnacle 4B+G+72; Elite 4B+G+85.

**The gap:** communities under Trakhees / free-zone authorities are not in the municipality file: Palm Jumeirah (21 bridged), JVC (4), JVT (0), Dubai Islands (0). Those need the Trakhees building register if one is ever published. `scripts/dm_bridge.py` → `data/dld/dm_buildings_<slug>.json`, keyed by DLD property id; the card prints the permit line.

**Also on the catalogue (48 datasets, Housing and Buildings):** DM Projects Buildings Information (project / building refs, construction stage, cost), DM Building Permits Applications, DM Building Usages Lookup, DLD Lookup Dubai Community Areas, DLD Building and Property Project Records, DLD Registered Freehold Units, Real Estate Licenses / Offices / Valuators, Owners Association Service Charges, DDSE completed / under-construction building statistics. Anonymous download works (a login dialog appears but the file still comes).

## What is in the knowledge graph now

Nodes: **Area** (DLD area ↔ district slug) → **MasterProject** → **Project / Building** (DLD `property_id` ↔ footprint DUID, bound by register name) → **UnitType**.

Facts on Building × UnitType, each with source and window: `units` (units register), `median_sqm`, `floors_min / floors_max / levels`, `sold_units`, `median_sale_aed`, `median_rent_aed`, `contracts`, `gross_yield` = median rent ÷ median sale price, same type, same building.

Facts on Building: `property_id`, parcel, land number, flats / offices / shops, floors, car parks, lifts, pools, freehold, parking allocated, nearest metro / mall / landmark, first / last sale.

Card status after the 6 Sep rebuild: **571 buildings verified** from the register (units + types + levels), 288 partial (sales or rents but no register match yet), 23,384 placeholder (small footprints, villas, podiums, and named towers whose footprint has not yet been bound). Rule kept: a number without its source and window never reaches a card; where the register cannot say, the card says so and names the file that would fill it.

## Order of work

1. Bind DLD building names to footprints — done (548 by name, 609 geocoded; 730 unbound, mostly unbuilt off-plan).
2. Unit mix from the units register with levels per type — done, pushed (`unitmix_<slug>`, `unitmix_projects`).
3. Sales price and Ejari rent per type → yield — done, on the same rows.
4. Raise the bound share: the 225 unnamed Marina buildings in the units table carry parcel and land number; a parcel layer (land registry → footprint) would bind them without a name. Next.
5. Permits: check Najjuko's brokerage. Sale index → feed macro line.
