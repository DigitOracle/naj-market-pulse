#!/usr/bin/env node
/**
 * glb_pack_v3.mjs — pack a TEXTURED per-building district GLB (najma_v3.cga export, merged by
 * glb_merge_per_building.py) for the phone viewer.
 *
 * Chain (each step one @gltf-transform/cli call, size printed after every step):
 *   resize  --width 1024 --height 1024   cap the ESRI.lib facade photos (some are 2048 px)
 *   webp    --quality Q                   EXT_texture_webp (native in three.js GLTFLoader)
 *   dedup                                 identical accessors / textures / materials
 *   weld                                  index the triangle soup (no normals in the file: the viewer flat-shades)
 *   meshopt --level high                  quantize + EXT_meshopt_compression (viewer has the decoder)
 *
 * Usage:  node scripts/glb_pack_v3.mjs data/ce/_glb/sky_businessbay_v3_0.glb [--out <file>] [--quality 72] [--max 1024]
 *         The input is kept as <input>.merged.glb (uncompressed, re-packable without CityEngine); the packed
 *         result overwrites <input> unless --out is given. Writes <input>.pack.json with the stage sizes.
 */
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { spawnSync } from 'node:child_process';

const argv = process.argv.slice(2);
const opt = (n, d) => { const i = argv.indexOf(n); return i === -1 ? d : argv[i + 1]; };
const input = path.resolve(argv.find((a) => !a.startsWith('--') && a.endsWith('.glb')) || 'data/ce/_glb/sky_businessbay_v3_0.glb');
const out = path.resolve(opt('--out', input));
const Q = String(opt('--quality', '72'));
const MAX = String(opt('--max', '1024'));
if (!fs.existsSync(input)) { console.error('no input', input); process.exit(2); }

const merged = input.replace(/\.glb$/, '.merged.glb');
if (out === input) fs.copyFileSync(input, merged);
const mb = (f) => (fs.statSync(f).size / 1048576).toFixed(3) + ' MB';
const scratch = fs.mkdtempSync(path.join(os.tmpdir(), 'scratch_facade_pack_'));
process.on('exit', () => { try { fs.rmSync(scratch, { recursive: true, force: true }); } catch {} });

const CLI = process.platform === 'win32' ? 'npx.cmd' : 'npx';
const base = ['--yes', '@gltf-transform/cli@latest'];
function run(step, args, src, dst) {
  const t0 = Date.now();
  const r = spawnSync(CLI, [...base, step, src, dst, ...args], { stdio: ['ignore', 'pipe', 'pipe'], shell: process.platform === 'win32' });
  if (r.status !== 0) { console.error(`step ${step} failed\n${r.stdout}\n${r.stderr}`); process.exit(1); }
  console.log(`  ${step.padEnd(8)} ${mb(dst).padStart(11)}   ${((Date.now() - t0) / 1000).toFixed(1)} s`);
  return fs.statSync(dst).size;
}
console.log(`input    ${mb(input)}   ${input}`);
const stages = { input: fs.statSync(input).size };
let cur = out === input ? merged : input;
const s1 = path.join(scratch, '1_resize.glb'); stages.resize = run('resize', ['--width', MAX, '--height', MAX], cur, s1);
const s2 = path.join(scratch, '2_webp.glb'); stages.webp = run('webp', ['--quality', Q], s1, s2);
const s3 = path.join(scratch, '3_dedup.glb'); stages.dedup = run('dedup', [], s2, s3);
const s4 = path.join(scratch, '4_weld.glb'); stages.weld = run('weld', [], s3, s4);
const s5 = path.join(scratch, '5_meshopt.glb'); stages.meshopt = run('meshopt', ['--level', 'high'], s4, s5);

// verify: GLB header, JSON, extensions, node/mesh count, names, webp images
const b = fs.readFileSync(s5);
if (b.readUInt32LE(0) !== 0x46546c67 || b.readUInt32LE(8) !== b.length) { console.error('bad GLB'); process.exit(1); }
const js = JSON.parse(b.subarray(20, 20 + b.readUInt32LE(12)).toString('utf8'));
const req = js.extensionsRequired || [];
const imgs = js.images || [];
const webp = imgs.filter((i) => i.mimeType === 'image/webp').length;
const tris = js.meshes.reduce((a, m) => a + m.primitives.reduce((x, p) => x + (p.indices != null ? js.accessors[p.indices].count / 3 : js.accessors[p.attributes.POSITION].count / 3), 0), 0);
const named = js.nodes.filter((n) => /^b\d+_/.test(n.name || '')).length;
const summary = { input, output: out, mergedKept: out === input ? merged : null, quality: Number(Q), maxTexture: Number(MAX), stages,
  meshes: js.meshes.length, nodes: js.nodes.length, namedBuildings: named, triangles: Math.round(tris), materials: (js.materials || []).length,
  textures: (js.textures || []).length, images: imgs.length, webpImages: webp, extensionsRequired: req, extensionsUsed: js.extensionsUsed || [] };
if (!req.includes('EXT_meshopt_compression')) { console.error('meshopt missing'); process.exit(1); }
if (webp !== imgs.length) { console.error('not all images are webp', webp, imgs.length); process.exit(1); }
fs.copyFileSync(s5, out);
fs.writeFileSync(input.replace(/\.glb$/, '.pack.json'), JSON.stringify(summary, null, 2));
console.log(`output   ${mb(out)}   ${out}`);
console.log(`  ${js.meshes.length} meshes / ${named} named buildings, ${Math.round(tris)} tris, ${(js.materials || []).length} materials, ${imgs.length} images (webp ${webp}), required ${req.join(',')}`);
