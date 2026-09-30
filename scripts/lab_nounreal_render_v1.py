"""LAB (no-Unreal, research only): render the Business Bay v1 film viewpoints WITHOUT Unreal - headless three.js r169
in Playwright/Chromium on the local GPU (ANGLE D3D11, NVIDIA forced), same inputs the Unreal build reads.

Inputs (read-only):
  data/ce/_glb/sky_businessbay_v5_0.glb            655 towers, CE local frame (origin_v5.json), y up, metres
  data/ce/_glb/sky_burjkhalifa_v5_0.glb            Downtown backdrop (as UE's burjkhalifa_lod3 Datasmith), --downtown
  data/ce/_datasmith/bb_v1/*.obj                   bb_v1_prep.py context + waterfront meshes, UE cm frame
  data/ce/_datasmith/ground/{sea,inland_water}.obj OSM water, UE cm frame
  data/ce/_datasmith/bb_v1/bb_v1_plan.json         camera keys (0.2 s), edit list, lift / water levels
  data/ce/businessbay/facade_palette_v1.json       per-building looks (UE's apply_pbr_v1 reads the same file)
Frames: UE cm (X = E - 328289, Y = 2784598 - N, Z up)  ->  three m (x = X/100 + 2358, y = Z/100, z = Y/100 + 1804).
Look: sun at Dubai 29 Sep 15:35 GST (el 33.4, az 248 - the same direction UE's SUN actor uses), Preetham sky -> PMREM IBL,
ACES filmic, PCF soft shadows (8k map fitted per view), GTAO, bloom 0.35, vignette 0.35, MSAA x4, linear fog.
Camera: UE CineCamera 20 mm on a 24 x 42.667 filmback -> vertical FOV 93.7 deg, 9:16.

  python scripts/lab_nounreal_render_v1.py stills [--w 1080 --h 1920] [--film 6,21,34,42] [--downtown]
  python scripts/lab_nounreal_render_v1.py seq --film0 36.4 --secs 5 --fps 25 --w 720 --h 1280 [--downtown]
Writes data/lab/no_unreal/{stills,seq}/ and timings.json. Never touches Unreal or CityEngine.
"""
import json
import math
import os
import sys
import time
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

from playwright.sync_api import sync_playwright

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
OUT = os.path.join(ROOT, "data", "lab", "no_unreal")
PLAN = os.path.join(ROOT, "data", "ce", "_datasmith", "bb_v1", "bb_v1_plan.json")
PALETTE = os.path.join(ROOT, "data", "ce", "businessbay", "facade_palette_v1.json")
BB_ORIGIN = (325931.0, 2786402.0)                 # origin_v5.json businessbay (E, N)
DT_ORIGIN = (326414.0, 2787548.0)                 # origin_v5.json burjkhalifa
UE_E0, UE_N0 = 328289.0, 2784598.0                # bb_v1_prep frame


def arg(k, d=None):
    return sys.argv[sys.argv.index(k) + 1] if k in sys.argv else d


def ue_to_three(p):
    """UE cm (X east, Y south, Z up) -> three m in the BB local frame (x east, y up, z south)"""
    return [p[0] / 100.0 + (UE_E0 - BB_ORIGIN[0]), p[2] / 100.0, p[1] / 100.0 + (BB_ORIGIN[1] - UE_N0)]


def film_to_render_t(plan, ft):
    bar, t = float(plan["bar_s"]), 0.0
    for t0, bars in plan["edit"]:
        d = bars * bar
        if ft < t + d:
            return t0 + (ft - t)
        t += d
    raise ValueError("film time %.2f is on the end card" % ft)


def cam_at(plan, rt):
    ks = plan["keys"]
    for a, b in zip(ks, ks[1:]):
        if a[0] <= rt <= b[0]:
            f = (rt - a[0]) / (b[0] - a[0])
            lerp = lambda u, v: [u[i] + (v[i] - u[i]) * f for i in range(3)]
            return lerp(a[1], b[1]), lerp(a[2], b[2])
    return ks[-1][1], ks[-1][2]


def palette_js():
    J = json.load(open(PALETTE, encoding="utf-8"))
    looks = {k: {"base": v.get("base_hex", "#CCCCCC"), "sec": v.get("secondary_hex", v.get("base_hex", "#CCCCCC")),
                 "refl": float(v.get("reflectivity", 0.3)), "rough": float(v.get("roughness", 0.5))} for k, v in J["palette"].items()}
    assign = {}
    for i, a in J.get("assignments", {}).items():
        if a.get("look") in looks:
            assign[int(i)] = a["look"]
    for lm in J.get("landmarks", {}).values():
        if lm.get("look") in looks:
            for i in lm.get("feature_ids", []):
                assign[int(i)] = lm["look"]
    return {"looks": looks, "assign": assign}


PAGE = r"""<!doctype html><html><head><meta charset="utf-8"><style>html,body{margin:0;background:#000}canvas{display:block}</style>
<script type="importmap">{"imports":{"three":"https://cdn.jsdelivr.net/npm/three@0.169.0/build/three.module.js",
"three/addons/":"https://cdn.jsdelivr.net/npm/three@0.169.0/examples/jsm/"}}</script></head><body>
<script type="module">
import * as THREE from 'three';
import {GLTFLoader} from 'three/addons/loaders/GLTFLoader.js';
import {Sky} from 'three/addons/objects/Sky.js';
import {EffectComposer} from 'three/addons/postprocessing/EffectComposer.js';
import {RenderPass} from 'three/addons/postprocessing/RenderPass.js';
import {GTAOPass} from 'three/addons/postprocessing/GTAOPass.js';
import {UnrealBloomPass} from 'three/addons/postprocessing/UnrealBloomPass.js';
import {OutputPass} from 'three/addons/postprocessing/OutputPass.js';
import {ShaderPass} from 'three/addons/postprocessing/ShaderPass.js';
const C = window.CFG, W = C.W, H = C.H, T0 = performance.now();
const log = m => { window.__log.push(((performance.now()-T0)/1000).toFixed(1)+'s '+m); };
window.__log = [];
const r = new THREE.WebGLRenderer({antialias:false, preserveDrawingBuffer:true, powerPreference:'high-performance'});
r.setPixelRatio(1); r.setSize(W, H); document.body.appendChild(r.domElement);
r.toneMapping = THREE.ACESFilmicToneMapping; r.toneMappingExposure = C.exposure;
r.shadowMap.enabled = true; r.shadowMap.type = THREE.PCFSoftShadowMap;
const gl = r.getContext();
log('GL ' + (gl.getExtension('WEBGL_debug_renderer_info') ? gl.getParameter(gl.getExtension('WEBGL_debug_renderer_info').UNMASKED_RENDERER_WEBGL) : '?'));
const scene = new THREE.Scene(); window.__scene = scene; window.__THREE = THREE;
const lin = (a) => new THREE.Color().setRGB(a[0], a[1], a[2]);          // UE linear values straight in (working space = linear)
const hexLin = (h, warm) => { const c = new THREE.Color(h); if (warm) { c.r = Math.min(1, c.r*1.05); c.g *= 1.01; c.b *= 0.92; } return c; };

// ---------------------------------------------------------------- sky + sun (Dubai 29 Sep 15:35 GST == UE SUN actor)
const sunDir = new THREE.Vector3(...C.sun).normalize();
const sky = new Sky(); sky.scale.setScalar(80000);
const su = sky.material.uniforms;
su.turbidity.value = 10; su.rayleigh.value = 0.6; su.mieCoefficient.value = 0.008; su.mieDirectionalG.value = 0.8;   // hazy, less blue (UE: desaturated golden-bay HDRI)
su.sunPosition.value.copy(sunDir);
{ const pm = new THREE.PMREMGenerator(r); const ss = new THREE.Scene(); const s2 = sky.clone(); ss.add(s2);
  // Preetham is black below the horizon; UE's sky light has lower_hemisphere_is_black = False -> a lit-sand lower hemisphere
  const gd = new THREE.Mesh(new THREE.CircleGeometry(300000, 32), new THREE.MeshBasicMaterial({color: lin(C.envGround), side: THREE.DoubleSide}));
  gd.rotation.x = -Math.PI/2; gd.position.y = -50; ss.add(gd);
  scene.environment = pm.fromScene(ss, 0, 1, 400000).texture; pm.dispose(); }
scene.environmentIntensity = C.envInt;
const dome = new THREE.Mesh(new THREE.SphereGeometry(45000, 48, 24), new THREE.ShaderMaterial({side: THREE.BackSide, depthWrite: false, fog: false,
  uniforms: {top: {value: lin(C.sky[0])}, mid: {value: lin(C.sky[1])}, hor: {value: lin(C.sky[2])}, low: {value: lin(C.sky[3])}},
  vertexShader: 'varying vec3 vW; void main(){ vec4 w = modelMatrix*vec4(position,1.0); vW = w.xyz; gl_Position = projectionMatrix*viewMatrix*w; }',
  fragmentShader: 'uniform vec3 top, mid, hor, low; varying vec3 vW; void main(){ vec3 d = normalize(vW - cameraPosition); float e = d.y;' +
    ' vec3 c = e < 0.0 ? mix(hor, low, smoothstep(0.0, 0.04, -e)) : (e < 0.07 ? mix(hor, mid, smoothstep(0.0, 0.07, e)) : mix(mid, top, smoothstep(0.07, 0.55, e)));' +
    ' gl_FragColor = vec4(c, 1.0); }'}));
dome.frustumCulled = false; dome.renderOrder = -10; scene.add(dome);
const sun = new THREE.DirectionalLight(lin([1.0, 0.88, 0.74]), C.sunInt);
sun.castShadow = true; sun.shadow.mapSize.set(C.shadowMap, C.shadowMap);
sun.shadow.bias = -0.0004; sun.shadow.normalBias = 0.6;
scene.add(sun); scene.add(sun.target);
scene.fog = new THREE.Fog(lin(C.fogRGB), C.fogNear, C.fogFar);
// no GI in three.js: a warm sky/sand hemisphere fill stands in for Lumen's sand bounce into the shadows (UE shadows read warm, not blue)
if (C.fill > 0) scene.add(new THREE.HemisphereLight(lin([0.62, 0.64, 0.66]), lin([0.80, 0.64, 0.45]), C.fill));

// ---------------------------------------------------------------- materials
const M = (rgb, rough, metal, extra) => new THREE.MeshStandardMaterial(Object.assign({color: lin(rgb), roughness: rough, metalness: metal}, extra || {}));
// sand: UE flat_or_noise (0.60,0.52,0.39)-(0.74,0.66,0.52) - value noise baked to a tiling texture
function noiseTex(a, b, n, px) {
  const d = new Uint8Array(n*n*4); const rnd = (x, y) => { const s = Math.sin(x*127.1 + y*311.7)*43758.5453; return s - Math.floor(s); };
  const g = 8, grid = []; for (let j = 0; j <= g; j++) for (let i = 0; i <= g; i++) grid.push(rnd(i % g, j % g));
  for (let y = 0; y < n; y++) for (let x = 0; x < n; x++) {
    const fx = x/n*g, fy = y/n*g, i = Math.floor(fx), j = Math.floor(fy), u = fx-i, v = fy-j, s = t => t*t*(3-2*t);
    const q = (ii, jj) => grid[jj*(g+1)+ii];
    let t = (q(i,j)*(1-s(u)) + q(i+1,j)*s(u))*(1-s(v)) + (q(i,j+1)*(1-s(u)) + q(i+1,j+1)*s(u))*s(v);
    t = 0.75*t + 0.25*rnd(x*0.37, y*0.71);
    const c = [0,1,2].map(k => a[k] + (b[k]-a[k])*t);
    const o = (y*n+x)*4; for (let k = 0; k < 3; k++) d[o+k] = Math.round(Math.pow(c[k], 1/2.2)*255); d[o+3] = 255; }
  const tx = new THREE.DataTexture(d, n, n); tx.colorSpace = THREE.SRGBColorSpace; tx.wrapS = tx.wrapT = THREE.RepeatWrapping;
  tx.magFilter = THREE.LinearFilter; tx.minFilter = THREE.LinearMipmapLinearFilter; tx.generateMipmaps = true; tx.anisotropy = 8; tx.needsUpdate = true; return tx; }
const sandTex = noiseTex([0.60,0.52,0.39], [0.74,0.66,0.52], 256); sandTex.repeat.set(60000/400, 60000/400);
const LOOK = {
  asphalt: [[0.19,0.19,0.195],0.85], pavement: [[0.58,0.58,0.56],0.9], parking: [[0.21,0.21,0.215],0.85],
  grass: [[0.17,0.34,0.085],0.9], pitch: [[0.12,0.33,0.09],0.85], pool: [[0.065,0.40,0.50],0.05], construction: [[0.55,0.51,0.425],0.95],
  buildings: [[0.67,0.65,0.61],0.8],
  quay: [[0.66,0.58,0.45],0.8], plots: [[0.58,0.53,0.44],0.9], podium: [[0.52,0.47,0.39],0.85], kerb: [[0.70,0.70,0.68],0.8],
  mark_white: [[0.85,0.85,0.83],0.6], mark_yellow: [[0.85,0.62,0.08],0.6], rail_steel: [[0.55,0.56,0.58],0.3,0.9],
  hoarding: [[0.82,0.82,0.80],0.7], promenade: [[0.31,0.29,0.265],0.85]};
const water = new THREE.MeshPhysicalMaterial({color: lin(C.waterRGB), roughness: 0.07, metalness: 0, ior: 1.33, specularIntensity: 1, side: THREE.DoubleSide,
  polygonOffset: true, polygonOffsetFactor: -1, polygonOffsetUnits: -4});

// ---------------------------------------------------------------- UE-frame OBJ (v/f only) -> three frame, winding fixed
async function obj(url, yOff, mat, opt) {
  opt = opt || {};
  const txt = await (await fetch(url)).text();
  const V = [], F = [];
  let p = 0; const L = txt.length;
  while (p < L) { let e = txt.indexOf('\n', p); if (e < 0) e = L; const c0 = txt.charCodeAt(p), c1 = txt.charCodeAt(p+1);
    if (c0 === 118 && c1 === 32) { const s = txt.substring(p+2, e).split(' '); V.push(+s[0], +s[1], +s[2]); }
    else if (c0 === 102 && c1 === 32) { const s = txt.substring(p+2, e).split(' '); F.push(parseInt(s[0])-1, parseInt(s[2])-1, parseInt(s[1])-1); }   // 'f a//n' ok; swap = unmirror
    p = e + 1; }
  const n = V.length/3, pos = new Float32Array(n*3), ox = opt.ox || 0, oz = opt.oz || 0;
  for (let i = 0; i < n; i++) { pos[3*i] = V[3*i]/100 + C.ueE + ox; pos[3*i+1] = V[3*i+2]/100 + yOff; pos[3*i+2] = V[3*i+1]/100 + C.ueN + oz; }
  const g = new THREE.BufferGeometry(); g.setAttribute('position', new THREE.BufferAttribute(pos, 3));
  g.setIndex(n > 65535 ? new THREE.BufferAttribute(new Uint32Array(F), 1) : new THREE.BufferAttribute(new Uint16Array(F), 1));
  g.computeVertexNormals();
  const m = new THREE.Mesh(g, mat); m.castShadow = !!opt.cast; m.receiveShadow = true; m.matrixAutoUpdate = false; m.updateMatrix();
  if (opt.order !== undefined) m.renderOrder = opt.order;
  scene.add(m); return m; }
const layerMat = (key, order) => { const L = LOOK[key]; return M(L[0], L[1], L[2] || 0, {side: THREE.DoubleSide, polygonOffset: true, polygonOffsetFactor: -order, polygonOffsetUnits: -order*2}); };

// ---------------------------------------------------------------- towers: facade_palette_v1 looks by b<i> (as apply_pbr_v1)
const PAL = C.palette, matCache = {};
function roleOf(n) { n = n.toLowerCase();
  if (n.indexOf('spandrel') >= 0) return 'spandrel';
  if (n.indexOf('vision') >= 0 || n.indexOf('retail_glass') >= 0 || n.indexOf('glass') >= 0) return 'vision';
  if (n.indexOf('roof') >= 0) return 'roof';
  if (n.indexOf('parapet') >= 0 || n.indexOf('balustrade') >= 0 || n.indexOf('column') >= 0) return 'fins';
  if (n.indexOf('plant') >= 0) return 'plant';
  return 'walls'; }
function towerMat(look, role, srcMat, flat) {
  const k = look + '|' + role + '|' + (srcMat.transparent ? 't' : 'o') + (flat ? 'f' : ''); if (matCache[k]) return matCache[k];
  const L = PAL.looks[look] || {base: '#8FA3B8', sec: '#E6E2D8', refl: 0.5, rough: 0.1};
  const glassy = L.refl >= 0.4, base = hexLin(L.base, true), sec = hexLin(L.sec, true);
  let m;
  if (role === 'roof') m = M([0.42,0.42,0.41], 0.8, 0);
  else if (role === 'plant') m = M([0.06,0.20,0.10], 0.9, 0);
  else if (role === 'vision' || role === 'spandrel') {
    const c = glassy ? base : sec; const col = role === 'spandrel' ? c.clone().multiplyScalar(0.75) : c;
    m = new THREE.MeshStandardMaterial({color: col, roughness: glassy ? Math.max(0.04, L.rough) + (role === 'spandrel' ? 0.1 : 0) : 0.08,
                                        metalness: glassy ? Math.min(0.8, L.refl + 0.1) : 0.5});
  } else { const c = glassy ? sec : base; m = new THREE.MeshStandardMaterial({color: c, roughness: glassy ? 0.75 : Math.max(0.4, L.rough), metalness: 0}); }
  if (srcMat.transparent) { m.transparent = true; m.opacity = Math.max(0.45, srcMat.opacity); m.depthWrite = false; }
  m.flatShading = !!flat; m.side = srcMat.side;          // CE GLB: doubleSided, no normals (GLTFLoader would do the same)
  return (matCache[k] = m); }
async function towers(url, pos, hideNear) {
  const g = await new GLTFLoader().loadAsync(url); log('glb ' + url.split('/').pop());
  let hidden = 0, tris = 0;
  g.scene.position.set(pos[0], pos[1], pos[2]);
  g.scene.traverse(o => { if (!o.isMesh) return;
    const nm = (o.name || (o.parent && o.parent.name) || ''); const mm = /^b(\d+)/.exec(nm) || /^b(\d+)/.exec((o.parent && o.parent.name) || '');
    const idx = mm ? +mm[1] : -1;
    const look = PAL.assign[idx] || C.seeded[Math.abs(idx) % C.seeded.length];
    o.material = towerMat(look, roleOf(o.material.name || ''), o.material, !o.geometry.attributes.normal);
    o.castShadow = true; o.receiveShadow = true; o.matrixAutoUpdate = false;
    tris += (o.geometry.index ? o.geometry.index.count : o.geometry.attributes.position.count)/3; });
  g.scene.updateMatrixWorld(true);
  if (hideNear) g.scene.traverse(o => { if (!o.isMesh) return; o.geometry.computeBoundingBox();
    const c = o.geometry.boundingBox.getCenter(new THREE.Vector3()).applyMatrix4(o.matrixWorld);
    if (Math.hypot(c.x - hideNear[0], c.z - hideNear[1]) < hideNear[2]) { o.visible = false; hidden++; } });
  scene.add(g.scene); log('  tris ' + Math.round(tris) + (hideNear ? ', hidden near Burj ' + hidden : ''));
  return g.scene; }

// ---------------------------------------------------------------- post
const rt = new THREE.WebGLRenderTarget(W, H, {type: THREE.HalfFloatType, samples: 4});
const cam = new THREE.PerspectiveCamera(C.fovV, W/H, 5, 90000);
const comp = new EffectComposer(r, rt);
comp.addPass(new RenderPass(scene, cam));
let gtao = null;
if (C.ao) { gtao = new GTAOPass(scene, cam, W, H);
  gtao.normalMaterial.flatShading = true; gtao.normalMaterial.side = THREE.DoubleSide; gtao.normalMaterial.needsUpdate = true;   // CE GLB has no NORMAL: derivative normals, both sides
  gtao.output = GTAOPass.OUTPUT.Default; gtao.blendIntensity = 0.85; comp.addPass(gtao); }
comp.addPass(new ShaderPass({uniforms: {tDiffuse: {value: null}, gain: {value: new THREE.Vector3(...C.gain)}},       // UE PPV_WARM colour gain x WB 8000 K
  vertexShader: 'varying vec2 vUv; void main(){vUv=uv; gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.0);}',
  fragmentShader: 'uniform sampler2D tDiffuse; uniform vec3 gain; varying vec2 vUv; void main(){ vec4 c=texture2D(tDiffuse,vUv); gl_FragColor=vec4(c.rgb*gain, c.a); }'}));
comp.addPass(new UnrealBloomPass(new THREE.Vector2(W/2, H/2), 0.35, 0.45, 0.92));
comp.addPass(new OutputPass());
comp.addPass(new ShaderPass({uniforms: {tDiffuse: {value: null}, amt: {value: 0.35}},
  vertexShader: 'varying vec2 vUv; void main(){vUv=uv; gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.0);}',
  fragmentShader: 'uniform sampler2D tDiffuse; uniform float amt; varying vec2 vUv; void main(){ vec4 c=texture2D(tDiffuse,vUv); vec2 d=(vUv-0.5)*vec2(1.0,1.2); float v=smoothstep(0.85,0.25,length(d)); c.rgb*=mix(1.0,v,amt); gl_FragColor=c; }'}));

function setView(v) {
  cam.position.set(...v.pos); dome.position.copy(cam.position); cam.lookAt(new THREE.Vector3(...v.tgt));
  const dist = cam.position.distanceTo(new THREE.Vector3(...v.tgt));
  cam.near = Math.max(2, Math.min(40, dist*0.012)); cam.far = 90000; cam.updateProjectionMatrix();
  // shadow frustum: centre between the look target and the camera ground point, sized to what is in view
  const ctr = new THREE.Vector3(...v.tgt).lerp(new THREE.Vector3(v.pos[0], 0, v.pos[2]), 0.25); ctr.y = 0;
  const half = Math.min(4200, Math.max(350, dist*1.35));
  const sc = sun.shadow.camera; sc.left = -half; sc.right = half; sc.top = half; sc.bottom = -half; sc.near = 10; sc.far = 20000;
  sun.position.copy(ctr).addScaledVector(sunDir, 8000); sun.target.position.copy(ctr); sun.target.updateMatrixWorld(); sc.updateProjectionMatrix();
  sun.shadow.needsUpdate = true;
  if (gtao) gtao.updateGtaoMaterial({radius: Math.min(25, Math.max(3, dist*0.01)), distanceExponent: 1.5, thickness: Math.min(20, Math.max(2, dist*0.008)), scale: 1.0, samples: 16});
  return dist; }
const px = new Uint8Array(4);
window.renderView = (v) => { const t = performance.now(); setView(v); comp.render(); gl.readPixels(0, 0, 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, px); return performance.now() - t; };

(async () => {
  const gz = 0.0, lift = C.lift, gl_ = gz + lift;
  const sand = new THREE.Mesh(new THREE.PlaneGeometry(60000, 60000), new THREE.MeshStandardMaterial({map: sandTex, roughness: 0.95}));
  sand.rotation.x = -Math.PI/2; sand.position.set(0, gz - 0.2, 0); sand.receiveShadow = true; scene.add(sand);
  const D = C.base + 'data/ce/_datasmith/';
  const jobs = [];
  jobs.push(obj(D + 'ground/sea.obj', gz + 0.10, water), obj(D + 'ground/inland_water.obj', gz + 0.10, water));
  let o = 1;
  for (const k of ['s_asphalt','s_pavement','s_parking','s_grass']) jobs.push(obj(D + 'bb_v1/ctx_' + k + '.obj', gz - 0.03, layerMat(k.slice(2), o++)));
  jobs.push(obj(D + 'bb_v1/ctx_s_buildings.obj', gz - 0.03, M(LOOK.buildings[0], 0.8, 0), {cast: true}));
  for (const k of ['asphalt','pavement','parking','grass','pitch','pool','construction']) jobs.push(obj(D + 'bb_v1/ctx_' + k + '.obj', gl_, layerMat(k, o++)));
  jobs.push(obj(D + 'bb_v1/v1_canal_water.obj', gl_, water));
  for (const k of ['quay','promenade','plots','podium','kerb','mark_white','mark_yellow','rail_steel','hoarding'])
    jobs.push(obj(D + 'bb_v1/v1_' + k + '.obj', gl_, layerMat(k, o++), {cast: ['quay','rail_steel','hoarding'].indexOf(k) >= 0}));
  await Promise.all(jobs); log('context + waterfront meshes: ' + jobs.length);
  await towers(C.base + 'data/ce/_glb/sky_businessbay_v5_0.glb', [0, gl_, 0]);
  if (C.downtown) {
    await towers(C.base + 'data/ce/_glb/sky_burjkhalifa_v5_0.glb', C.dtPos, [C.burj[0], C.burj[2], 70]);
    const bg = new THREE.MeshStandardMaterial({color: hexLin('#7f96bd'), roughness: 0.08, metalness: 0.8});
    const bb = new THREE.MeshStandardMaterial({color: hexLin('#5f6b80'), roughness: 0.3, metalness: 0.6});
    const bs = new THREE.MeshStandardMaterial({color: hexLin('#c9c9c8'), roughness: 0.25, metalness: 0.9});
    const bo = {cast: true, ox: C.burj[0] - C.ueE, oz: C.burj[2] - C.ueN};
    await Promise.all([obj(D + 'bb_v1/burj_glass.obj', gz, bg, bo), obj(D + 'bb_v1/burj_band.obj', gz, bb, bo), obj(D + 'bb_v1/burj_spire.obj', gz, bs, bo)]);
    log('hero Burj placed');
  }
  const t = performance.now(); r.compile(scene, cam); window.renderView(C.views[0]); window.renderView(C.views[0]);
  log('compile + first 2 renders ' + ((performance.now()-t)/1000).toFixed(1) + ' s');
  document.title = 'ready';
})().catch(e => { document.title = 'error ' + e + ' ' + (e.stack || ''); });
</script></body></html>"""


class _RO(SimpleHTTPRequestHandler):
    """read-only static server for the page's fetches (GET/HEAD only, no listing), bound to 127.0.0.1"""
    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*"); super().end_headers()

    def list_directory(self, path):
        self.send_error(404); return None

    def log_message(self, *a):
        pass


def serve_root():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), partial(_RO, directory=ROOT))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("--") else "stills"
    plan = json.load(open(PLAN, encoding="utf-8"))
    W, H = int(arg("--w", 1080)), int(arg("--h", 1920))
    fov_v = math.degrees(2 * math.atan((42.667 / 2.0) / float(plan.get("focal_mm", 20.0))))
    views = []
    if mode == "stills":
        for ft in [float(x) for x in arg("--film", "6,21,34,42").split(",")]:
            rt = film_to_render_t(plan, ft)
            loc, tgt = cam_at(plan, rt)
            views.append({"name": "film_t%gs" % ft, "film_t": ft, "render_t": round(rt, 3), "pos": ue_to_three(loc), "tgt": ue_to_three(tgt)})
    else:
        f0, secs, fps = float(arg("--film0", 36.4)), float(arg("--secs", 5)), int(arg("--fps", 25))
        for i in range(int(round(secs * fps))):
            ft = f0 + i / float(fps)
            rt = film_to_render_t(plan, ft)
            loc, tgt = cam_at(plan, rt)
            views.append({"name": "f%04d" % i, "film_t": round(ft, 3), "render_t": round(rt, 3), "pos": ue_to_three(loc), "tgt": ue_to_three(tgt)})
    # UE SUN actor: Rotator(pitch -33, yaw -22) -> light travels (0.7776, -0.3142, -0.5446) UE; to-sun in three = (-0.7776, 0.5446, 0.3142)
    p, y = math.radians(-float(plan["district_cfg"].get("sun_elev_deg", 33.0))), math.radians(-22.0)
    fwd = (math.cos(p) * math.cos(y), math.cos(p) * math.sin(y), math.sin(p))
    sun = [-fwd[0], -fwd[2], -fwd[1]]
    burj = ue_to_three(plan["burj_cm"])
    seeded = ["BB02_sand_stone_midrise", "BB03_cream_render_lowrise", "BB07_deep_blue_glass", "BB08_white_balcony_bands", "BB04_silver_reflective"]
    cfg = {"W": W, "H": H, "fovV": fov_v, "views": views, "sun": sun, "lift": float(plan["lift_cm"]) / 100.0,
           "ueE": UE_E0 - BB_ORIGIN[0], "ueN": BB_ORIGIN[1] - UE_N0, "burj": burj,
           "dtPos": [DT_ORIGIN[0] - BB_ORIGIN[0], 0.0, BB_ORIGIN[1] - DT_ORIGIN[1]],
           "downtown": "--downtown" in sys.argv, "palette": palette_js(), "seeded": seeded,
           "exposure": float(arg("--exposure", 0.95)), "sunInt": float(arg("--sun", 4.5)), "envInt": float(arg("--env", 0.7)),
           "fogNear": float(arg("--fog-near", 6000)), "fogFar": float(arg("--fog-far", 45000)),
           "fogRGB": [float(x) for x in arg("--fog-rgb", "0.34,0.39,0.42").split(",")],
           "fill": float(arg("--fill", 0.9)),
           "waterRGB": [float(x) for x in arg("--water-rgb", "0.03,0.25,0.30").split(",")],     # UE M_BB1_Water base (0.02,0.16,0.22) reads brighter under Lumen
           "gain": [float(x) for x in arg("--gain", "1.12,1.0,0.84").split(",")],
           "envGround": [float(x) for x in arg("--env-ground", "0.75,0.60,0.42").split(",")],
           "sky": [[0.012, 0.030, 0.036], [0.05, 0.085, 0.09], [0.42, 0.38, 0.26], [0.34, 0.39, 0.42]],
           "shadowMap": int(arg("--shadow", 8192)), "ao": "--no-ao" not in sys.argv}
    out_dir = os.path.join(OUT, "stills" if mode == "stills" else "seq_" + arg("--tag", "wide"))
    os.makedirs(out_dir, exist_ok=True)
    gpu_args = ["--use-angle=d3d11", "--ignore-gpu-blocklist", "--force_high_performance_gpu", "--gpu-preference=high-performance"]
    if "--swiftshader" in sys.argv:
        gpu_args = ["--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"]
    timings = {"mode": mode, "W": W, "H": H, "fov_v_deg": round(fov_v, 2), "sun_to": [round(v, 4) for v in sun],
               "downtown": cfg["downtown"], "ao": cfg["ao"], "frames": []}
    srv = serve_root(); cfg["base"] = "http://127.0.0.1:%d/" % srv.server_address[1]
    t_launch = time.time()
    with sync_playwright() as pw:
        br = pw.chromium.launch(headless=True, args=gpu_args)
        pg = br.new_page(viewport={"width": W, "height": H})

        def handle(route, request):
            url = request.url
            if url.split("?")[0].endswith("/__nounreal_page.html"):       # page is served from memory, same origin as the data
                route.fulfill(body=PAGE, content_type="text/html")
            else:
                route.continue_()
        pg.route("**/*", handle)
        pg.add_init_script("window.CFG = %s;" % json.dumps(cfg))
        pg.goto(cfg["base"] + "__nounreal_page.html")
        pg.wait_for_function("document.title === 'ready' || document.title.startsWith('error')", timeout=900000, polling=1000)
        timings["setup_s"] = round(time.time() - t_launch, 1)
        timings["page_log"] = pg.evaluate("window.__log")
        for line in timings["page_log"]:
            print("  page:", line, flush=True)
        if pg.title() != "ready":
            print(pg.title()); sys.exit(1)
        for v in views:
            t = time.time()
            gpu_ms = pg.evaluate("v => window.renderView(v)", v)
            outp = os.path.join(out_dir, "%s.png" % v["name"])
            pg.screenshot(path=outp, clip={"x": 0, "y": 0, "width": W, "height": H})
            wall = time.time() - t
            timings["frames"].append({"name": v["name"], "film_t": v["film_t"], "render_t": v["render_t"], "render_ms": round(gpu_ms, 1), "frame_wall_s": round(wall, 3)})
            if mode == "stills" or len(timings["frames"]) % 25 == 0:
                print("%s  render %.0f ms  frame incl. PNG capture %.2f s" % (v["name"], gpu_ms, wall), flush=True)
        br.close()
    timings["total_s"] = round(time.time() - t_launch, 1)
    rs = [f["render_ms"] for f in timings["frames"]]; ws = [f["frame_wall_s"] for f in timings["frames"]]
    timings["render_ms_median"] = sorted(rs)[len(rs) // 2]; timings["frame_wall_s_median"] = sorted(ws)[len(ws) // 2]
    json.dump(timings, open(os.path.join(out_dir, "timings.json"), "w"), indent=1)
    print("setup %.1f s, render median %.0f ms, frame (render + capture) median %.2f s, total %.1f s -> %s"
          % (timings["setup_s"], timings["render_ms_median"], timings["frame_wall_s_median"], timings["total_s"], out_dir))


if __name__ == "__main__":
    main()
