#!/usr/bin/env bash
# Pack every district facade that has not been packed since it was generated, then push it under sky_<slug>.
# A district is packed when its .pack.json is no older than its .glb - re-packing a packed file would compress it twice.
cd /c/Dev/naj-market-pulse
for d in "$@"; do
  f="data/ce/_glb/sky_${d}_v3_0.glb"
  [ -f "$f" ] || { echo "$d: no facade"; continue; }
  echo "=== $d"
  node scripts/glb_pack_v3.mjs "$f" 2>&1 | tail -1
  python scripts/push_sky_gz.py "$d" 2>&1 | tail -1
done
echo "=== pack+push finished"
