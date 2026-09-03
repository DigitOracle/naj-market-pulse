#!/usr/bin/env node
/**
 * glb_optimize.mjs — Najma skyline viewer: per-district GLB optimisation.
 *
 * Runs the glTF Transform CLI (@gltf-transform/cli, fetched with `npx --yes`) over
 * every  data/ce/_glb/sky_*.glb  and writes an optimised copy with the SAME file
 * name to  data/ce/_glb/opt/ . Originals are never touched.
 *
 * Pipeline per file (each step is one CLI invocation, intermediates in a scratch dir):
 *   1. dedup     — merge duplicate accessors / materials / meshes
 *   2. weld      — index the geometry, merge identical vertices (tolerance 0, lossless)
 *   3. simplify  — OPTIONAL, merged-mesh districts only (--simplify), meshoptimizer
 *                  --ratio 0.6 --error 0.001  (error is a fraction of mesh extent!)
 *   4. quantize  — KHR_mesh_quantization, 16-bit positions, per-mesh volume
 *   5. meshopt   — EXT_meshopt_compression, level high
 *
 * Every output is re-parsed and checked (GLB header, JSON chunk, extensionsRequired
 * has EXT_meshopt_compression, mesh/node counts and node order preserved). A file
 * that fails any check is deleted from opt/ and reported.
 *
 * Usage:
 *   node scripts/glb_optimize.mjs                    # all sky_*.glb, no simplify
 *   node scripts/glb_optimize.mjs --simplify         # + simplify merged-mesh models
 *   node scripts/glb_optimize.mjs --only dubaimarina # substring filter on file name
 *   node scripts/glb_optimize.mjs --in <dir> --out <dir> --ratio 0.6 --error 0.001
 *   node scripts/glb_optimize.mjs --bin <path/to/cli.js>   # skip the npx lookup
 *   node scripts/glb_optimize.mjs --dry-run          # print plan only
 *
 * Viewer side: the outputs REQUIRE the Meshopt decoder in GLTFLoader — see
 * scripts/glb_optimize.README.md for the exact three.js snippet.
 */

import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REPO = path.resolve(__dirname, '..');

// ---------------------------------------------------------------- args
const argv = process.argv.slice(2);
function opt(name, dflt) {
  const i = argv.indexOf(name);
  if (i === -1) return dflt;
  const v = argv[i + 1];
  return v === undefined || v.startsWith('--') ? true : v;
}
const IN_DIR = path.resolve(opt('--in', path.join(REPO, 'data', 'ce', '_glb')));
const OUT_DIR = path.resolve(opt('--out', path.join(IN_DIR, 'opt')));
const ONLY = opt('--only', null);
const SIMPLIFY = argv.includes('--simplify');
const RATIO = String(opt('--ratio', '0.6'));
const ERROR = String(opt('--error', '0.001'));
const POS_BITS = String(opt('--position-bits', '16'));
const LEVEL = String(opt('--level', 'high'));
const DRY = argv.includes('--dry-run');
const BIN_OVERRIDE = opt('--bin', process.env.GLTF_TRANSFORM_BIN || null);
// A model with more than this many meshes is treated as "per-building" (never simplified,
// so that mesh index == building index survives for the anchors file).
const PER_BUILDING_MIN_MESHES = 50;
// Rough 4G planning figure (effective, after TCP ramp-up): 1.5 MB/s ≈ 12 Mbit/s.
const MBPS_4G = 1.5;

// ---------------------------------------------------------------- scratch dir
const SCRATCH = fs.mkdtempSync(path.join(os.tmpdir(), 'scratch_glb_'));
process.on('exit', () => { try { fs.rmSync(SCRATCH, { recursive: true, force: true }); } catch {} });

// ---------------------------------------------------------------- GLB parsing
export function readGlbJson(file) {
  const b = fs.readFileSync(file);
  if (b.length < 20) throw new Error('file too small to be a GLB');
  if (b.readUInt32LE(0) !== 0x46546c67) throw new Error('bad GLB magic');
  const version = b.readUInt32LE(4);
  if (version !== 2) throw new Error(`unsupported GLB version ${version}`);
  const total = b.readUInt32LE(8);
  if (total !== b.length) throw new Error(`GLB length field ${total} != file size ${b.length}`);
  const chunkLen = b.readUInt32LE(12);
  const chunkType = b.readUInt32LE(16);
  if (chunkType !== 0x4e4f534a) throw new Error('first chunk is not JSON');
  const json = JSON.parse(b.subarray(20, 20 + chunkLen).toString('utf8'));
  return { json, bytes: b.length };
}
export function summarise(json) {
  const meshes = json.meshes || [];
  const nodes = json.nodes || [];
  let tris = 0, verts = 0;
  for (const m of meshes) for (const p of m.primitives || []) {
    const pos = json.accessors[p.attributes.POSITION];
    verts += pos.count;
    tris += p.indices != null ? json.accessors[p.indices].count / 3 : pos.count / 3;
  }
  return {
    meshes: meshes.length,
    nodes: nodes.length,
    nodeNames: nodes.map((n) => n.name || ''),
    meshNames: meshes.map((m) => m.name || ''),
    materials: (json.materials || []).length,
    verts, tris: Math.round(tris),
    required: json.extensionsRequired || [],
    used: json.extensionsUsed || [],
  };
}

// ---------------------------------------------------------------- CLI resolution
function run(cmd, args, opts = {}) {
  // npm/npx are .cmd shims on Windows and need a shell; pass ONE pre-joined string so
  // Node does not warn about unescaped args (the args here are fixed constants).
  const r = cmd === 'npx' || cmd === 'npm'
    ? spawnSync([cmd, ...args].join(' '), { encoding: 'utf8', shell: true, ...opts })
    : spawnSync(cmd, args, { encoding: 'utf8', ...opts });
  return { code: r.status, out: (r.stdout || '') + (r.stderr || '') };
}
function resolveCli() {
  if (BIN_OVERRIDE) return { kind: 'node', bin: path.resolve(BIN_OVERRIDE) };
  // 1. Warm the npx cache (this is the one slow network step, ~30-60 s the first time).
  process.stdout.write('resolving @gltf-transform/cli via npx --yes ... ');
  const v = run('npx', ['--yes', '@gltf-transform/cli@latest', '--version']);
  const version = (v.out.match(/(\d+\.\d+\.\d+)\s*$/m) || [])[1];
  if (v.code !== 0 || !version) {
    console.log('FAILED\n' + v.out);
    throw new Error('could not run npx @gltf-transform/cli@latest');
  }
  console.log(`v${version}`);
  // 2. Find the cached install so each step can call node directly (~0.7 s instead of ~40 s).
  const cache = run('npm', ['config', 'get', 'cache']).out.trim();
  const npx = path.join(cache, '_npx');
  if (fs.existsSync(npx)) {
    for (const h of fs.readdirSync(npx)) {
      const pkg = path.join(npx, h, 'node_modules', '@gltf-transform', 'cli', 'package.json');
      if (!fs.existsSync(pkg)) continue;
      const meta = JSON.parse(fs.readFileSync(pkg, 'utf8'));
      if (meta.version === version) {
        return { kind: 'node', bin: path.join(path.dirname(pkg), meta.bin['gltf-transform'] || 'bin/cli.js'), version };
      }
    }
  }
  console.log('  (cached install not found - falling back to npx per step, this will be slow)');
  return { kind: 'npx', version };
}
function gltf(cli, args) {
  return cli.kind === 'node'
    ? run('node', [cli.bin, ...args])
    : run('npx', ['--yes', '@gltf-transform/cli@latest', ...args]);
}

// ---------------------------------------------------------------- helpers
const fmtKB = (n) => (n / 1024).toFixed(n >= 1024 * 1024 ? 0 : 1).padStart(7) + ' KB';
const pad = (s, n) => String(s).padEnd(n);
const rpad = (s, n) => String(s).padStart(n);

// ---------------------------------------------------------------- verify-only mode
// node scripts/glb_optimize.mjs --verify   (re-checks every opt/sky_*.glb against its original)
function verifyOnly() {
  const files = fs.readdirSync(OUT_DIR).filter((f) => /^sky_.*\.glb$/i.test(f)).sort();
  let bad = 0;
  for (const name of files) {
    const problems = [];
    try {
      const o = summarise(readGlbJson(path.join(OUT_DIR, name)).json);
      if (!o.required.includes('EXT_meshopt_compression')) problems.push('extensionsRequired lacks EXT_meshopt_compression');
      const srcPath = path.join(IN_DIR, name);
      if (fs.existsSync(srcPath)) {
        const s = summarise(readGlbJson(srcPath).json);
        if (s.meshes !== o.meshes) problems.push(`mesh count ${s.meshes} -> ${o.meshes}`);
        if (s.nodes !== o.nodes) problems.push(`node count ${s.nodes} -> ${o.nodes}`);
        if (s.nodeNames.join(' ') !== o.nodeNames.join(' ')) problems.push('node order/names changed');
      }
      console.log(`${problems.length ? 'x' : 'ok'} ${pad(name, 38)} meshes=${o.meshes} nodes=${o.nodes} tris=${o.tris} required=${o.required.join('+')}${problems.length ? '  ' + problems.join('; ') : ''}`);
    } catch (e) { problems.push(e.message); console.log(`x ${pad(name, 38)} ${e.message}`); }
    if (problems.length) bad++;
  }
  console.log(`${files.length} files, ${bad} with problems`);
  if (bad) process.exitCode = 1;
}

// ---------------------------------------------------------------- main
function main() {
  if (argv.includes('--verify')) return verifyOnly();
  const t0 = Date.now();
  if (!fs.existsSync(IN_DIR)) throw new Error(`input dir not found: ${IN_DIR}`);
  let files = fs.readdirSync(IN_DIR).filter((f) => /^sky_.*\.glb$/i.test(f)).sort();
  if (ONLY) files = files.filter((f) => f.includes(ONLY));
  if (!files.length) { console.log('nothing to do'); return; }
  fs.mkdirSync(OUT_DIR, { recursive: true });

  console.log(`in : ${IN_DIR}\nout: ${OUT_DIR}\nfiles: ${files.length}  simplify: ${SIMPLIFY ? `on (ratio ${RATIO}, error ${ERROR})` : 'off'}  position bits: ${POS_BITS}  meshopt: ${LEVEL}`);
  if (DRY) { files.forEach((f) => console.log('  ' + f)); return; }

  const cli = resolveCli();
  const rows = [];
  const failures = [];

  for (const name of files) {
    const src = path.join(IN_DIR, name);
    const dst = path.join(OUT_DIR, name);
    const tf = Date.now();
    let before;
    try {
      const { json, bytes } = readGlbJson(src);
      before = { bytes, ...summarise(json) };
    } catch (e) {
      failures.push({ name, step: 'read-input', err: e.message });
      console.log(`x ${name}: cannot read input (${e.message})`);
      continue;
    }
    const perBuilding = before.meshes > PER_BUILDING_MIN_MESHES;
    const kind = perBuilding ? 'per-building' : 'merged';
    const doSimplify = SIMPLIFY && !perBuilding;

    const steps = [
      ['dedup', []],
      ['weld', []],
      ...(doSimplify ? [['simplify', ['--ratio', RATIO, '--error', ERROR]]] : []),
      ['quantize', ['--quantize-position', POS_BITS, '--quantization-volume', 'mesh']],
      ['meshopt', ['--level', LEVEL, '--quantize-position', POS_BITS]],
    ];

    let cur = src;
    let failed = null;
    process.stdout.write(`${pad(name, 38)} ${pad(kind, 12)} `);
    for (let i = 0; i < steps.length; i++) {
      const [cmd, extra] = steps[i];
      const next = path.join(SCRATCH, `${path.basename(name, '.glb')}.${i}.${cmd}.glb`);
      const r = gltf(cli, [cmd, cur, next, ...extra]);
      if (r.code !== 0 || !fs.existsSync(next)) {
        failed = { name, step: cmd, err: r.out.trim().split('\n').slice(-3).join(' | ') };
        break;
      }
      process.stdout.write(cmd[0]);
      cur = next;
    }
    if (failed) { failures.push(failed); console.log(`  FAILED at ${failed.step}: ${failed.err}`); continue; }

    // ---- verify, then move into place
    let after;
    try {
      const { json, bytes } = readGlbJson(cur);
      after = { bytes, ...summarise(json) };
      const problems = [];
      if (!after.required.includes('EXT_meshopt_compression')) problems.push('extensionsRequired lacks EXT_meshopt_compression');
      if (after.meshes !== before.meshes) problems.push(`mesh count ${before.meshes} -> ${after.meshes}`);
      if (after.nodes !== before.nodes) problems.push(`node count ${before.nodes} -> ${after.nodes}`);
      if (after.nodeNames.join(' ') !== before.nodeNames.join(' ')) problems.push('node names/order changed');
      if (after.materials !== before.materials) problems.push(`material count ${before.materials} -> ${after.materials} (dedup merged identical materials - viewer classifies by colour, so this is only informational)`);
      const hard = problems.filter((p) => !p.includes('informational'));
      if (hard.length) throw new Error(hard.join('; '));
      if (problems.length) after.note = problems.join('; ');
    } catch (e) {
      failures.push({ name, step: 'verify', err: e.message });
      console.log(`  VERIFY FAILED: ${e.message}`);
      continue;
    }
    fs.copyFileSync(cur, dst);
    const secs = ((Date.now() - tf) / 1000).toFixed(1);
    rows.push({ name, kind, before, after, secs, simplified: doSimplify });
    console.log(`  ${fmtKB(before.bytes)} -> ${fmtKB(after.bytes)}  (${(100 * after.bytes / before.bytes).toFixed(0)}%)  ${secs}s`);
  }

  // ---- table
  const W = { name: 38, kind: 12, b: 11, a: 11, pct: 6, tri: 20, t4g: 7 };
  console.log('\n' + pad('district file', W.name) + pad('kind', W.kind) + rpad('before', W.b) + rpad('after', W.a) + rpad('%', W.pct) + rpad('tris before>after', W.tri) + rpad('4G s', W.t4g) + '  notes');
  console.log('-'.repeat(W.name + W.kind + W.b + W.a + W.pct + W.tri + W.t4g + 8));
  let tb = 0, ta = 0;
  for (const r of rows) {
    tb += r.before.bytes; ta += r.after.bytes;
    console.log(
      pad(r.name, W.name) + pad(r.kind + (r.simplified ? '*' : ''), W.kind) +
      rpad(fmtKB(r.before.bytes), W.b) + rpad(fmtKB(r.after.bytes), W.a) +
      rpad((100 * r.after.bytes / r.before.bytes).toFixed(0) + '%', W.pct) +
      rpad(`${r.before.tris.toLocaleString()}>${r.after.tris.toLocaleString()}`, W.tri) +
      rpad((r.after.bytes / (MBPS_4G * 1024 * 1024)).toFixed(2), W.t4g) +
      '  ' + (r.after.note || ''),
    );
  }
  console.log('-'.repeat(W.name + W.kind + W.b + W.a + W.pct + W.tri + W.t4g + 8));
  console.log(pad(`TOTAL (${rows.length} files)`, W.name + W.kind) + rpad(fmtKB(tb), W.b) + rpad(fmtKB(ta), W.a) + rpad(tb ? (100 * ta / tb).toFixed(0) + '%' : '-', W.pct));
  if (rows.some((r) => r.simplified)) console.log('* = simplify applied');
  console.log(`\nlargest output: ${rows.length ? rows.reduce((m, r) => (r.after.bytes > m.after.bytes ? r : m)).name : '-'}  ->  ${rows.length ? fmtKB(Math.max(...rows.map((r) => r.after.bytes))) : ''}  (~${rows.length ? (Math.max(...rows.map((r) => r.after.bytes)) / (MBPS_4G * 1024 * 1024)).toFixed(2) : '-'} s at ${MBPS_4G} MB/s)`);
  console.log(`failed: ${failures.length}`);
  for (const f of failures) console.log(`  x ${f.name}  [${f.step}]  ${f.err}`);
  console.log(`total time: ${((Date.now() - t0) / 1000).toFixed(1)} s`);

  // machine-readable report next to the outputs
  const report = {
    generated: new Date().toISOString(),
    tool: `@gltf-transform/cli ${cli.version || '(custom bin)'}`,
    settings: { simplify: SIMPLIFY, ratio: RATIO, error: ERROR, positionBits: Number(POS_BITS), meshoptLevel: LEVEL },
    files: rows.map((r) => ({
      name: r.name, kind: r.kind, simplified: r.simplified,
      bytesBefore: r.before.bytes, bytesAfter: r.after.bytes,
      trisBefore: r.before.tris, trisAfter: r.after.tris,
      vertsBefore: r.before.verts, vertsAfter: r.after.verts,
      meshes: r.after.meshes, nodes: r.after.nodes, extensionsRequired: r.after.required, note: r.after.note || null,
    })),
    failures,
  };
  fs.writeFileSync(path.join(OUT_DIR, '_optimize_report.json'), JSON.stringify(report, null, 2));
  if (failures.length) process.exitCode = 1;
}

main();
