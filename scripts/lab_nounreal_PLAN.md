# Dropping Unreal for district films - gap plan (Kendall, 30 Sep 2026: "start closing those gaps so we can drop unreal")

Baseline (30 Sep): the headless three.js prototype matches the Unreal Business Bay film (`data/media/businessbay/bb_v1_9x16.mp4`)
on cameras, geometry, water, sun and shadows. The side-by-side is in `pairs/pairs_sheet.jpg` and
`sidebyside_wide_ue_vs_three.mp4`. Keep Unreal only for street-level hero shots until every row below is closed.

| # | Gap | Owner | Status |
|---|-----|-------|--------|
| 1 | Speed: WebCodecs in-page encode, shadow cache, mesh batching | renderer agent | **done 30 Sep**: full 121 s path (3,025 frames 1080x1920) in 5.4 min end to end; 66 ms/frame median |
| 2 | Lighting: sand bounce, sky tint, exposure/IBL/SSAO vs Unreal | renderer agent | **done as far as measurable**: dE to Unreal 42.8 -> 27.0 (mean). Open: ground and shadows still darker (no true GI), no local reflections, no motion blur |
| 3a | Facade look in the renderer: landmark glass, M_DA_Facade band/mullion shader | renderer agent | **done**: shader ported with role mapping and landmarks_v2 glass; switches off when real v6 geometry is present |
| 3b | Facade look at the source: CGA `najma_v6` | facade agent + coordinator | **built in CE 2026.1 (30 Sep 23:40)**: businessbay 655/655, b<i> names intact, 307k tris, 32 PBR role-named materials, 1.38 MB gz packed; Datasmith export with metadata on all 655 actors and roughness/metallic |
| 4 | Street dressing: ground / hardscape PBR, instanced palms and trees, furniture, lamps, cars, from the SAME `*_ue.json` placements | scenery agent (`data/lab/context/`) | **lab done 30 Sep** for businessbay: CGA/PyPRT, 19,467 placements within 0.4 mm of Unreal's, 43-role palette from Unreal's values, 1.76 MB gz, Datasmith export with instancing. Left: ground noise is a baked tile; low-poly Esri plants instead of Unreal's Sketchfab plants; café sets are primitives. |
| 5 | True GI for hero stills: Blender 5.1 Cycles (OptiX) builder from the same glTF | Cycles agent + coordinator | **done 30 Sep**: 6-10 s/still after a 2-3 min build. Finding: Unreal's warm shadows come from its SKYLIGHT (HDRI's own low sun, blurred for diffuse), not bounce (3-6% of shadow light). With a UE-style sky, Cycles scores mean dE 30.6 on aerials vs three.js 27.1, but wins at street level (33.0 vs 38.2). Use Cycles for eye-level hero stills; three.js for aerials and sequences |
| 6 | Tours: labels, price heat, metro and site lines for the Sobha / Ellington tours, reusing the web twin's code | next | queued |
| 7 | Integration: one film script | renderer agent | **done 30 Sep**: `scripts/lab_nounreal_film.py <plan.json> --out <mp4> --mb 2`. bb_v1 end to end in 17.5 min (1,411 frames at 328 ms + the unchanged bb_v1_encode.py grade/cards), 59.92 s / 1,498 frames, same as Unreal's cut. Replaces the 4 UE steps in logs/bb_v1_run.ps1. Limit: scene inputs wired for businessbay only |

Rules for every lane: lab files only until promoted; no Unreal or CityEngine GUI launches while the CityEngine 2026.1
batch runs; one GPU-heavy job at a time; nothing published without Kendall's go via Rings.


Deliverables (30 Sep): `pairs_v2/pairs_sheet.jpg`, `film_v2/three_film_v2_graded.mp4` (full path), `film_v2/sidebyside_bb_v1_edit.mp4` (Unreal vs three.js, the 55.7 s edit).
Remaining before Unreal can go: true GI for ground and shadows (Blender Cycles lane, #5), local reflections (SSR or probe grid, about 1 day), close street-level shots untested, tours (#6), one film script (#7).

Also done 30 Sep: reflections (probe + optional SSR; dE flat at about 27), close shots (street level broadly matches; shopfronts ported), motion blur `--mb 2` (Unreal parity, 2x cost).
Open: glint bloom on mirror glass, canal saturation, low-poly plants and café primitives within 5 m, flat paving, true GI (Cycles lane running), other districts' scene wiring, tours (#6).

1 Oct 00:xx - ANY DISTRICT done: `python scripts/lab_nounreal_film.py auto --district <slug> --secs 30 --out <mp4> --mb 2` picks up the district's buildings, looks, shopfronts, scenery or ground and water, and reflection capture, and generates an orbit + flyover plan. Dubai Marina 30 s film in 6 min (film_dubaimarina/). Tuning: glint capped, paler water (close shots 47.7 -> 44.7; aerial 26.9). v6 facades in the film: dE 27.6 (towers too pale), so v6.1 with palette-tinted glass is in progress. CE's own glTF export still loses precision, so web tiles come from PyPRT (local frame); test GLTFExportModelSettings.setGlobalOffset. Still open: shop glass reflection too bright; tours (#6).
