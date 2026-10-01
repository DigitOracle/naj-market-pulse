#!/usr/bin/env bash
# v278 release = v277 (simple Brief, no register estimate, Blocks buttons, new-style PDF from the building page)
#              + v277.1 (START is the Brief alone)
#              + v278 (map stays in blocks, twin blocks-first, detail on demand)
# Also re-publishes the 45 districts' blocks with the small-footprint height cap (no more 90 m needles).
# Run in PowerShell:  & "C:\Program Files\Git\bin\bash.exe" "<this file>"
set -eo pipefail
export MSYS_NO_PATHCONV=1
SHA=94b792a
BASE=6737368
W="C:/Dev/azimuth-worker-dewa"
REL="C:/Dev/_rel278"
DW="C:/Dev/_deploy_v278"
REPO="C:/Dev/naj-market-pulse"
HM=$(python -c "import datetime;n=datetime.datetime.utcnow()+datetime.timedelta(hours=4);print(n.strftime('%H%M'))")
if [ "$HM" -ge 0555 ] && [ "$HM" -le 0635 ]; then echo "STOP: $HM Dubai - Naj's morning feed window. Run after 06:35."; exit 1; fi
echo "Dubai $HM - ok"

echo "== 1  re-publish blocks (45 districts, capped heights)"
if [ "${SKIP_BLOCKS:-0}" = "1" ]; then echo "   skipped (SKIP_BLOCKS=1)"; else
for d in $(ls "$REPO/data/ce" | grep -v '^_' | grep -v '\.json$'); do
  if [ -f "$REPO/data/ce/$d/blocks.json" ]; then ( cd "$REPO" && python scripts/build_blocks.py "$d" --push | tail -1 ); fi
done
fi

HM=$(python -c "import datetime;n=datetime.datetime.utcnow()+datetime.timedelta(hours=4);print(n.strftime('%H%M'))")
if [ "$HM" -ge 0545 ] && [ "$HM" -le 0635 ]; then echo "STOP before deploy: $HM Dubai - too close to Naj's morning feed. Blocks are published; re-run after 06:35 to deploy."; exit 1; fi
echo "== 2  pre-flight"
cd "$W"; git fetch -q origin
T=$(git rev-parse --short origin/dewa-screens)
[ "$T" = "$BASE" ] || [ "$T" = "$SHA" ] || { echo "STOP: origin/dewa-screens is $T, expected v276 ($BASE)"; exit 1; }
git -C "$REL" merge-base --is-ancestor "$BASE" "$SHA" || { echo "STOP: release is not built on v276"; exit 1; }
for P in picjob_ gmp_; do
  N=$(npx wrangler kv key list --env azimuth2 --namespace-id 2cdf36a27f834b5f9c726294d36770fb --prefix $P | python -c "import sys,json;print(len(json.load(sys.stdin)))")
  [ "$N" = "0" ] || { echo "STOP: $N $P keys in flight - wait a few minutes and re-run"; exit 1; }
done
[ "$T" = "$SHA" ] || git -C "$REL" push origin "$SHA:dewa-screens"
[ -d "$DW" ] || git worktree add -q --detach "$DW" "$SHA"
[ -d "$DW/node_modules" ] || cmd /c "mklink /J C:\\Dev\\_deploy_v278\\node_modules C:\\Dev\\azimuth-worker-dewa\\node_modules"
[ -d "$DW/node_modules/wrangler" ] || { echo "STOP: node_modules link missing"; exit 1; }

echo "== 3  upload $SHA"
cd "$DW"
npx wrangler versions upload --env azimuth2 --tag "$SHA" | tee /tmp/v278_upload.txt
VID=$(grep -o 'Worker Version ID: [0-9a-f-]*' /tmp/v278_upload.txt | awk '{print $4}')
[ -n "$VID" ] || { echo "STOP: no version id - nothing deployed"; exit 1; }
echo "== 4  deploy $VID at 100%"
npx wrangler versions deploy "$VID" --percentage 100 --env azimuth2 --yes
cd "$W" && cmd /c "rmdir C:\\Dev\\_deploy_v278\\node_modules" && git worktree remove "$DW"
echo "== LIVE: v278 ($SHA)"
