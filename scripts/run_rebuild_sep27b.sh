#!/usr/bin/env bash
# Continuation of the 27 Sep rebuild after the first run stopped between JVC's split and its push.
#
# jumeirahvillagecircle is already GENERATED and gated - GATE 0/1/3 passed, GATE 2 routed it to
# per-building payloads (18.34 MB gzipped against a 5 MB cap) and glb_split_buildings wrote 132 of
# them. Only the publish is missing, so this pushes what is on disk rather than spending another
# eight minutes regenerating a district that is already correct.
#
# Every pipeline here uses grep --line-buffered. The first run's progress was invisible because grep
# block-buffers when its stdout is a file, so the log showed three lines while the pass was minutes
# into real work. That is a reporting fault, not a build fault, but it is the reason a dead run
# looked identical to a working one.
set -u
cd "$(dirname "$0")/.." || exit 1
mkdir -p logs

SUM="logs/rebuild_sep27b.summary"
say() { echo "$(date +%H:%M:%S)  $*" | tee -a "$SUM"; }
G() { grep --line-buffered -E "$1"; }

say "=== continuation starting"

# --- 0. finish jumeirahvillagecircle: publish the 132 per-building payloads already on disk -----
say "--- [0/4] jumeirahvillagecircle per-building publish"
python -u scripts/push_buildings_gz.py jumeirahvillagecircle 2>&1 | tail -3 | tee -a "$SUM"

# --- 1. jumeirahvillagetriangle, LOD 2 base with LOD 3 above 13 m ------------------------------
say "--- [1/4] jumeirahvillagetriangle (LOD 2 base, LOD 3 >= 13 m)"
if python -u scripts/ce_batch_v2.py --v4 jumeirahvillagetriangle --lod 2 --tall-h 13 --tall-lod 3 \
     > logs/rebuild_sep27_jvt.log 2>&1; then
  if python -u - <<'PY' 2>&1 | tee -a "$SUM"
import sys; sys.argv=['x']; sys.path.insert(0,'scripts')
import najma_build_all as M
ok, lines = M.gate('jumeirahvillagetriangle','v4','logs/rebuild_sep27_jvt.log',0)
for l in lines: print('  ', l)
sys.exit(0 if ok else 1)
PY
  then
    python -u scripts/push_sky_gz.py jumeirahvillagetriangle --ver v4 --live 2>&1 | tail -2 | tee -a "$SUM"
  else
    say "  jumeirahvillagetriangle GATED - not pushed"
  fi
else
  say "  jumeirahvillagetriangle generate FAILED - see logs/rebuild_sep27_jvt.log"
fi

# --- 2. the remaining twelve through the gated rollout -----------------------------------------
say "--- [2/4] the remaining twelve (rollout sorts cheapest-first by storeys)"
python -u scripts/najma_lod3_rollout.py \
    samaaljadaf sobhaheartland businessbay dubaimarina palmjumeirah arjan \
    bukadra liwan1 siliconoasis madinatalmataar dubaihills althanyahfifth \
  2>&1 | tee -a logs/rebuild_sep27_rest.log \
  | G "^=== \[|GATE [0-9]|HERO |TILE |REJECTED|FAILED|IN THE TILE|PER-BUILDING|generate FAILED" \
  | tee -a "$SUM"

# --- 3. multi-key tiles, then reconcile every district against its geojson ----------------------
say "--- [3/4] multi-key tile refresh"
for d in jumeirahvillagecircle jumeirahvillagetriangle samaaljadaf sobhaheartland businessbay \
         dubaimarina palmjumeirah arjan bukadra liwan1 siliconoasis madinatalmataar \
         dubaihills althanyahfifth; do
  python -u scripts/glb_tile_parts.py "$d" --ver v4 2>&1 | tail -1
  if [ -f "data/ce/_glb/parts/$d/manifest.json" ]; then
    python -u scripts/push_tile_parts.py "$d" 2>&1 | tail -1
  fi
done | tee -a "$SUM"

say "--- [4/4] reconciliation"
python -u - <<'PY' 2>&1 | tee -a "$SUM"
import json, os, sys
sys.path.insert(0, 'scripts')
from glb_merge_per_building import read_glb
S = ['jumeirahvillagecircle','jumeirahvillagetriangle','samaaljadaf','sobhaheartland','businessbay',
     'dubaimarina','palmjumeirah','arjan','bukadra','liwan1','siliconoasis','madinatalmataar',
     'dubaihills','althanyahfifth']
bad = 0
for s in S:
    n = len(json.load(open('data/ce/%s/buildings.geojson' % s, encoding='utf-8'))['features'])
    p = 'data/ce/_glb/sky_%s_v4_0.glb' % s
    b = len([x for x in read_glb(p)[0]['nodes'] if 'mesh' in x]) if os.path.exists(p) else 0
    bad += 0 if b == n else 1
    print('  %-26s geojson %6d  build %6d  %s' % (s, n, b, 'OK' if b == n else 'MISMATCH'))
print('  districts still mismatched:', bad)
PY

say "=== continuation done"
