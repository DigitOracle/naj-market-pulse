# najma_v6.cga — LAB notes (CityEngine 2026.1, research only)

`C:\Dev\ce2026_lab\rules_v6\najma_v6.cga` = production `rules\najma_v3.cga` (verbatim) + 3D facade detail from the
2026 ESRI.lib components + PBR by facade role on Unreal's palette. Nothing in the repo, the Default Workspace, the lab
`najma` project, `ESRI.lib` or `data_ce` was written. All compile / build / render work is in the throwaway
`C:\Dev\ce2026_lab\cgac_ws_v6\` (scripts, logs, RPKs, GLBs). Snapshots: `rules_v6\snap_*.png`.

## 1. What facadeDetail = true adds (textured = true, LOD >= 1)

The v3 photo facade is ALWAYS kept; v6 adds geometry on the texture's own grid and puts PBR on the material.

| building | v6 detail |
|---|---|
| glass class (glassblue / glassclear / glassbronze), mid-rise >= 20 m and tower shafts (`glassTexture` = true, default) | v3 photo curtain wall + glossy glass PBR on it (metallic capped at `texGlassMetal` 0.10, roughness >= `texGlassRough` 0.12: the palette's metallic 0.5-0.6 turns a photo grey in a PBR viewer); a slab-edge ledge (`ledgeH` 0.3 x `bandProj` 0.3 m) on every floor line of the texture; a vertical fin (ESRI `Shading_Structure_Vertical_Fin.cga`, `finProj` 0.5 m, white) on every bay line of the texture and at every facet start, so faceted / curved towers get one per facet |
| same, `glassTexture` = false (Unreal-parity option) | untextured curtain wall on Unreal's M_DA_Facade rhythm: vision glass + `bandW` 0.9 m spandrel every `ueFloorH` 3.6 m, fins every `finEvery` panes of `paneW` 1.5 m (MullW = `finW` 0.12) |
| residential (below), mid-rise and tower shafts | v3 photo texture (swapped to the class's `_Residential_` texture if v3 had an office one) + ESRI balconies (`Balcony_Structure_Rectangular_With_Railings_On_Top_Of_Slab.cga`, 1.4 m deep, 0.2 m slab, 1.1 m rail) with `Balcony_Railing.cga` (LOD 1 "Solid" glass panel at 0.8 opacity, LOD 2 "Solid Panels With Top Bar" + side rails), on the texture's own storey / bay grid, every 2nd bay (`balconyEvery`; a facet narrower than that gets one on its first bay) or continuous (`balconyContinuous`); never on the first storey of a face, never on a podium |
| warehouse / school / mosque / retail / other / villa / townhouse (`btype`) | no balconies, no residential detail; texture + PBR only |
| low glass (< 20 m), podiums, other walls, roofs | v3 texture, PBR role params |
| crowns | glass: dark (da_spandrel, like v3's dark band); others pale_concrete |
| pipeline ghosts, LOD 0 | unchanged (v3) |

Residential = `btype` tower / lowrise_apt(ment) (non-glass), or, with `btype` empty, a non-glass building >= 20 m whose v3
texture is a `_Residential_` one. Untyped glass gets fins; a look pushing `balconyMinH >= 0` gets balconies on glass too.
Louvres (ESRI Shading_Panel_Louvers) were not used: their default 0.08 m blade pitch is far beyond the triangle budget.

PBR: every v6 leaf sets `material.shader = "CityEnginePBRShader"` (without it CE's glTF / Datasmith drop roughness and
metallic — v4 set them and `sky_businessbay_v4_0.glb` carries metallic 0 / no roughness), `roughness`, `metallic`,
`specular.rgb` and `material.name = "<look>_<role>[_<status>]"`. Colours = `scripts\ue_sobha_pbr.py` PALETTE (linear)
converted with gamma 2.2 (CE writes glTF baseColorFactor = cga^2.2, measured on sky_businessbay_v2_0.glb; PyPRT's GLB of
v6 carries blue_glass back as 0.14 / 0.28 / 0.46 exactly) + `da_*` = `scripts\ue_bb_facade.py` M_DA_Facade2 defaults.
Photo textures are tinted only when a look is pushed. Roles (ue_sobha_pbr ROLE_OF tokens): vision spandrel slab_band fin
mullion balcony_slab balustrade parapet roof wall podium_wall.

## 2. facadeDetail = false == najma_v3 (verified on the final rule)

v3 rules / attrs / functions are verbatim; v6 only inserts `case dOn ...` branches ahead of v3's (Building, PodiumFacade,
ShaftFacade, LowFacade, CrownBand, Roof, bldgH's typeHeights case) with `dOn = facadeDetail && textured && LOD >= 1`, plus
annotations (`@Enum(0,1,2)` on LOD for the Unreal LOD export). PyPRT 1.12, Business Bay, 655 shapes, both packages from the
same CE 2026.1 headless compiler (`cgac_ws_v6\build_bb.py compare`, `dbg_diff2.py`, `dbg_glbeq.py`): results in section 8.
Vertex ORDER is not a test: two runs of v3 itself agree raw on only ~100-290 of 655 buildings.

## 3. Compile (headless, CE 2026.1) — how, and three traps

`CityEngine.exe -application com.esri.cgac.application -nosplash -consoleLog -data <ws> -cgalib <ws>\ce.lib\rules\_ce_.cga -prj <ws>\najma6 -out <dir> <ws>\najma6\rules\najma_v6.cga`
(`cgac_ws_v6\compile.py`) -> 0 errors, 0 warnings, one `najma_v6.cgb` + `$_ce_` + a `najma_v6$<import>.cgb` per component.
1. `max` / `min` / `clamp` live in `ce.lib\rules\_ce_.cga`; cgac 2.11 only finds them via `-cgalib` (else "No such
   function: max(float,float)", also inside ESRI's own Railing_Panel_*).
2. Cross-project imports (`/ESRI.lib/...`) need ESRI.lib to be a REGISTERED Eclipse project of `-data`, else the bytecode
   backend NPEs in `CGAFileResolver.getImportAnnotationPath` after a clean semantic pass. The throwaway workspace carries a
   copy of the lab workspace's resource metadata (`.root\15.tree`, `.safetable`, `.projects\*\.location`, all
   default-located, so they resolve to the COPIES: `cgac_ws_v6\ESRI.lib` = rules copy + `assets` junction, `ce.lib` rules
   copy). Nothing written to C:\Dev\ce2026_lab\ESRI.lib / ce.lib / najma (checked with find -newermt).
3. The main rule must sit OUTSIDE the registered projects (`najma6`), or its charset lookup NPEs (file not in the tree).

RPK `cgac_ws_v6\najma_v6.rpk` (`pack_rpk.py`): rules/najma_v6.cga, bin/ all .cgb, `.ws/ESRI.lib/assets/...` the 23 facade /
roof textures the rule can name, `.ws/ESRI.lib/rules/...` the 7 component sources; 7z LZMA non-solid. PyPRT 1.12 loads it
from an absolute path and generates with one warning per shape: "Potentially unsupported CGAC version 2.11 : newer than
current (2.10)" — no CGA error, no missing asset.

## 4. Attributes the build pushes

Already pushed by ce_batch_v2 / pyprt_district: `status bHeight levels fclass fvar pctComplete` (OBJECT), `LOD bandEvery`
(USER). The default look needs nothing else (`facadeDetail` defaults to true). Optional, OBJECT-sourced:
- `btype` from `data\lab\buildingtype\types_<slug>.json` (medium / high confidence measured; `lowrise_apartment` accepted).
  `typeHeights` (default false) = PATCH_buildingtype.diff heights for typed placeholders (off: it changes massing).
- `look` + `palWalls palSlabs palVision palFins palCrown` from facade_refs.json looks[look].unreal via facade_match.json
  (Business Bay: 7 buildings); look `cga` keys read under the same names: `paneW finW finProj balconyMinH
  balconyContinuous balconyD` (+ `fclass`, `crownPct`, already v3 attrs).
- `landmark lmLOD lmFloors lmAz0..2 lmLen0..2` from landmark_table.json (b158 The Opus: void_cube).
- 2026 lane: a `--v6` in ce2026_batch.py that behaves like `--v3` (names `b<i>_<class>_s<status>`, single tier LOD 1, RULE_WS
  `/najma/rules/najma_v6.cga`) + `setAttribute` / `setAttributeSource(..., "OBJECT")` for any optional attr. v6 is
  2026-only: the ESRI.lib components it imports are not in 2025.1's ESRI.lib.

## 5. Landmark hook

`landmark != ""` (detail on) routes to `Landmark` -> `LandmarkBuild` = today the generic v6 build + `report("Landmark.<f>")`.
Switch the families on (v6 deployed as `<project>\rules\najma_v6.cga` beside `rules\lab\landmarks\`): add
`import lmk : "lab/landmarks/landmarks.cga"` and `LandmarkBuild(v, c) --> lmk.Landmark`. Compile-tested in the throwaway
(`najma6\rules\najma_v6_lmk.cga`): 0 errors, 47 .cgb (13 version warnings from the 2023.0 landmark files).

## 6. Unreal (Datasmith) export, CityEngine 2026 Python API

```python
s = UnrealExportModelSettings()
s.setUseUnrealBaseMaterials(True)      # Unreal base material as parent: colour / metallic / roughness arrive as parameters
s.setMeshMerging("perInitialShape")    # one actor per building (b<i>_<class>_s<status>), material slots = the v6 roles
s.setInstancing("disabled")            # v6 inlines its component geometry (nothing to instance); required for metadata
s.setMetadata("all")                   # attrs + reports per actor (look, btype, Faces.<role>, Height_m ...)
s.setExportLod(True); s.setLODAttribute("LOD"); s.setLODOrder(UnrealExportModelSettings.ASCENDING)
                                       # LOD is @Enum(0,1,2): Unreal LOD0 = v6 LOD 2 (ledge soffits, fin boxes, side rails),
                                       # LOD1 = v6 LOD 1 (web detail), LOD2 = v6 LOD 0 (massing)
s.setTwinmotionCompatible(False)
```
With the look carried by CE, ue_sobha_pbr.py / M_DA_Facade no longer have to re-create it; if they still run, ROLE_OF
matches v6's names. Trap: ROLE_OF is a substring search in fixed order, so a look NAME containing a role token misroutes
(`central_fins_wall` matches `fin` before `_wall`); anchor the regexes on the suffix before relying on it.

## 7. Not verified without a CityEngine 2026.1 generate

- PyPRT 1.12 is PRT for CGAC 2.10; the bytecode is 2.11 ("potentially unsupported" warning). Geometry was checked with it.
- Mesh names in CE's own glTF export. In PRT a leaf that IS an inserted primitive is named after the asset ("builtin:cube")
  and an inline(append) result "merged" — both break glb_merge_per_building (Business Bay came out as 65,794 "buildings").
  v6 folds each face's detail with inline(recompose) whose FIRST shape is the facade's own textured face, which keeps
  `b<i>_<class>_s<status>` (655 / 655 in PyPRT). Check on the first CE export that every mesh name starts `b<i>_`.
- inline(recompose) reconnects split pieces by their tracking: a fin built from the wall's split piece was pulled back into
  the wall as a 6 m panel (the grey slabs in the 16:43 snapshot). Fins, ledges and LOD 2 bands are now fresh primitives.
- LOD 2 and `glassTexture = false` were compiled, built and counted in PyPRT, not rendered.
- Datasmith: whether `material.specular` and the PBR params survive into Unreal's base-material instances.
- ce_report_v2.py with the new `Faces.<role>` reports; CE generate time (PyPRT: ~90-170 s for Business Bay LOD 1).
- glb_pack_v3.mjs `dedup` folds materials with identical parameters, so a packed web tile can label e.g. all balcony slabs
  with one look's name. Datasmith keeps names.

## 8. Numbers (Business Bay, PyPRT 1.12, LOD 1, attrs as ce_batch_v2 pushes them)

| build | triangles | packed (glb_pack_v3.mjs) | gzip -9 |
|---|---|---|---|
| v3 production tile (sky_businessbay_v3_0.glb, CE 2025.1) | 20,010 | 2.67 MB | 1.09 MB |
| v6 facadeDetail = false (= v3) | 20,010 | 2.57 MB | 1.05 MB |
| **v6 facadeDetail = true (default)** | **307,154** | **6.07 MB** | **1.38 MB** (limit 5 MB) |

facadeDetail = false vs v3, final rule: triangles 20,010 = 20,010; reports identical 655 / 655; face sets identical
655 / 655; merged GLB per building (materials, texture image bytes, positions, UVs, names) identical 655 / 655
(`cgac_ws_v6\verify_final.log`, final rule code).
facadeDetail = true: 655 / 655 meshes named `b<i>_<class>_s<status>`, no CGA errors (CGAError.txt: version warnings only).

Added faces by role (quads; x2 = triangles): slab_band (ledges) 101,126 · balcony_slab 19,152 · fin 13,718 ·
balustrade 9,576 (= 9,576 balconies) · wall 2,415 · parapet 1,878 · podium_wall 1,878 · vision 1,711 · roof 879.
Heaviest buildings: b7 DAMAC Paramount (19-facet residential, ~11k added), b3 JW Marriott, b603 Safa Two.

Budget target: <= 350k triangles / <= 1.5 MB gzip for Business Bay at LOD 1 (the densest district). Knobs, cheapest first:
`bandProj = 0` (no ledges, about -200k), `finEvery = 2` (half the fins), `balconyEvery = 3`. Measured on earlier
variants of the same rule: pushing `btype` (medium / high) adds balconies to typed non-glass towers (+~70k); LOD 2 (Unreal)
is ~3x LOD 1.

Snapshots (same cameras for before / after; PyPRT build, glb_pack_v3 packed, three.js r160, sun + shadows, sky PMREM
environment, ACES): `rules_v6\snap_aerial_{before,after,pair}.png`, `snap_closeup_{...}.png`, and an extra oblique
`snap_detail_{...}.png` that shows the relief (b7 balconies, b325 / b84 fins and ledges).

## 9. v6.1 (`najma_v6_1.cga`, 1 Oct) — palette-tinted photo facades for the no-Unreal film

Why: in the three.js film renderer v6 read too pale next to Unreal (mean dE 27.6 vs v4 26.8; the t34 s oval tower white
where Unreal shows dark blue). v6.1 = v6 + three changes, all on the facadeDetail = true path only:
- photo GLASS is tinted by the vision palette colour (glassblue -> blue_glass, glassclear -> clear_glass, glassbronze ->
  bronze_glass; a pushed look's vision otherwise): baseColorFactor = 1 - m + m x palette (linear), m = `tintGlassMix` 0.5;
  metallic `texGlassMetal` 0.4, roughness `texGlassRough` 0.12;
- photo WALLS and podiums are tinted by the wall palette (render cream_render, stone sandstone, concrete pale_concrete,
  brick terracotta, glass-class podium white) - `tintWalls`;
- `tintGlass` / `tintWalls` switch either off.
Sweep through `scripts\lab_nounreal_render.py stills` + `lab_nounreal_pairs.py` (4 film stills t6 / t21 / t34 / t42, dE vs
Unreal; `cgac_ws_v6\sweep.log`, GLB factors patched, then the winner baked into the rule):

| glass metallic / roughness / tint strength | t6 | t21 | t34 | t42 | mean |
|---|---|---|---|---|---|
| v4 (reference) | 21.1 | 31.6 | 32.8 | 21.6 | 26.8 |
| v6 | 22.5 | 27.3 | 37.2 | 23.3 | 27.6 |
| 0.6 / 0.06 / 1.0 (the brief's full tint) | 22.0 | 40.5 | 33.2 | 21.6 | 29.3 |
| 0.4 / 0.12 / 1.0 | 22.0 | 37.7 | 33.5 | 21.7 | 28.7 |
| 0.5 / 0.10 / 1.0 | 21.1 | 40.8 | 32.8 | 21.2 | 29.0 |
| 0.4 / 0.12 / 0.7 | 20.9 | 32.7 | 32.9 | 21.4 | 27.0 |
| 0.4 / 0.12 / 0.6 | 20.9 | 31.1 | 33.1 | 21.4 | 26.6 |
| **0.4 / 0.12 / 0.5 (v6.1)** | 20.9 | 29.7 | 33.3 | 21.5 | **26.35** |
| 0.3 / 0.15 / 0.6 | 20.9 | 29.6 | 33.4 | 21.6 | 26.4 |

The trade-off is between two towers: full-strength palette glass fixes the t34 oval (Unreal dark blue) but turns the t21
canal tower near-black (Unreal pale lavender): the renderer's box probe reflects canal and ground into a steeply-viewed
metallic facade. Half-strength tint with metallic 0.4 keeps the oval blue and the canal tower light.

Confirmed with the rule itself (not a patched GLB): v6.1 compiled headless (0 errors / 0 warnings), Business Bay built with
PyPRT in the v5 local frame (`cgac_ws_v6\bb\bb_v61.glb` -> `data\lab\no_unreal\v6\sky_businessbay_v61_pyprt_local.glb`,
307,154 triangles, 655 / 655 named), stills `data\lab\no_unreal\stills_v61`, sheet `data\lab\no_unreal\pairs_v61\pairs_sheet.jpg`:
dE t6 20.9 · t21 29.7 · t34 33.3 · t42 21.5 = mean 26.35 (v4 26.77, v6 27.6). The t34 oval reads blue-grey (v6: white;
Unreal: dark navy). facadeDetail = false vs v3: faces 655 / 655, reports 655 / 655, per-building GLB 655 / 655 identical.
Exploration leftovers (safe to delete): `data\lab\no_unreal\v6\sky_businessbay_v61x_pyprt_local.glb`, `stills_v61x`, `pairs_v61x`.
