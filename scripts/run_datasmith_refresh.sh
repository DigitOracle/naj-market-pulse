#!/usr/bin/env bash
# Re-export Unreal LOD 3 (Datasmith) for every district whose export is older than its inputs.
#
# Stale means either the geojson changed after the export (Ellington appends, position nudges) or the
# district carries a reviewed height override dated after it - height_overrides.json was written on
# 25 Sep and every full-district export predates it. An mtime check alone misses the second kind, which
# is why arjan and palmjumeirah are listed even though their geojson has not moved.
#
# Datasmith export is fast (arjan 67 s, businessbay 178 s, dubaihills 210 s end to end) against the glTF
# web export (businessbay 38 min), so this goes first: it feeds L_Dubai directly.
#
# Every export uses the same city offset as the LOD 1 base in L_Dubai, so the two land on the same spot.
# It is passed explicitly for every district - ce_lod3_datasmith refuses to invent one.
set -u
cd "$(dirname "$0")/.." || exit 1
mkdir -p logs
OFFSET="-328289,0,2784598"
SUM="logs/datasmith_refresh.summary"
say() { echo "$(date +%H:%M:%S)  $*" | tee -a "$SUM"; }

DISTRICTS=("$@")
if [ ${#DISTRICTS[@]} -eq 0 ]; then
  DISTRICTS=(arjan bukadra jumeirahvillagetriangle jumeirahvillagecircle motorcity samaaljadaf liwan1 \
             sobhaheartland siliconoasis palmjumeirah jltnorth businessbay dubaimarina jabalalifirst \
             wadialsafa3 madinatalmataar althanyahfifth dubaihills)
fi

say "=== Datasmith LOD 3 refresh: ${#DISTRICTS[@]} districts: ${DISTRICTS[*]}"
ok=0; bad=()
for d in "${DISTRICTS[@]}"; do
  # ALWAYS explicit. The exporter reuses an offset only from <slug>_georef.json - the FLAT export's file -
  # and this script first checked <slug>_lod3_georef.json instead, so every district that had one got no
  # --offset and was (rightly) refused: six failed in a second each on 28 Sep. It is one constant for the
  # whole city, and stating it is the point.
  args=("$d" --rule najma_v4.cga --lod 3 --offset "$OFFSET")
  t=$(date +%s)
  if python -u scripts/ce_lod3_datasmith.py "${args[@]}" > "logs/datasmith_${d}.log" 2>&1; then
    st="data/ce/_datasmith/${d}_lod3_stats.json"
    line=$(python - "$st" "$d" <<'PY'
import json, sys
d = json.load(open(sys.argv[1], encoding="utf-8"))
g = len(json.load(open("data/ce/%s/buildings.geojson" % sys.argv[2], encoding="utf-8"))["features"])
el = d.get("export_log", {}) or {}
n = el.get("ok", d.get("shape_count"))
print("%s shapes %s of %d geojson, export ok %s failed %s  %s" % (
    "OK  " if (n == g and not el.get("failed")) else "MISMATCH", n, g, el.get("ok"), el.get("failed"),
    "gen %.0fs exp %.0fs" % (d.get("generate_s", 0), d.get("export_s", 0))))
PY
)
    say "  $d  $line  ($(( $(date +%s) - t ))s)"
    case "$line" in OK*) ok=$((ok+1));; *) bad+=("$d");; esac
  else
    say "  $d  FAILED - see logs/datasmith_${d}.log"; bad+=("$d")
  fi
done
say "=== done: $ok ok, ${#bad[@]} not: ${bad[*]:-none}"
