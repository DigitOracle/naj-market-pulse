"""LAB (context / scenery, research only): headless preview of the CityEngine-generated scenery with the current v5
buildings - three.js r160 in Playwright (Chromium, ANGLE D3D11 on the laptop GPU; SwiftShader if that is refused).

Loads, all in the SAME local v5 frame (no transforms added), the files manifest.json lists:
  ground_<slug>_v5_meshopt.glb                           (MeshoptDecoder, as the web viewer does)
  vegetation_ / furniture_ / props_<slug>_v5.glb         (EXT_mesh_gpu_instancing -> THREE.InstancedMesh)
  data/ce/_glb/sky_<slug>_v5_0.glb                       (the current buildings, local frame, aligned)
Look: sun elevation 33 deg and colour (1.0, 0.88, 0.74) as L_BB_v1 (bb_v0_prep DISTRICT sun_elev_deg, ue_bb_v1_build
PPV); sky from three's Sky model (PMREM environment for the glossy water / glass); haze. The ground layers are
centimetres apart (Unreal's stack) - drawn with polygonOffset by the draw_order the GLB carries in node extras.
Cameras: an aerial oblique of the district, a 70 m view down the M06 boulevard, a street-level view at 1.7 m on
Unreal's M06 boulevard glide path (bb_v1_plan keys t = 32-40 s, which Unreal flies at 12 m), and eye level at the
promenade cafes (the densest run of bb_v1_plan prom_cafes).

  python scripts/lab_context_render.py [businessbay] [--views v.json --prefix cand_]
      -> data/lab/context/<slug>/render_aerial.png, render_aerial_low.png, render_street.png, render_cafe.png (+ render_info.json)
"""
import functools
import http.server
import json
import os
import sys
import threading
import time

from playwright.sync_api import sync_playwright

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lab_context_common as C

ARGS = sys.argv[1:]
SLUG = ([a for i, a in enumerate(ARGS) if not a.startswith("--") and (i == 0 or ARGS[i - 1] not in ("--views", "--prefix"))] or ["businessbay"])[0]
OUT = C.lab_dir(SLUG)
PREFIX = ARGS[ARGS.index("--prefix") + 1] if "--prefix" in ARGS else "render_"
W, H = 1920, 1080

VIEWS = {  # local metres: x east, y up, z south
    "aerial": {"pos": [260, 720, 900], "target": [-560, 0, -330], "fov": 38, "near": 5, "far": 16000,
               "shadow": {"centre": [-500, 0, -250], "half": 1500, "map": 4096}, "fog": [2600, 14000]},
    "aerial_low": {"pos": [-300, 70, -540], "target": [0, 0, -370], "fov": 50, "near": 1, "far": 12000,
                   "shadow": {"centre": [-120, 0, -420], "half": 350, "map": 4096}, "fog": [1500, 9000]},
    "street": {"pos": [-117.4, 1.7, -444.0], "target": [-29.4, 10.0, -389.0], "fov": 62, "near": 0.25, "far": 9000,
               "shadow": {"centre": [-50, 0, -400], "half": 220, "map": 4096}, "fog": [400, 7000]},
    "cafe": {"pos": [187.4, 1.7, -1317.8], "target": [99.6, 0.8, -1354.0], "fov": 58, "near": 0.2, "far": 9000,
             "shadow": {"centre": [130, 0, -1330], "half": 120, "map": 4096}, "fog": [400, 7000]},
}

PAGE = r"""<!doctype html><html><head><meta charset="utf-8">
<style>html,body{margin:0;background:#cfd8e3;overflow:hidden}canvas{display:block}
#cap{position:absolute;left:14px;bottom:12px;font:13px/1.35 system-ui,Segoe UI,sans-serif;color:#1d2226;background:#ffffffcc;padding:6px 10px;border-radius:4px;max-width:1500px}</style>
<script type="importmap">{"imports":{"three":"https://cdn.jsdelivr.net/npm/three@0.160.0/build/three.module.js",
"three/addons/":"https://cdn.jsdelivr.net/npm/three@0.160.0/examples/jsm/"}}</script></head><body><div id="cap"></div>
<script type="module">
import * as THREE from 'three';
import {GLTFLoader} from 'three/addons/loaders/GLTFLoader.js';
import {MeshoptDecoder} from 'three/addons/libs/meshopt_decoder.module.js';
import {Sky} from 'three/addons/objects/Sky.js';
const cfg = window.CFG;
const r = new THREE.WebGLRenderer({antialias:true, preserveDrawingBuffer:true, powerPreference:'high-performance'});
r.setSize(cfg.W, cfg.H); r.setPixelRatio(1);
r.outputColorSpace = THREE.SRGBColorSpace; r.toneMapping = THREE.ACESFilmicToneMapping; r.toneMappingExposure = 0.8;
r.shadowMap.enabled = true; r.shadowMap.type = THREE.PCFSoftShadowMap;
document.body.appendChild(r.domElement);
const scene = new THREE.Scene();
// sun: elevation 33 deg, from the south-west (afternoon), Unreal v1 sun colour
const el = THREE.MathUtils.degToRad(33), az = THREE.MathUtils.degToRad(cfg.sunAz);
const sunDir = new THREE.Vector3(Math.sin(az) * Math.cos(el), Math.sin(el), -Math.cos(az) * Math.cos(el)).normalize();
const sky = new Sky(); sky.scale.setScalar(20000);
const su = sky.material.uniforms; su.turbidity.value = 7; su.rayleigh.value = 1.6; su.mieCoefficient.value = 0.006; su.mieDirectionalG.value = 0.82;
su.sunPosition.value.copy(sunDir);
const pm = new THREE.PMREMGenerator(r); const skyScene = new THREE.Scene(); skyScene.add(sky.clone());
scene.environment = pm.fromScene(skyScene, 0, 1, 30000).texture;
scene.add(sky);
const sun = new THREE.DirectionalLight(new THREE.Color(1.0, 0.88, 0.74), 2.3);
sun.castShadow = true; sun.shadow.bias = -0.0004; sun.shadow.normalBias = 0.6;
scene.add(sun); scene.add(sun.target);
scene.add(new THREE.HemisphereLight(0xbfd2e8, 0x8a7a62, 0.2));
const haze = new THREE.Color(0.74, 0.78, 0.82);
scene.fog = new THREE.Fog(haze, 3000, 14000);
const loader = new GLTFLoader(); loader.setMeshoptDecoder(MeshoptDecoder);
const stats = {};
function count(root, key){ let n = 0, inst = 0, tri = 0; root.traverse(o => { if (o.isMesh) { n++; const k = o.isInstancedMesh ? o.count : 1; inst += k;
  const g = o.geometry; tri += k * ((g.index ? g.index.count : g.attributes.position.count) / 3); } }); stats[key] = {meshes: n, objects: inst, triangles: tri}; }
(async () => {
  const t0 = performance.now();
  const all = await Promise.all([cfg.ground, cfg.buildings, ...cfg.layers].map(u => loader.loadAsync(u)));
  const ground = all[0], bld = all[1];
  const dress = {scene: new THREE.Group()}; all.slice(2).forEach(g => dress.scene.add(g.scene));
  ground.scene.traverse(o => { if (o.isMesh) {
      const ord = (o.userData && o.userData.draw_order != null) ? o.userData.draw_order : (o.parent && o.parent.userData.draw_order) || 0;
      const m = o.material; m.polygonOffset = true; m.polygonOffsetFactor = -1; m.polygonOffsetUnits = -6 * ord; m.side = THREE.FrontSide;
      if (m.map) { m.map.anisotropy = 8; }
      m.envMapIntensity = (m.roughness < 0.2) ? 1.0 : 0.5;
      o.receiveShadow = true; o.castShadow = (m.name === 'ctx_quay'); o.renderOrder = ord; } });
  dress.scene.traverse(o => { if (o.isMesh) { o.castShadow = true; o.receiveShadow = true; o.frustumCulled = false; o.material.envMapIntensity = 0.5; } });
  bld.scene.traverse(o => { if (o.isMesh) { o.castShadow = true; o.receiveShadow = true;
      const ms = Array.isArray(o.material) ? o.material : [o.material]; ms.forEach(m => { if (m.roughness === 1) m.roughness = 0.75; }); } });
  scene.add(ground.scene, dress.scene, bld.scene);
  count(ground.scene, 'ground'); count(dress.scene, 'dressing'); count(bld.scene, 'buildings');
  window.LOADED = {ms: Math.round(performance.now() - t0), stats};
  document.title = 'loaded';
})().catch(e => { document.title = 'error ' + e; });
window.renderView = (v) => {
  const cam = new THREE.PerspectiveCamera(v.fov, cfg.W / cfg.H, v.near, v.far);
  cam.position.set(...v.pos); cam.lookAt(new THREE.Vector3(...v.target));
  const c = new THREE.Vector3(...v.shadow.centre), h = v.shadow.half;
  sun.position.copy(c).addScaledVector(sunDir, 4000); sun.target.position.copy(c); sun.target.updateMatrixWorld();
  const sc = sun.shadow.camera; sc.left = -h; sc.right = h; sc.top = h; sc.bottom = -h; sc.near = 10; sc.far = 9000; sc.updateProjectionMatrix();
  sun.shadow.mapSize.set(v.shadow.map, v.shadow.map); if (sun.shadow.map) { sun.shadow.map.dispose(); sun.shadow.map = null; }
  scene.fog.near = v.fog[0]; scene.fog.far = v.fog[1];
  document.getElementById('cap').textContent = v.caption;
  const t = performance.now(); r.render(scene, cam); r.getContext().finish();
  return {render_ms: Math.round(performance.now() - t), calls: r.info.render.calls, triangles: r.info.render.triangles};
};
</script></body></html>"""


class Files(http.server.SimpleHTTPRequestHandler):
    """127.0.0.1 only: /ctx/<file> from the lab folder, /glb/<file> from data/ce/_glb, / = the page. Playwright's
    route.fulfill pushes bodies through the driver protocol (base64) - a 182 MB building GLB crashed the page that way."""
    page = b""

    def log_message(self, *a):
        pass

    def do_GET(self):
        u = self.path.split("?")[0]
        if u.startswith("/ctx/") or u.startswith("/glb/"):
            base = OUT if u.startswith("/ctx/") else os.path.join(C.CE, "_glb")
            fp = os.path.join(base, os.path.basename(u))
            if not os.path.isfile(fp):
                self.send_error(404); return
            self.send_response(200)
            self.send_header("Content-Type", "model/gltf-binary"); self.send_header("Content-Length", str(os.path.getsize(fp)))
            self.send_header("Access-Control-Allow-Origin", "*"); self.end_headers()
            with open(fp, "rb") as fh:
                while True:
                    b = fh.read(1 << 20)
                    if not b:
                        break
                    self.wfile.write(b)
        else:
            self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(self.page))); self.end_headers(); self.wfile.write(self.page)


def main():
    man = json.load(open(os.path.join(OUT, "manifest.json"), encoding="utf-8"))
    ground = next(l["file"] for l in man["layers"] if l["layer"] == "ground")
    layers = [l["file"] for l in man["layers"] if l["layer"] != "ground"]
    Files.page = PAGE.encode("utf-8")
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Files)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d" % srv.server_address[1]
    cfg = {"W": W, "H": H, "sunAz": 235.0,
           "ground": base + "/ctx/" + ground, "layers": [base + "/ctx/" + f for f in layers],
           "buildings": base + "/glb/sky_%s_v5_0.glb" % SLUG}
    info = {"slug": SLUG, "built": time.strftime("%Y-%m-%dT%H:%M:%S"), "files": cfg, "views": {}}
    with sync_playwright() as p:
        br = None
        for args in (["--use-angle=d3d11", "--ignore-gpu-blocklist", "--enable-gpu"], ["--use-angle=swiftshader", "--enable-unsafe-swiftshader"]):
            try:
                br = p.chromium.launch(args=args); info["chromium_args"] = args; break
            except Exception as e:
                print("launch failed with %s: %s" % (args, str(e)[:120]))
        pg = br.new_page(viewport={"width": W, "height": H})
        pg.on("console", lambda m: print("  [page]", m.text) if m.type in ("error", "warning") else None)

        pg.add_init_script("window.CFG = %s;" % json.dumps(cfg))
        t = time.time()
        pg.goto(base + "/index.html")
        pg.wait_for_function("document.title === 'loaded' || document.title.startsWith('error')", timeout=900000)
        if pg.title() != "loaded":
            sys.exit("page: %s" % pg.title())
        info["renderer"] = pg.evaluate("""() => { const g = document.querySelector('canvas').getContext('webgl2'); const e = g.getExtension('WEBGL_debug_renderer_info');
                                                return e ? g.getParameter(e.UNMASKED_RENDERER_WEBGL) : g.getParameter(g.RENDERER); }""")
        info["load"] = pg.evaluate("window.LOADED"); info["load_s"] = round(time.time() - t, 1)
        print("loaded in %.1f s on %s: %s" % (time.time() - t, info["renderer"], info["load"]["stats"]))
        views = json.load(open(ARGS[ARGS.index("--views") + 1], encoding="utf-8")) if "--views" in ARGS else VIEWS
        for name, v in views.items():
            v = dict(v)
            v["caption"] = ("LAB research render - %s %s - ground + dressing generated by lab_context.rpk (CityEngine 2026.1 CGA, PyPRT); placements = what Unreal's "
                            "film placed (bb_v1_plan) + the city JSONs; palette = Unreal L_BB_v1 values; buildings = sky_%s_v5_0.glb (unchanged)") % (SLUG, name, SLUG)
            res = pg.evaluate("v => window.renderView(v)", v)
            pg.wait_for_timeout(300)
            outp = os.path.join(OUT, "%s%s.png" % (PREFIX, name))
            pg.screenshot(path=outp)
            info["views"][name] = {"png": os.path.relpath(outp, C.ROOT).replace("\\", "/"), **{k: v[k] for k in ("pos", "target", "fov")}, **res}
            print("  %s: %s  %s" % (name, os.path.relpath(outp, C.ROOT), res))
        br.close()
    srv.shutdown()
    if PREFIX == "render_":
        json.dump(info, open(os.path.join(OUT, "render_info.json"), "w", encoding="utf-8"), indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
