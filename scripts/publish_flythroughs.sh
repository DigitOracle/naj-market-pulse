#!/usr/bin/env bash
# publish_flythroughs.sh -- render (if needed) and publish district fly-throughs so the map rail's camera icons light up.
#   bash scripts/publish_flythroughs.sh <slug> [<slug> ...]      (run from anywhere; renders happen in the open Unreal editor)
# For each district: Movie Render Queue fly-through (kit da_render_district_flythroughs.py, chained, 15 s), then a 720p H.264
# transcode + poster, then push_unreal_clip.py <slug> district -> KV vid_unreal_<slug>_fly + img_videos item (kind unreal, scope district).
set -u
GOV="C:/Users/kwils/OneDrive/Desktop/DigitAlchemy_31MAY2026/Ecosystem/20_governance/scripts"
KIT="C:/Users/kwils/OneDrive/Desktop/DigitAlchemy_31MAY2026/Ecosystem/30_kits/unreal"
REPO="C:/Dev/naj-market-pulse"; OUT="$REPO/data/video"; mkdir -p "$OUT"
NAMES="$REPO/data/ce/_city/INDEX.json"
slugs="$*"; [ -z "$slugs" ] && { echo "usage: publish_flythroughs.sh <slug> ..."; exit 1; }
# 1. render the whole list in one chained editor session (skips districts whose ledger entry is ok unless 'force' is in the list)
( cd "$GOV" && python da_remote_exec.py "\"$KIT/scripts/da_render_district_flythroughs.py\" $slugs 15" 2>&1 | grep -ao "DA_FLY.*" | head -3 | cut -c1-160 )
for s in $slugs; do
  [ "$s" = "force" ] && continue
  D="$KIT/results/fly_$s"; t=0
  until [ -f "$D/render.json" ] && grep -q '"ok": true' "$D/render.json" || [ $t -ge 1800 ]; do sleep 15; t=$((t+15)); done
  if ! grep -q '"ok": true' "$D/render.json" 2>/dev/null; then echo "$s: render not ok after ${t}s"; continue; fi
  # newest mp4 (native MRQ encoder) or assemble from PNGs
  src="$D/frame_.mp4"; [ -f "$src" ] || ffmpeg -y -v error -framerate 24 -i "$D/frame_%04d.png" -c:v libx264 -pix_fmt yuv420p "$D/frame_.mp4"
  ffmpeg -y -v error -i "$src" -vf scale=1280:720 -c:v libx264 -preset slow -crf 25 -pix_fmt yuv420p -movflags +faststart -an "$OUT/unreal_${s}_fly.mp4"
  ffmpeg -y -v error -ss 4 -i "$OUT/unreal_${s}_fly.mp4" -frames:v 1 -q:v 4 "$OUT/unreal_${s}_fly.jpg"
  name=$(python -c "import json,sys; d=json.load(open(sys.argv[1])); print(d.get(sys.argv[2],{}).get('name') or sys.argv[2])" "$NAMES" "$s" 2>/dev/null || echo "$s")
  ( cd "$REPO" && PYTHONIOENCODING=utf-8 python scripts/push_unreal_clip.py "$s" district "$name" "$OUT/unreal_${s}_fly.mp4" "$OUT/unreal_${s}_fly.jpg" "15 s fly-through" 2>&1 | tail -3 )
  echo "$s: published $(du -k "$OUT/unreal_${s}_fly.mp4" | cut -f1) KB"
done
