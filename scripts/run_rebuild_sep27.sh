#!/usr/bin/env bash
# The 27 Sep rebuild: 14 districts whose built tile no longer matches their geojson.
#
# Ten are short of buildings because the Sobha session appended Ellington register placeholders to
# a contiguous tail; four have the right count but carry reviewed height overrides the tile predates.
# Both classes are fixed by the same thing - one ce_batch_v2 generate, the four gates, then whichever
# publish route the district's own measured size picks.
#
# Order is deliberate: jumeirahvillagecircle first because it is the only district whose defect is
# visible on screen (THE PORTMAN renders as a 6.2 m stub and is 60.8 m), then the small mixed ones,
# then the height-only rebuilds, and dubaihills and althanyahfifth last because they are the two
# expensive districts and a failure there costs the least at the end.
#
# jumeirahvillagetriangle is not in the rollout: it keeps an LOD 2 base with LOD 3 above 13 m, so it
# is built by hand and gated by hand rather than being given the rollout's LOD 3 default.
#
# Every district's scene shape count is re-read at the gate. Nothing here trusts a count captured
# earlier - a stale precondition that happens to agree is exactly how the Marina publish went wrong.
set -u
cd "$(dirname "$0")/.." || exit 1
mkdir -p logs

TS=$(date +%Y%m%d_%H%M%S)
SUM="logs/rebuild_sep27_${TS}.summary"
say() { echo "$(date +%H:%M:%S)  $*" | tee -a "$SUM"; }

say "=== rebuild starting: 14 districts"

# --- 1. jumeirahvillagecircle, on its own, because it is the one to get right first -------------
say "--- [1/4] jumeirahvillagecircle"
python scripts/najma_lod3_rollout.py jumeirahvillagecircle 2>&1 | tee -a logs/rebuild_sep27_jvc.log \
  | grep -E "GATE|HERO |TILE |REJECTED|FAILED|generate FAILED" | tee -a "$SUM"

# --- 2. jumeirahvillagetriangle, LOD 2 base with LOD 3 above 13 m ------------------------------
say "--- [2/4] jumeirahvillagetriangle (LOD 2 base, LOD 3 >= 13 m)"
if python scripts/ce_batch_v2.py --v4 jumeirahvillagetriangle --lod 2 --tall-h 13 --tall-lod 3 \
     > logs/rebuild_sep27_jvt.log 2>&1; then
  python - <<'PY' 2>&1 | tee -a "$SUM"
import sys; sys.argv=['x']; sys.path.insert(0,'scripts')
import najma_build_all as M
ok, lines = M.gate('jumeirahvillagetriangle','v4','logs/rebuild_sep27_jvt.log',0)
for l in lines: print('  ', l)
sys.exit(0 if ok else 1)
PY
  if [ "${PIPESTATUS[0]}" = "0" ]; then
    python scripts/push_sky_gz.py jumeirahvillagetriangle --ver v4 --live 2>&1 | tail -2 | tee -a "$SUM"
  else
    say "  jumeirahvillagetriangle GATED - not pushed"
  fi
else
  say "  jumeirahvillagetriangle generate FAILED - see logs/rebuild_sep27_jvt.log"
fi

# --- 3. the remaining twelve through the gated rollout -----------------------------------------
# The rollout sorts cheapest-first by storey count on its own, which puts dubaihills and
# althanyahfifth last without my having to order them.
say "--- [3/4] the remaining twelve"
python scripts/najma_lod3_rollout.py \
    samaaljadaf sobhaheartland businessbay dubaimarina palmjumeirah arjan \
    bukadra liwan1 siliconoasis madinatalmataar dubaihills althanyahfifth \
  2>&1 | tee -a logs/rebuild_sep27_rest.log \
  | grep -E "^=== \[|GATE 1|GATE 2|HERO |TILE |REJECTED|FAILED|IN THE TILE|PER-BUILDING" | tee -a "$SUM"

# --- 4. refresh the multi-key tiles, then reconcile every district against its geojson ----------
say "--- [4/4] multi-key tile refresh, then reconciliation"
for d in jumeirahvillagecircle jumeirahvillagetriangle samaaljadaf sobhaheartland businessbay \
         dubaimarina palmjumeirah arjan bukadra liwan1 siliconoasis madinatalmataar \
         dubaihills althanyahfifth; do
  python scripts/glb_tile_parts.py "$d" --ver v4 2>&1 | tail -1
  if [ -f "data/ce/_glb/parts/$d/manifest.json" ]; then
    python scripts/push_tile_parts.py "$d" 2>&1 | tail -1
  fi
done | tee -a "$SUM"

python - <<'PY' 2>&1 | tee -a "$SUM"
import json, os, sys
sys.path.insert(0, 'scripts')
from glb_merge_per_building import read_glb
S = ['jumeirahvillagecircle','jumeirahvillagetriangle','samaaljadaf','sobhaheartland','businessbay',
     'dubaimarina','palmjumeirah','arjan','bukadra','liwan1','siliconoasis','madinatalmataar',
     'dubaihills','althanyahfifth']
bad = 0
print('  %-26s %8s %8s  %s' % ('district', 'geojson', 'build', ''))
for s in S:
    n = len(json.load(open('data/ce/%s/buildings.geojson' % s, encoding='utf-8'))['features'])
    p = 'data/ce/_glb/sky_%s_v4_0.glb' % s
    b = len([x for x in read_glb(p)[0]['nodes'] if 'mesh' in x]) if os.path.exists(p) else 0
    bad += 0 if b == n else 1
    print('  %-26s %8d %8d  %s' % (s, n, b, 'OK' if b == n else 'MISMATCH'))
print('  districts still mismatched:', bad)
PY

say "=== rebuild done"
