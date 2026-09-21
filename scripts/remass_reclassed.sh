#!/usr/bin/env bash
# Re-mass, pack and push the districts whose facade classes changed (facade_reclass.py, 22 Sep 2026).
# The class is baked at GENERATE time - najma_v3.cga reads it as an object attribute - so a repack would
# keep the old material. Order is by how many buildings moved, so the biggest visual gains land first.
cd /c/Dev/naj-market-pulse
for d in "$@"; do
  echo "=== re-mass $d"
  python scripts/ce_batch_v2.py --v3 "$d" 2>&1 | tail -3
  f="data/ce/_glb/sky_${d}_v3_0.glb"
  [ -f "$f" ] || { echo "$d: NO GLB after generate - skipping pack"; continue; }
  node scripts/glb_pack_v3.mjs "$f" 2>&1 | tail -1
  python scripts/push_sky_gz.py "$d" 2>&1 | tail -1
done
echo "=== re-mass queue finished"
