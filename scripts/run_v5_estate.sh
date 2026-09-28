#!/usr/bin/env bash
# Build every district's LOD 3 in its LOCAL frame at full precision (v5), to disk only - nothing is published.
#
# Why: the CityEngine glTF exports hold absolute UTM in float32, so every LOD 3 multi-key part, every bld3
# payload and 17 bare tiles are snapped to a 25 cm grid north-south - measured 28 Sep, 100% of decoded
# vertices on the lattice. (The 27 textured bare tiles that went through glTF-Transform are clean and are
# not rebuilt here.) Each district here comes out relative to its own origin, recorded in origin_v5.json.
#
# PyPRT, not CityEngine: headless, no py4j bridge, no CE lock - so it cannot collide with a CityEngine job
# and does not stop when CityEngine does. Parity with the CityEngine builds is exact on alyufrah1 and within
# 2 triangles in 861,455 on arjan.
#
# Gate per district: buildings in the v5 GLB == features in the geojson. A district that fails is reported
# and skipped - it is never left half-written, because export_glb writes the final GLB only after merging.
set -u
cd "$(dirname "$0")/.." || exit 1
mkdir -p logs
# One summary per run. A waiter left over from an earlier run - stopping background tasks here has not
# reliably stopped them - watches the old file and can never be triggered by this one.
SUM="logs/v5_estate_$(date +%Y%m%d_%H%M%S).summary"
say() { echo "$(date +%H:%M:%S)  $*" | tee -a "$SUM"; }

# Smallest first, so results stream early and the three largest land last. The list comes from a small
# Python helper, and Windows Python prints CRLF: mapfile keeps the carriage return, so on 28 Sep every slug
# became "name<CR>" and all 45 districts failed on an invalid path. tr strips it.
list_districts() {
  python -c "
import json, glob, os
rows = [(len(json.load(open(p, encoding='utf-8'))['features']), os.path.basename(os.path.dirname(p)))
        for p in glob.glob('data/ce/*/buildings.geojson')]
for n, s in sorted(rows):
    print(s)
" | tr -d '\r'
}

DISTRICTS=("$@")
if [ ${#DISTRICTS[@]} -eq 0 ]; then
  mapfile -t DISTRICTS < <(list_districts)
fi

say "=== v5 local-frame build: ${#DISTRICTS[@]} districts"
ok=0; bad=()
for d in "${DISTRICTS[@]}"; do
  # Each district's LIVE configuration, from scripts/district_lod_config.json - not a blanket LOD 3. Six
  # districts are two-tier (LOD 2 base, tall buildings at LOD 3) and one is uniform LOD 2; rebuilding any of
  # them at uniform LOD 3 changes the product, not just its precision, and on 28 Sep a building-count gate
  # passed exactly that. Unlisted districts are uniform LOD 3.
  mapfile -t extra < <(python -c "
import json
c = json.load(open('scripts/district_lod_config.json', encoding='utf-8'))['districts'].get('$d', {})
a = ['--lod', str(c.get('lod', 3))]
if c.get('tall_h') is not None:
    a += ['--tall-h', str(c['tall_h']), '--tall-lod', str(c.get('tall_lod', 3))]
print('\n'.join(a))
" | tr -d '\r')
  t=$(date +%s)
  if PYTHONIOENCODING=utf-8 python -u scripts/pyprt_district.py "$d" --glb --ver v5 "${extra[@]}" > "logs/v5_$d.log" 2>&1; then
    line=$(python -c "
import json
s = '$d'
o = json.load(open('data/ce/%s/origin_v5.json' % s, encoding='utf-8'))
g = len(json.load(open('data/ce/%s/buildings.geojson' % s, encoding='utf-8'))['features'])
# Building count alone passed a wrong product on 28 Sep. Also compare triangles with the LIVE CityEngine
# build (glb_v4_verify.json): the same configuration lands within a fraction of a percent. A district whose
# live build predates its current inputs can legitimately differ, so this flags rather than fails.
import os
tri = ''
vp = 'data/ce/%s/glb_v4_verify.json' % s
if os.path.exists(vp):
    ce = json.load(open(vp, encoding='utf-8')).get('triangles')
    if ce:
        r = o['triangles'] / float(ce)
        tri = ' | vs live %d tris: %.4f%s' % (ce, r, '' if abs(r - 1) <= 0.01 else '  <-- DIFFERS >1%')
print('%s buildings %d of %d, %d triangles, LOD %s%s, %d raw part(s)%s' % (
    'OK  ' if o['buildings'] == g else 'MISMATCH', o['buildings'], g, o['triangles'], o['lod'],
    (' tall>=%sm@%s' % (o['tall_h'], o['tall_lod'])) if o.get('tall_h') is not None else '', o.get('raw_parts', 1), tri))
" | tr -d '\r')
    say "  $d  $line  ($(( $(date +%s) - t ))s)"
    case "$line" in OK*) ok=$((ok+1));; *) bad+=("$d");; esac
  else
    say "  $d  FAILED - $(grep -v '\[info\]' "logs/v5_$d.log" | tail -1 | cut -c1-120)"; bad+=("$d")
  fi
done
say "=== v5 done: $ok ok, ${#bad[@]} not: ${bad[*]:-none}"
