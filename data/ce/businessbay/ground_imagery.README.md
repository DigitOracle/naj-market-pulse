# Ground imagery - businessbay

`ground_imagery.jpg` is Esri World Imagery for this district's footprint bbox padded 150 m, exported from
ArcGIS Online in EPSG:32640 (UTM 40N), north-up, square pixels. `ground_imagery.json` carries the placement.

| | |
|---|---|
| bbox (m, EPSG:32640) | xmin 323677.9  ymin 2784978.2  xmax 328183.8  ymax 2787826.3 |
| scene box (x = easting, z = -northing) | x 323677.9 .. 328183.8   z -2787826.3 .. -2784978.2 |
| pixels / resolution | 2048 x 1294 px, 2.20 m/px, JPEG q82, 1.03 MB |
| fetched | 2026-09-03T07:49:34Z |

Scene x/z are absolute metres, the same frame as `ctx.json` and the CE GLBs. The image's TOP row is
north, which is the SMALLER z. A `PlaneGeometry` rotated `-PI/2` about X puts its local +y (uv v = 1,
the image top with the default `flipY = true`) at world -z, so no texture flip is needed.

## three.js drop-in (after `ROOTREF` and `ground` exist - e.g. next to `drawCtx()`)

```js
const G = await fetch("/img/ground_businessbay").then(r => r.json());                 // this .json
const tex = new THREE.TextureLoader().load("/img/ground_businessbay_jpg");            // this .jpg
tex.colorSpace = THREE.SRGBColorSpace;                                          // flipY stays true
tex.anisotropy = ren.capabilities.getMaxAnisotropy();
const geo = new THREE.PlaneGeometry(G.scene.x1 - G.scene.x0, G.scene.z1 - G.scene.z0);
geo.rotateX(-Math.PI / 2);                                                      // +y (north) -> -z
const mat = new THREE.MeshStandardMaterial({ map: tex, roughness: 1, metalness: 0,
  color: 0x8F958F });                                                            // ~55 % multiplier keeps the dark brand look; 0x707570 for darker
const gp = new THREE.Mesh(geo, mat);
gp.position.set((G.scene.x0 + G.scene.x1) / 2 + ROOTREF.position.x,             // GLB root is re-centred; ctx uses the same offset
  ground.position.y + 0.05,                                                     // 5 cm above the ground disc, below ctx green (0.3) / roads (0.55)
  (G.scene.z0 + G.scene.z1) / 2 + ROOTREF.position.z);
gp.receiveShadow = true; gp.renderOrder = -1;                                   // draws before the massing
scene.add(gp);
```

Notes: the ctx `roads` polygons (dark grey, y + 0.55) will sit on top of the photographed roads - drop
them or set their opacity ~0.35 once the imagery is on. The ground disc stays as the outer ground
beyond the padded bbox. Serve the two files from the Worker under whatever `/img/` keys you prefer;
the snippet assumes `ground_<slug>` (json) and `ground_<slug>_jpg`.

## Attribution (must be visible on screen while the imagery is shown)

`Source: Esri, Vantor, Earthstar Geographics, and the GIS User Community`

Esri World Imagery is licensed for use inside ArcGIS-licensed applications and apps built on ArcGIS
(the export was made under the organisation's ArcGIS Online sign-in). Keep the attribution line in
the viewer footer, do not redistribute the JPEG as a standalone product, and do not strip the
source note from `ground_imagery.json`.
