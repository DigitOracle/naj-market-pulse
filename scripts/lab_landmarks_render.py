"""LAB (landmarks, research only): render before / after for each landmark - headless three.js in Playwright.

Per landmark, one PNG of four panels with IDENTICAL cameras per pair, so only the rule differs:
  1 before, whole building (stock najma_v4 build)      2 after, whole building (landmark family, wizard LOD 2)
  3 before, close-up at mid-height                      4 after, close-up at the same point
All four are clay (one neutral material, sun + sky light): the twin's in-family palette is near-black by design, and
the point of the comparison is geometry. A fifth panel tints the after-build by material slot (render-only colours,
not the rule's) so the facade elements can be told apart.

GLBs come from scripts/lab_landmarks_build.py and are served to the page from disk through Playwright's router;
three.js r160 loads from cdn.jsdelivr.net.

  python scripts/lab_landmarks_render.py   -> data/lab/landmarks/render_<slug>_b<i>.png
"""
import json
import os
import sys

from playwright.sync_api import sync_playwright

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
OUT = os.path.join(ROOT, "data", "lab", "landmarks")
W, H = 1900, 1000
PW = [0.14, 0.14, 0.24, 0.24, 0.24]      # panel widths, fraction of W

PAGE = r"""<!doctype html><html><head><meta charset="utf-8">
<style>html,body{margin:0;background:#e9e6e0;font:14px system-ui,sans-serif}canvas{display:block}
.l{position:absolute;top:8px;color:#222;background:#ffffffcc;padding:2px 6px;border-radius:3px}</style>
<script type="importmap">{"imports":{"three":"https://cdn.jsdelivr.net/npm/three@0.160.0/build/three.module.js",
"three/addons/":"https://cdn.jsdelivr.net/npm/three@0.160.0/examples/jsm/"}}</script></head><body>
<script type="module">
import * as THREE from 'three';
import {GLTFLoader} from 'three/addons/loaders/GLTFLoader.js';
const cfg = window.CFG, W = cfg.W, H = cfg.H;
const r = new THREE.WebGLRenderer({antialias:true, preserveDrawingBuffer:true});
r.setSize(W, H); r.setScissorTest(true); document.body.appendChild(r.domElement);
const clay = new THREE.MeshStandardMaterial({color:0xcdc7bd, roughness:0.85, metalness:0.0, side:THREE.DoubleSide, flatShading:true});
const TINT = cfg.tint;
function tintFor(n){ for (const [k,c] of TINT) if (n.indexOf(k) >= 0) return c; return 0xb8b2a8; }
async function load(url, mode){
  const g = await new GLTFLoader().loadAsync(url);
  const sc = new THREE.Scene(); sc.background = new THREE.Color(0xe9e6e0);
  g.scene.traverse(o => { if (o.isMesh) {
      const nm = (o.material && o.material.name) || '';
      o.material = mode === 'tint' ? new THREE.MeshStandardMaterial({color:tintFor(nm), roughness:0.6, metalness:0.1, side:THREE.DoubleSide, flatShading:true}) : clay; } });
  sc.add(g.scene);
  sc.add(new THREE.HemisphereLight(0xffffff, 0x8a8070, 1.1));
  const d = new THREE.DirectionalLight(0xffffff, 2.4); d.position.set(Math.cos(cfg.az - 0.7), 0.8, Math.sin(cfg.az - 0.7)).multiplyScalar(3000); sc.add(d);
  const d2 = new THREE.DirectionalLight(0xffffff, 0.6); d2.position.set(Math.cos(cfg.az + 1.2), 0.3, Math.sin(cfg.az + 1.2)).multiplyScalar(3000); sc.add(d2);
  const box = new THREE.Box3().setFromObject(g.scene);
  const gr = new THREE.Mesh(new THREE.PlaneGeometry(4000,4000), new THREE.MeshStandardMaterial({color:0xd8d3ca}));
  gr.rotation.x = -Math.PI/2; gr.position.y = box.min.y - 0.05; sc.add(gr);
  return {sc, box};
}
function cam(box, aspect, full, focusY){
  const c = new THREE.PerspectiveCamera(full ? 24 : 30, aspect, 1, 20000);
  const ctr = box.getCenter(new THREE.Vector3()), sz = box.getSize(new THREE.Vector3());
  const dir = new THREE.Vector3(Math.cos(cfg.az), 0.0, Math.sin(cfg.az));
  if (full) {
    const h = sz.y, w = Math.max(sz.x, sz.z);
    const dist = Math.max(h / (2*Math.tan(THREE.MathUtils.degToRad(12))) , w / (2*Math.tan(THREE.MathUtils.degToRad(12))*aspect)) * 1.08;
    const tgt = new THREE.Vector3(ctr.x, box.min.y + h*0.5, ctr.z);
    c.position.copy(tgt).addScaledVector(dir, dist).add(new THREE.Vector3(0, h*0.08, 0)); c.lookAt(tgt);
  } else {
    const tgt = new THREE.Vector3(ctr.x, box.min.y + focusY, ctr.z);
    const dist = cfg.closeW / (2*Math.tan(THREE.MathUtils.degToRad(15))*aspect) + Math.max(sz.x, sz.z) * 0.5;
    c.position.copy(tgt).addScaledVector(dir, dist).add(new THREE.Vector3(0, dist*0.12, 0)); c.lookAt(tgt);
  }
  return c;
}
(async () => {
  const before = await load(cfg.before, 'clay'), after = await load(cfg.after, 'clay'), tint = await load(cfg.after, 'tint');
  const pw = cfg.pw.map(f => Math.round(f*W));
  const panels = [[before,true],[after,true],[before,false],[after,false],[tint,false]];
  let x = 0;
  panels.forEach(([m, full], k) => {
    const w = pw[k], aspect = w / H;
    const box = after.box;                                       // same camera for both builds: frame the landmark build
    const box2 = new THREE.Box3().copy(box).union(before.box);
    const c = cam(box2, aspect, full, cfg.focusY);
    r.setViewport(x, 0, w, H); r.setScissor(x, 0, w, H); r.render(m.sc, c); x += w;
  });
  document.title = 'done';
})().catch(e => { document.title = 'error ' + e; });
</script>
<div class="l" style="left:8px">BEFORE - stock v4</div>
<div class="l" style="left:274px">AFTER - landmark</div>
<div class="l" style="left:540px">before, close-up</div>
<div class="l" style="left:996px">after, close-up</div>
<div class="l" style="left:1452px">after, tinted by slot (render only)</div>
</body></html>"""

TINT = [["spire", 0xd9dde2], ["steel_fin", 0xf2f4f6], ["steel_spandrel", 0xa9b0b8], ["reflective_glass", 0x6f8fb0],
        ["mech", 0x4a4f57], ["titanium", 0xbfb8a8], ["screen", 0x8d877b], ["twist_glass", 0x49607a],
        ["frit_glass", 0x55606c], ["void_glass", 0xdfe7ee], ["transom", 0x2c3138], ["mullion", 0x2c3138],
        ["retail_glass", 0x6a8aa8], ["roof", 0x9c968c], ["slab", 0x7c7a76]]
VIEW = {  # camera azimuth (radians, from +x toward +z), close-up focus height (fraction of height), close-up view width (m)
    "spiral_setback": (0.9, 0.55, 70.0),
    "twist": (0.6, 0.5, 55.0),
    "void_cube": (1.1, 0.45, 125.0),
}


def main():
    rp = sys.argv[sys.argv.index("--report") + 1] if "--report" in sys.argv else os.path.join(OUT, "build_report.json")
    rep = json.load(open(rp, encoding="utf-8"))
    out_dir = sys.argv[sys.argv.index("--out") + 1] if "--out" in sys.argv else OUT
    with sync_playwright() as p:
        br = p.chromium.launch(args=["--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"])
        for key, b in rep["buildings"].items():
            fam = b["family"]; az, fy, cd = VIEW[fam]
            hb = b["builds"]["lod2"]["height_m"]
            cfg = {"W": W, "H": H, "az": az, "closeW": cd, "focusY": fy * hb, "tint": TINT, "pw": PW,
                   "before": "http://lab.local/" + b["builds"]["stock"]["glb"], "after": "http://lab.local/" + b["builds"]["lod2"]["glb"]}
            pg = br.new_page(viewport={"width": W, "height": H})

            def handle(route, request):
                url = request.url
                if url.startswith("http://lab.local/data/"):
                    path = os.path.join(ROOT, url[len("http://lab.local/"):].replace("/", os.sep))
                    route.fulfill(path=path, headers={"Access-Control-Allow-Origin": "*", "Content-Type": "model/gltf-binary"})
                elif url.startswith("http://lab.local/"):
                    route.fulfill(body=PAGE, content_type="text/html")
                else:
                    route.continue_()
            pg.route("**/*", handle)
            pg.add_init_script("window.CFG = %s;" % json.dumps(cfg))
            if "--before-only" in sys.argv:                      # stock build in every panel: say so on the image
                pg.add_init_script("document.addEventListener('DOMContentLoaded', () => document.querySelectorAll('.l')"
                                   ".forEach((e, k) => e.textContent = ['STOCK v4 (today)', 'STOCK v4 (today)', 'stock, close-up',"
                                   " 'stock, close-up', 'stock, tinted by slot'][k]));")
            pg.goto("http://lab.local/index.html")
            pg.wait_for_function("document.title === 'done' || document.title.startsWith('error')", timeout=600000)
            if pg.title() != "done":
                print(key, pg.title()); continue
            outp = os.path.join(out_dir, "render_%s.png" % key.replace(":", "_b"))
            pg.screenshot(path=outp)
            print("wrote %s" % os.path.relpath(outp, ROOT), flush=True)
            pg.close()
        br.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
