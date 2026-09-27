#!/usr/bin/env bash
# The twelve districts still to build, as ONE pipeline.
#
# jumeirahvillagecircle and jumeirahvillagetriangle are done and verified on the wire, so they are not
# here. What is here is the set whose tile still holds fewer buildings than its geojson, or whose
# reviewed height overrides the tile predates.
#
# SINGLE INSTANCE, deliberately. On 27 Sep I read a process listing whose filter did not match
# ce_batch_v2.py, concluded the first pass was dead, and started a second one; the two raced for the
# CityEngine lock and twelve districts recorded generate failures in a tenth of a minute each without
# ever running. The guard below is cheap and would have stopped that, and it does not depend on my
# reading a process list correctly - it checks for its own marker and for the CE lock.
set -u
cd "$(dirname "$0")/.." || exit 1
mkdir -p logs

MARK="logs/.rebuild_twelve.running"
if [ -f "$MARK" ]; then
  echo "REFUSING to start: $MARK exists, written by pid $(cat "$MARK" 2>/dev/null)."
  echo "Another run of this script is already going, or one died without clearing it."
  echo "If you are certain nothing is running, delete the file and try again."
  exit 1
fi
echo "$$ $(date -Iseconds)" > "$MARK"
trap 'rm -f "$MARK"' EXIT INT TERM

if [ -f data/ce/.ce_lock ]; then
  echo "note: CE lock currently held by '$(cat data/ce/.ce_lock)' - ce_batch_v2 will wait for it"
fi

SUM="logs/rebuild_twelve.summary"
say() { echo "$(date +%H:%M:%S)  $*" | tee -a "$SUM"; }

say "=== twelve districts, one pipeline, pid $$"

# The rollout sorts cheapest-first by storey count, so dubaihills and althanyahfifth land last on
# their own. Each district: generate, four gates, then whichever publish route its measured gzipped
# size picks - single tile under the 5 MB cap, per-building payloads over it.
python -u scripts/najma_lod3_rollout.py \
    samaaljadaf sobhaheartland businessbay dubaimarina palmjumeirah arjan \
    bukadra liwan1 siliconoasis madinatalmataar dubaihills althanyahfifth \
  2>&1 | tee -a logs/rebuild_twelve.log \
  | grep --line-buffered -E "^=== \[|GATE [0-9]|HERO |TILE |REJECTED|FAILED|IN THE TILE|PER-BUILDING|generate FAILED|REFUSING" \
  | tee -a "$SUM"

# Multi-key tiles for whatever now needs them, then the only check that matters: does the published
# district hold as many buildings as its geojson says it should.
say "--- multi-key tile refresh"
for d in samaaljadaf sobhaheartland businessbay dubaimarina palmjumeirah arjan \
         bukadra liwan1 siliconoasis madinatalmataar dubaihills althanyahfifth; do
  python -u scripts/glb_tile_parts.py "$d" --ver v4 2>&1 | tail -1
  if [ -f "data/ce/_glb/parts/$d/manifest.json" ]; then
    python -u scripts/push_tile_parts.py "$d" 2>&1 | tail -1
  fi
done | tee -a "$SUM"

say "--- reconciliation, all fourteen"
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

say "=== twelve done"
