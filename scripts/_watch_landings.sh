#!/usr/bin/env bash
# Exit when the pull either LANDS a dataset or BREAKS, so the session is woken for events and not for progress.
# Kendall, 22 Sep 2026: "only report when something lands or breaks".
#   lands  - a dataset reaches ok (the manifest's ok count rises)
#   breaks - the gateway stops serving, the network drops, or the whole pass exits
set -u
cd /c/Dev/naj-market-pulse
LOG=data/raw_downloads/dda/prod/pull_retry.log
WATCH="C:/Users/kwils/AppData/Local/Temp/claude/C--Users-kwils-AppData-Roaming-Claude-scratch-workspaces-98193c80-1321-4f8d-b8fd-21f6a1ac8b75-458bf548-05b1-475b-b8c2-afc946a8d6bc-scratch-2026-09-18-eeb573/fd021bd2-361f-4aa7-ba47-753c96305d50/tasks/bogmvorxp.output"
count_ok () { python -c "
import json
d = json.load(open('data/raw_downloads/dda/prod/MANIFEST.json', encoding='utf-8'))
print(sum(1 for v in d.values() if v.get('status') == 'ok'))"; }

BASE=$(count_ok)
echo "$(date '+%H:%M') watching from ok=$BASE"

for i in $(seq 1 480); do          # up to 8 hours, checked every minute
  sleep 60
  NOW=$(count_ok)
  if [ "$NOW" != "$BASE" ]; then
    echo "$(date '+%H:%M') LANDED: ok $BASE -> $NOW"
    grep "ok rows=" $LOG | tail -1
    echo "EVENT landed"; exit 0
  fi
  if grep -q "RESUME WATCH EXIT" "$WATCH" 2>/dev/null; then
    echo "$(date '+%H:%M') the pass finished"; echo "EVENT finished"; exit 0
  fi
  # BROKEN means the work stopped, not that a probe failed. 22 Sep 2026: the probe competed with the running pull for the
  # shared 60 req/min budget, lost, returned a transport error, and this watcher declared an outage while the pull was fine.
  # The checkpoint files are the honest signal and cost no API budget to read: if nothing has been written for 20 minutes
  # while a pull is supposed to be running, something is actually wrong.
  if [ $((i % 20)) -eq 0 ]; then
    FRESH=$(find data/raw_downloads/dda/prod -name "*.part" -newermt "-20 minutes" 2>/dev/null | wc -l)
    if [ "$FRESH" -eq 0 ]; then
      echo "$(date '+%H:%M') BROKE: no checkpoint written in 20 minutes"; echo "EVENT broke"; exit 0
    fi
  fi
done
echo "$(date '+%H:%M') eight hours, no event"; echo "EVENT quiet"
