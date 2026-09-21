#!/usr/bin/env bash
# Every district still without a textured facade, in the 2025-26 launch-register order Kendall set
# (most units launched first), then the rest. CityEngine stays open; the .ce_lock serialises the runs.
cd /c/Dev/naj-market-pulse
ORDER="madinatalmataar bukadra wadialsafa5 dubaiinvestmentparksecond majan dubaihills arjan \
dubaisportscity siliconoasis damachills alhebiahfifth dubaiproductioncity alkhairanfirst meydanone \
dubaistudiocity dubaisciencepark dubaiinvestmentparkfirst alsatwa madinathind4 jabalaliindustrialsecond \
goldensymphony alyelayiss1 alyelayiss2 alyufrah1 dubaiindustrialcity"
for d in $ORDER; do
  [ -f "data/ce/_glb/sky_${d}_v3_0.glb" ] && { echo "== $d already has a facade"; continue; }
  [ -f "data/ce/_glb/sky_${d}_0.glb" ] || { echo "== $d has no massing, skipped"; continue; }
  echo "=== facades: $d"
  python scripts/ce_batch_v2.py --v3 "$d" 2>&1 | tail -4
done
echo "=== facade queue finished"
