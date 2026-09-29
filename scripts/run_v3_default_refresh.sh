#!/usr/bin/env bash
# Rebuild the textured default-view tiles (bare sky_<slug>, the layer a person sees first) - Kendall, 29 Sep 2026.
# The live ones were built 22 Sep and predate the reviewed heights and Ellington appends; on 28 Sep the default
# view drew b1492 OAKLEY SQUARE (JVC) at 116.8 m against a reviewed 20.0 m. The JVC pilot came out at 20.0 m.
#
# Per district: ce_batch_v2 --v3 (CityEngine, holds .ce_lock) -> glb_pack_v3.mjs -> gates. Disk only: the
# push is Rings' (python scripts/push_sky_gz.py <slugs>), so nothing here changes what the site serves.
# Gates: buildings == geojson features and shapes failed 0 (from glb_v3_verify.json), packed file actually
# smaller than the merged one (the pack ran), gzip <= 5 MB (the store cap).
#
# District list = bare keys that are TEXTURED today (logs/live_bare_tiles.json, measured 29 Sep from the
# worker), so a district the rollout already replaced with an untextured v4 tile is not silently changed back.
set -u
cd "$(dirname "$0")/.." || exit 1
mkdir -p logs
SUM="logs/v3_refresh_$(date +%Y%m%d_%H%M%S).summary"
say() { echo "$(date +%H:%M:%S)  $*" | tee -a "$SUM"; }
DISTRICTS=("$@")
if [ ${#DISTRICTS[@]} -eq 0 ]; then
  mapfile -t DISTRICTS < <(python -c "import json; print('\n'.join(json.load(open('logs/live_bare_tiles.json'))['textured']))" | tr -d '\r')
fi
say "=== v3 default-view refresh: ${#DISTRICTS[@]} districts"
ok=(); bad=()
for d in "${DISTRICTS[@]}"; do
  t=$(date +%s)
  if ! PYTHONIOENCODING=utf-8 python -u scripts/ce_batch_v2.py --v3 "$d" > "logs/v3r_$d.log" 2>&1; then
    say "  $d  BUILD FAILED - $(tail -1 "logs/v3r_$d.log" | cut -c1-120)"; bad+=("$d"); continue
  fi
  node scripts/glb_pack_v3.mjs "data/ce/_glb/sky_${d}_v3_0.glb" >> "logs/v3r_$d.log" 2>&1
  line=$(python - "$d" <<'EOF' | tr -d '\r'
import gzip, json, os, sys
s = sys.argv[1]; g = "data/ce/_glb/sky_%s_v3_0" % s
v = json.load(open("data/ce/%s/glb_v3_verify.json" % s, encoding="utf-8")) if os.path.exists("data/ce/%s/glb_v3_verify.json" % s) else {}
n = len(json.load(open("data/ce/%s/buildings.geojson" % s, encoding="utf-8"))["features"])
packed, merged = os.path.getsize(g + ".glb"), os.path.getsize(g + ".merged.glb")
gz = len(gzip.compress(open(g + ".glb", "rb").read(), 9)) / 1048576.0
b = v.get("buildings"); fail = v.get("shapes_failed", 0)
okk = b == n and not fail and packed < merged and gz <= 5.0
print("%s buildings %s of %d, failed %s, packed %.2f MB (merged %.2f), gz %.2f MB" % (
    "OK  " if okk else "FAIL", b, n, fail, packed / 1048576.0, merged / 1048576.0, gz))
EOF
)
  say "  $d  $line  ($(( $(date +%s) - t ))s)"
  case "$line" in OK*) ok+=("$d");; *) bad+=("$d");; esac
done
say "=== v3 done: ${#ok[@]} ok, ${#bad[@]} not: ${bad[*]:-none}"
say "PUSH (Rings): python scripts/push_sky_gz.py ${ok[*]:-}"
