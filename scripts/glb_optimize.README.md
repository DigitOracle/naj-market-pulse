# glb_optimize — Najma skyline district models, optimised for 4G

`scripts/glb_optimize.mjs` runs the glTF Transform command-line tool over every
`data/ce/_glb/sky_*.glb` and writes an optimised copy **with the same file name** to
`data/ce/_glb/opt/`. Originals are never modified. A machine-readable summary is written
to `data/ce/_glb/opt/_optimize_report.json`.

Result of the 3 Sep 2026 run (40 files, no simplify): **45.5 MB -> 4.36 MB (10 %)**.
Every district is now under 450 KB, i.e. well under 0.5 s on a 1.5 MB/s (12 Mbit/s) 4G link;
the previous worst case (`sky_althanyahfifth_0.glb`, 4.2 MB, ~2.8 s) is now 354 KB.

## Run

```bash
cd C:\Dev\naj-market-pulse
node scripts/glb_optimize.mjs                 # all sky_*.glb -> data/ce/_glb/opt/   (~2 min)
node scripts/glb_optimize.mjs --simplify      # also decimate merged-mesh districts (see below)
node scripts/glb_optimize.mjs --only marina   # substring filter on the file name
node scripts/glb_optimize.mjs --verify        # re-check every opt/ file against its original
node scripts/glb_optimize.mjs --dry-run       # list what would be processed
```

Options: `--in <dir>` `--out <dir>` `--ratio 0.6` `--error 0.001` `--position-bits 16`
`--level high|medium` `--bin <path/to/gltf-transform cli.js>` (or env `GLTF_TRANSFORM_BIN`).

The tool is fetched with `npx --yes @gltf-transform/cli@latest` (first call ~40 s, network);
the script then locates that cached install and calls it directly so each step takes < 1 s.
Nothing is installed globally and nothing is added to the repo's dependencies.

## What each file goes through

| step | command | effect on these models |
|---|---|---|
| 1 | `dedup` | merges duplicate accessors / materials / meshes (none found in practice) |
| 2 | `weld` | indexes the geometry; identical vertices merged, tolerance 0 = lossless. CityEngine exports are unindexed triangle soup, so this alone cuts vertex count ~3x |
| 3 | `simplify --ratio 0.6 --error 0.001` | **opt-in (`--simplify`)**, merged-mesh districts only, never the per-building model |
| 4 | `quantize --quantize-position 16 --quantization-volume mesh` | `KHR_mesh_quantization`; positions stored as normalised int16 per mesh. The per-mesh offset/scale goes into the node transform, so **world-space coordinates are unchanged** (precision ~6 cm on a 3.7 km district, sub-millimetre on a single building) |
| 5 | `meshopt --level high` | `EXT_meshopt_compression` on all buffer views |

The output is then re-parsed: GLB header and length, JSON chunk, `extensionsRequired` must list
`EXT_meshopt_compression`, mesh count, node count and node order must equal the original. Any
failure deletes that output and is listed at the end (exit code 1).

Classification: a file with more than 50 meshes is treated as *per-building*
(`sky_dubaimarina_v2_0.glb`, 589 meshes / 1178 nodes); everything else is *merged*
(1 mesh, except `businessbay` = 4 and `goldensymphony` = 3).

### Why simplify is off by default

Measured on the full set: simplify takes the total from 4.36 MB to 3.08 MB (biggest file
354 KB -> 223 KB), which is not needed for the 2 s target. The cost is geometric: `--error`
is a fraction of the *mesh extent*, and a merged district mesh is 3-4 km across, so 0.001 allows
~3-4 m of deviation - enough to visibly distort small buildings and roof edges. On the
per-building model the same setting would be harmless (extent = one building) but that model is
skipped anyway to keep mesh index == building index for the anchors file. If bandwidth ever
becomes the constraint, prefer `--simplify --error 0.0002` (~0.7 m) and eyeball the result.

## Viewer change required (three.js 0.169, GLTFLoader)

The optimised files **require** the Meshopt decoder: a plain `GLTFLoader` throws
`THREE.GLTFLoader: setMeshoptDecoder must be called before loading compressed files`.
The decoder ships inside three's `examples/jsm`, so with the existing import map no new
dependency or CDN entry is needed. `KHR_mesh_quantization` is supported natively by GLTFLoader.

Change in `C:\Dev\azimuth-worker\src\index.js` (skyline page, ~line 4506 and ~4520 - owned by
the Worker maintainer, not edited by this step):

```js
import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { MeshoptDecoder } from "three/addons/libs/meshopt_decoder.module.js";   // ADD

// ...

const loader = new GLTFLoader();
loader.setMeshoptDecoder(MeshoptDecoder);                                       // ADD
loader.load("/img/sky_${slugName}", g => {                                        // was: new GLTFLoader().load(...)
  // unchanged
});
```

The decoder is ~30 KB (base64-embedded WebAssembly inside that module, one extra request from
the same unpkg origin) and initialises asynchronously; `GLTFLoader` waits for it, nothing else
changes. A loader with the decoder set also loads the un-optimised originals, so the change can
ship before the `opt/` files are pushed.

Things that were checked against the viewer code and do not need changes:

- `flatShading: true` on the replacement `MeshStandardMaterial` - welding shares vertices, but
  flat normals are derived in the shader, so facades stay crisp (do **not** switch to
  `computeVertexNormals()` on the welded geometry, that would smooth the building edges).
- `Box3().setFromObject(root)` is world-space, so the re-centring, ground disc and camera
  framing are unaffected by the quantisation node transforms.
- `MESHES` order (traverse order = mesh index used by `anchors_<slug>.json`) is preserved: no
  flatten, no join, no instancing, node order verified equal to the original.
- Material colours are unchanged, so `classify()` still resolves existing / construction / pipeline.
- Anchor labels use `a.x, a.h, a.z` + `ROOTREF.position` in GLB metres - still valid, world
  coordinates are identical to within the quantisation step.

## Serving note

The per-building file (`sky_dubaimarina_v2_0.glb`, 446 KB) is 80 % JSON (589 nodes, 801
accessors with min/max, meshopt buffer-view descriptors). That JSON gzips to ~90 KB total, but
`model/gltf-binary` is not on Cloudflare's automatic-compression list, so the wire size is the
file size unless the Worker sets `Content-Encoding` itself. Not needed for the 2 s target;
noted in case more per-building districts are added.

## Size table (default run, 3 Sep 2026)

| district file | kind | before | after | % | triangles |
|---|---|---:|---:|---:|---:|
| sky_alhebiahfifth_0.glb | merged | 121.2 KB | 11.8 KB | 10% | 3,428 |
| sky_alkhairanfirst_0.glb | merged | 129.1 KB | 13.5 KB | 10% | 3,652 |
| sky_alsatwa_0.glb | merged | 1284 KB | 108.1 KB | 8% | 36,494 |
| sky_althanyahfifth_0.glb | merged | 4192 KB | 353.5 KB | 8% | 119,230 |
| sky_alwasl_0.glb | merged | 2071 KB | 179.4 KB | 9% | 58,888 |
| sky_alyelayiss1_0.glb | merged | 693.6 KB | 58.5 KB | 8% | 19,708 |
| sky_alyelayiss2_0.glb | merged | 192.9 KB | 21.1 KB | 11% | 5,468 |
| sky_alyufrah1_0.glb | merged | 28.7 KB | 4.5 KB | 16% | 796 |
| sky_arjan_0.glb | merged | 348.0 KB | 32.7 KB | 9% | 9,880 |
| sky_burjkhalifa_0.glb | merged | 519.8 KB | 47.9 KB | 9% | 14,764 |
| sky_businessbay_0.glb | merged (4 meshes) | 537.6 KB | 52.8 KB | 10% | 15,228 |
| sky_damachills_0.glb | merged | 478.3 KB | 49.8 KB | 10% | 13,584 |
| sky_dubaihills_0.glb | merged | 3212 KB | 274.5 KB | 9% | 91,336 |
| sky_dubaiindustrialcity_0.glb | merged | 743.3 KB | 63.4 KB | 9% | 21,124 |
| sky_dubaiinvestmentparkfirst_0.glb | merged | 1403 KB | 123.6 KB | 9% | 39,900 |
| sky_dubaiinvestmentparksecond_0.glb | merged | 520.3 KB | 51.4 KB | 10% | 14,780 |
| sky_dubaimarina_0.glb | merged | 631.1 KB | 57.6 KB | 9% | 17,932 |
| sky_dubaimarina_v2_0.glb | per-building (589) | 813.5 KB | 446.2 KB | 55% | 17,932 |
| sky_dubaimaritimecity_0.glb | merged | 415.7 KB | 38.2 KB | 9% | 11,804 |
| sky_dubaiproductioncity_0.glb | merged | 1438 KB | 124.4 KB | 9% | 40,884 |
| sky_dubaisciencepark_0.glb | merged | 1686 KB | 147.3 KB | 9% | 47,928 |
| sky_dubaisportscity_0.glb | merged | 1051 KB | 88.8 KB | 8% | 29,868 |
| sky_dubaistudiocity_0.glb | merged | 123.5 KB | 13.2 KB | 11% | 3,492 |
| sky_goldensymphony_0.glb | merged (3 meshes) | 653.8 KB | 134.4 KB | 21% | 18,548 |
| sky_jabalalifirst_0.glb | merged | 2323 KB | 195.2 KB | 8% | 66,044 |
| sky_jabalaliindustrialsecond_0.glb | merged | 781.0 KB | 71.0 KB | 9% | 22,196 |
| sky_jumeirahvillagecircle_0.glb | merged | 904.4 KB | 82.8 KB | 9% | 25,704 |
| sky_jumeirahvillagetriangle_0.glb | merged | 967.6 KB | 87.3 KB | 9% | 27,504 |
| sky_madinatalmataar_0.glb | merged | 3439 KB | 265.5 KB | 8% | 97,808 |
| sky_madinathind4_0.glb | merged | 680.6 KB | 52.5 KB | 8% | 19,340 |
| sky_majan_0.glb | merged | 2996 KB | 248.4 KB | 8% | 85,204 |
| sky_meydanone_0.glb | merged | 2627 KB | 212.3 KB | 8% | 74,712 |
| sky_motorcity_0.glb | merged | 382.4 KB | 35.8 KB | 9% | 10,856 |
| sky_palmdeira_0.glb | merged | 207.6 KB | 19.5 KB | 9% | 5,884 |
| sky_palmjumeirah_0.glb | merged | 2431 KB | 202.6 KB | 8% | 69,136 |
| sky_samaaljadaf_0.glb | merged | 777.1 KB | 70.1 KB | 9% | 22,084 |
| sky_siliconoasis_0.glb | merged | 1313 KB | 114.8 KB | 9% | 37,324 |
| sky_sobhaheartland_0.glb | merged | 1234 KB | 103.4 KB | 8% | 35,088 |
| sky_wadialsafa4_0.glb | merged | 543.2 KB | 49.5 KB | 9% | 15,432 |
| sky_wadialsafa5_0.glb | merged | 606.0 KB | 55.1 KB | 9% | 17,216 |
| **TOTAL (40)** | | **45501 KB** | **4362 KB** | **10%** | |

Triangle counts are identical before and after (weld + quantize + meshopt are geometry-preserving);
vertex counts drop ~3x from indexing. Failures: none. Run time: 117 s.

## Browser check (3 Sep 2026)

Loaded in three.js r169 from the unpkg import map with `setMeshoptDecoder(MeshoptDecoder)`:

| file | result | meshes | triangles | world bbox min / size |
|---|---|---:|---:|---|
| original `sky_dubaimarina_v2_0.glb` (plain loader) | OK, 60 ms | 589 | 17,932 | 310332.50, 0.00, -2777416.25 / 3416.97 x 377.00 x 3702.25 |
| opt `sky_dubaimarina_v2_0.glb` | OK, 22 ms | 589 | 17,932 | identical (Int16 normalised positions, indexed) |
| opt `sky_althanyahfifth_0.glb` | OK, 6 ms | 1 | 119,230 | 312075.85, -0.02, -2775152.25 / 3635.35 x 340.04 x 5184.75 |
| opt `sky_goldensymphony_0.glb` | OK, 5 ms | 3 | 18,548 | 329449.72, 0.00, -2784649.50 / 56.06 x 158.00 x 56.50 |
| opt file with a plain `GLTFLoader` (no decoder) | FAIL - `setMeshoptDecoder must be called before loading compressed files` | | | |

First mesh name (`b294`) and traverse order match the original, so the anchors' mesh indices remain valid.

## Not done here (by design)

- The Worker source is not edited and nothing is pushed to Worker KV - the `opt/` files are
  ready for whoever owns `/img/sky_*` to publish once the viewer change above has shipped.
- Nothing committed.
