# The Twin Bible — what we learned building Dubai's building identity layer

*Najma / Azimuth digital twin. Started 4 Sep 2026. Every entry here cost something to learn: a wrong number
shipped, a name deleted, a tower drawn as a 9 m box. Read it before touching the identity or height pipelines.*

The rule for this file: **an entry only goes in when it has bitten us.** Theory belongs in the script docstrings.

---

## 1 · The architecture, in one line each

```
CAPTURE -> NORMALISE -> MATCH -> ENRICH -> VALIDATE -> KNOWLEDGE GRAPH -> AUDIT
```

| Stage | Script | What it must never do |
|---|---|---|
| capture | `acquire_identity.py`, `osm_heights.py`, `places_names.py` | invent a source, or bypass a portal's click-through |
| normalise | `name_roles.normalize()` | **judge**. It tidies a string; it never returns None as an opinion |
| classify | `name_roles.classify()` | let a source's rank decide a role |
| match | `resolve_identity.py` adapters | match on a centroid when the geometry disagrees (see §4) |
| resolve | `resolve_identity.resolve()` | let an ineligible role become a name at any confidence |
| write | `apply_identity.py` | overwrite a hand-pinned name, or delete anything |
| audit | `twin_audit.py` | report "named" as if it meant "known" |

**The knowledge graph is the destination of every accepted fact, not an optional extra script.** Anything discovered
by any source flows to the building entity or it does not count. This was NOT true until 4 Sep: `build_building_meta.py`
was invoked in the nightly job with a literal `goldensymphony` argument, and the whole DNA chain
(`build_developer_dna` → `build_board` → `build_projfacts` → `build_compare`) was not in the nightly run at all, so
captured availability sheets never reached the developer DNA. Both fixed; do not let either regress.

---

## 2 · Identity: roles, not blacklists

**The mistake.** The first resolver asked *"is 'Apple Office' good enough to replace 'B4'?"* and answered with a
blacklist. The blacklist never ends. It proposed **"Look Up Rooftop Bar"**, **"Primavera Dry Cleaning"**,
**"Dr. Michael Roger"** and a holiday-let ad — *"City Walk 1BR, Stunning Burj Khalifa view"* — as building names.

**The fix.** Ask what ROLE the string plays, then make precedence `(source, role)` rather than source alone:

```
BUILDING_NAME · STRUCTURAL_ID · PROJECT_NAME · PLOT_ID · ADDRESS      <- may be canonical
TENANT · VENUE · AMENITY · INFRASTRUCTURE · ADVERTISEMENT · FRAGMENT · PERSON   <- never, at any confidence
```

Google Places does not lose because Google ranks low. **TENANT loses because a tenant is not an eligible role.**

Rules that each came from a specific failure:

- **A point of interest fills a blank; it never replaces a survey name.** ("Building 4" → "Apple Office", "Building 6" → "Marriott International".)
- **Normalisation must not judge.** A single `clean_name()` that both tidied and rejected deleted **A1, B4, B5** from JLT — those are what the site plan calls those buildings. `is_weak()` marks them; nothing discards them.
- **A name written ON a polygon is a building name. A name on a POINT must earn it.** Treating both alike turned *"Dubai Gate 1"* into an AMENITY (the `gate \d` pattern) and *"Green Lakes 1"* into UNKNOWN — **553 real names lost in one run**.
- **Two tiers of building vocabulary.** "Centre" is both a building word and a business word. Only a STRONG word (tower, residence, plaza, palazzo…) rescues a string that also reads as a trade name — otherwise "Innovators Training Center" becomes a building.
- **Parent-name lifting.** "Jam Tower Car Parking" is an amenity, but it is evidence FOR "Jam Tower". Lift the parent, keep the original as amenity.
- **Grades mean provenance, not confidence.** 0.99 from a place search still does not make a restaurant a building name.
  `VERIFIED` = authoritative register only · `MATCHED` = survey record on the building · `STRUCTURALLY_IDENTIFIED` = site-plan or street identifier · `INFERRED` = a nearby POI, a lead not a fact.

---

## 3 · The metric: identified, not named

**"1,914 named of 17,090" is a meaningless KPI.** It averages Burj Khalifa with 13,929 bare 12 m villa footprints.
Report four numbers instead:

```
properly named (BUILDING_NAME)  ·  structural identity only  ·  address identity only  ·  UNIQUELY IDENTIFIED  ·  unknown
```

A villa has no name. It has *"Villa 32, Street 14"* or a Makani number, and that is complete identity.
Wiring OSM `addr:housenumber` as an **ADDRESS** attribute took JVC + Palm from 9.2% → **17.0% uniquely identified**
overnight, without finding a single new "name".

---

## 4 · Heights: the OSM 3D scheme, and why centroids fail

**This cost three failed attempts on 4 Sep. Read it before writing any height matcher.**

OSM splits a tall building across **two different objects**:

- a **named outline way** — carries the name, and very often a *podium* floor count
- one or more **unnamed `building:part` ways** — carry the **real height**

Worked example, JLT:

```
our footprint "Lake Shore Tower"   1,457 m2
  cand A  h=9.4    name="Lake Shore Tower"  area 1457  cover 1.00  share 1.00   <- the outline, tagged 2 levels
  cand B  h=165.0  name=None                area  848  cover 0.58  share 1.00   <- the building:part. THE TRUTH.
```

Three rules follow, and each one was learned by getting it wrong:

1. **Never match on centroid distance.** The nearest way is the podium. Attempt 1 wrote **9.4 m onto a 40-storey tower**.
2. **Never prefer the name-matched way.** The named way is precisely the one carrying the wrong number. Attempt 2 still
   produced a median of 9.4 m across 506 matches.
3. **Qualify a candidate if it COVERS us (≥0.55) OR we CONTAIN it (share ≥0.80), then take the TALLEST.** Attempt 3.
   Lake Shore Tower 6 → **165 m**, Corporate Tower 12 → **180 m**, Taj JLT 12 → **170 m**.

Also true and separately important: **our footprints and OSM's are at different granularities.** JLT footprints have a
median area of **588 m²** — plot- and podium-sized fragments beneath towers OSM draws as one polygon. Any matcher that
assumes 1:1 will fail here even when it works in Marina.

Plausibility gates that must stay (each has a scar):

- a stated height above `floors × 3.6 + 12` is rejected in favour of the floor count
- 300–1,200 with no floor count to support it is **feet**, converted (Paramount Midtown: 886 m from a Wikidata value in feet)
- never let a tag inflate a height a survey already gave (Marina Arcade: 445 m absorbed from a neighbour's centroid; hand-pinned to 215 m)
- CityEngine reads `bHeight` **baked into the .cej at import** — patching the geojson alone does nothing. Push heights as
  **object attributes before generate** (`ce_batch_v2.py --v3`), or the model keeps its stumps.

---

## 5 · Areas are an envelope, not a floor area

The massing extrudes each footprint straight up, so its area is `footprint × storeys` — an **upper bound**.
Published as "floor area" it read as 178 M sq ft for Business Bay (≈3× the real built stock) and credited one building
with 7,600 homes.

- Say **envelope**, never floor area.
- **Withhold it entirely** where the footprint is a podium or a plot: gates scale with height — `h>100 & fp>2,500 m²`, or `h>60 & fp>4,000 m²`.
- Home counts are the register's where we hold one; otherwise indicative at 78% efficiency on a 105 m² apartment, labelled as such, and **never** on a flagged footprint.

---

## 6 · Bindings: a scheme may not be pinned onto a contradicting footprint

Geocode-and-snap pinned register schemes onto the tallest footprint within 80 m. Four buildings were mislabelled:
**23 Marina** → Six Senses Residences · **Ciel Tower** → Infinity/Cayan · **Baccarat** → Address Downtown (matched through
its Arabic name) · **Five JBR** → Jumeirah Residences Emirates Towers.

Rule: **if the footprint already carries a name and the scheme shares no distinctive word with it, refuse the binding.**
District words carry no evidence — every third building in Dubai Marina has "Marina" in its name. The test is
asymmetric: if the scheme has a distinctive word, the footprint must carry it; if the scheme is all generic words, any
word in common will do. This rejected 40 bindings and cost 4 good ones. Correct trade for a client-facing product.

---

## 7 · District maturity — read this before promising anything

Marina, Downtown and Business Bay are the only districts where naming, heights, tenants and register depth are all
populated. **Marina is the most mature**: 50.6% identified, 254 surveyed heights, 195 buildings with tenants, 16 bound to
developers, 3,540 homes named by the register.

Two traps:

- **Downtown looks impressive and answers few broker questions** — 2 developer bindings, 49 registered homes, because
  Emaar is not on the eleven-developer whitelist.
- **Motor City's 76.2% identification is the highest in the twin and the thinnest** — villas identified by street
  address, 11.7% real heights, no developer bindings, no register homes. *Correctly identified, barely known.*

---

## 8 · Environment traps (they will waste an hour each)

- **The Bash heredoc collapses `\\` to `\`.** Python written inline arrives with `\b` as a **backspace byte (0x08)** — it
  looks correct in `sed` output and only `cat -A` or a byte count reveals it. **Write patch scripts with the Write tool,
  then run the file.** Verify with `sum(b.count(bytes([c])) for c in (7,8,11,12)) == 0`.
- **The DLD gateway serves transactions and rents only.** `units`, `buildings`, `lands`, `projects` answer HTTP 500 while
  `transactions` answers 200 — they are portal-CSV downloads, not API endpoints. Do not keep probing.
- **Overpass 504s often.** Rotate mirrors, cache the raw answer, and never re-fetch what is on disk.
- **`data/*` is gitignored** — identity and board artefacts need `git add -f`.

---

## 9 · The one thing that would change everything

**DLD Unit Details** carries `BUILDING_NAME`, `BUILDING_NUMBER`, `LAND_NUMBER`, `MUNICIPALITY_NUMBER`, `PROJECT_NUMBER`
and `PROJECT_NAME` outright. It is rank 1 in the precedence table and the adapter is written and waiting in
`resolve_identity.adapters()`. It sits behind a portal click-through at
<https://dubailand.gov.ae/en/open-data/real-estate-data/> and must be downloaded by hand into
`data/identity/official/dld/`. Then Dubai Municipality's **Building Summary Information** and **Makani** for the villas.

Open data can improve the edges. It will not take 1,775 names to 10,000. Only the cadastral registers will.

## 10. Tiles, the size budget and what a district GLB actually weighs (JLT split, 5 Sep 2026)

- **A district GLB is mostly JSON, not geometry.** JLT North packed to 7.99 MB: 5.57 MB of that is the JSON chunk
  (one node + mesh + three accessors + a name per building, ~1.6 KB each for 3,577 buildings); triangles were 2.4 MB.
  meshopt/webp cannot touch the JSON. gzip crushes the whole file 5-6x (7.99 -> 1.65 MB). So the 5 MB cap is met by
  **storing large GLBs gzipped** (`push_assets.py` does it automatically for `model/gltf-binary` over the cap) and the
  Worker's `/img/` route serving them with `Content-Encoding: gzip` + `encodeBody: "manual"` when it sees the 1f 8b magic.
  The browser's fetch inflates transparently, GLTFLoader never knows. Do NOT merge meshes to save bytes - per-building
  meshes are what make tap-a-tower work.
- **Split by count, keep buildings whole.** `split_district.py <parent> <north> <south>` cuts at the median centroid
  latitude of the building-level export; a building goes with its centroid. JLT: 7,153 -> 3,577 / 3,576. All 111 towers
  fell north; the south tile is the Jumeirah Islands / Jumeirah Park villa belt - that is the geography, not a bug.
- **Never run `ce_batch.py` to add one district.** It imports every folder that has a buildings.shp and only skips folders
  with a legacy `sky_<slug>_0.glb`; v2/v3 districts have `_v2_0`/`_v3_0` names, so it would re-import the whole city.
  `ce_import_tile.py <tile> ...` does the single import (lock-protected) and `ce_batch_v2.py --v3 <tile>` masses it.
- **KV name = `sky_<slug>` exactly.** `push_assets.py --skylines` maps `sky_<slug>_v3_0.glb` to `sky_<slug>_v3`, which is
  the WRONG key (the rail lists every `img_sky_*` key, so a stray name becomes a phantom district pill), and it happily
  pushed the packer's `.merged.glb` intermediate too. Both fixed (`--only`, `.merged` excluded) - but for v3 tiles push by
  hand under `sky_<slug>` and `kv key list --prefix img_sky_` afterwards.
- **A tile has no community polygon.** `ce_context.py --area <tile>` now frames on the convex hull of the tile's own
  footprints; the minimap and locator map the tile to its parent polygon via `TWIN_TILE_PARENT` in the Worker.
  Identity evidence (Overture / OSM addresses / Places) is still keyed by the PARENT slug - the tiles came out with
  anchors-only names (164 / 179). Teach `resolve_identity.py` to read the parent's evidence for a tile before re-running.
- **Rail lesson.** One flat alphabetical row does not scale past ~12 districts. v86 groups by five corridors, badges
  maturity from `twin_audit` (gold = register-bound, grey = surveyed, dark = massing only) and retires a parent from the
  rail once all of its tiles are live.

## 11. Rail on the twin (5 Sep 2026, v87)

- **Sources, in order.** OpenStreetMap is the geometry (track ways with bridge/tunnel/layer, stations, construction status,
  route relations); the public ArcGIS Online station layers (NYU 2018, a 2023 set) are the second source - they confirmed
  49 of the 60 OpenStreetMap stations and added 12 (mostly Route 2020 and tram stops). Esri World Imagery is the ground and
  SRTM the relief underneath, both already in the tile. No official RTA geodata is reachable without a portal login
  (Dubai Pulse returns HTML, data.dubai does not resolve) - the moment a shapefile lands, it goes in as the authority.
- **Why not CityEngine for the viaduct.** The rail is procedural anyway (deck ribbon + piers every 30 m + platform boxes);
  building it in the viewer keeps it out of the 5 MB tile budget and lets it be toggled. CityEngine stays for buildings.
- **Red Line vs Route 2020.** Route relations name the branch as part of the Red Line ("Red Line: ... -> Expo 2020"), so a
  naive "2020 in the name" test paints the JLT/Marina trunk as Route 2020. Rule: a way on any plain Red Line route is
  trunk; a way whose route names ALL say 2020/Expo is the branch.
- **Station noise.** A bare railway=station pin with no network/operator is not a station (a pharmacy in Jebel Ali got in);
  require station/network/operator and drop retail names.
- **Heights are standard figures** (viaduct 13 m, rail bridge 8 m, ballast 0.6 m) - OpenStreetMap does not tag them; the
  footer says "deck heights illustrative". Tunnels are not drawn.
- **Windows are square.** The tile window is the ground-imagery bbox, which is pixel-square, so JLT North's window reaches
  across Sheikh Zayed Road into Marina and picks up the tram - that is continuity, not an error.
- Trolley (Downtown Boulevard, 12 ways) and the airport people-movers are tagged as tram/monorail in OpenStreetMap and get
  their own nets so the label is honest.

## 12. The register thread (6 Sep 2026)

The Dubai Land Department exports only join once you find the id: `units.parent_property_id = buildings.property_id`, and the building's `project_name_en` is the same string the transactions file calls `building_name_en` and Ejari calls `project_name_en`. That chain gives every registered building its true unit mix (units by type, size, the floors each type sits on), what sold by type, what rents by type, and the gross yield per type. The floor-level file is keyed by a municipality id and joins none of it; ignore it. Footprint binding is still by name (transactions bindings, name match then gated geocode), so an unnamed register building cannot reach the twin until a parcel layer exists. Details and proofs: `DATA_SOURCES_DLD_06SEP2026.md`. Identity grades: a register name confirmed by the map is VERIFIED, a register name placed by geocoding is MATCHED, and `apply_identity.py` now creates a label anchor for any footprint that gains a name.

Addendum, later on 6 Sep: the same parcel id is Dubai Municipality's parcel id. `DLD parcel_id == DM parcel_id` opens `building_summary_information` (permitted floors "6B+G+94+1P+1R", lifts, indoor parking, usages, completion date) and, through its `building_id`, the floor-level file (units and usage per floor). 4,829 of our 20,209 register buildings bridge; the Trakhees communities (Palm Jumeirah, JVC, JVT, Dubai Islands) are not in the municipality file. Script `dm_bridge.py`; the card prints the permit line. The unit-mix layers now read, in order: units register (verified) → DM permit → transactions → Ejari → developer register → sheet → model.
