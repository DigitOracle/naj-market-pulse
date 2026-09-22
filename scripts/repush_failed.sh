#!/usr/bin/env bash
# Re-push districts whose re-mass produced a GLB but whose push failed (DNS/gateway - 7 failures on 22 Sep).
# The generate is the expensive half and it succeeded; only the upload was lost. Probe rather than schedule: the
# gateway comes back on its own timetable, so this retries every 10 minutes until every district is stored.
cd /c/Dev/naj-market-pulse
LOG=logs/repush_failed.log
: > "$LOG"
left=("$@")
while [ ${#left[@]} -gt 0 ]; do
  nxt=()
  for d in "${left[@]}"; do
    out=$(python scripts/push_sky_gz.py "$d" 2>&1 | tail -1)
    echo "$(date -u +%H:%M) $d :: $out" >> "$LOG"
    case "$out" in *"stored=True"*) ;; *) nxt+=("$d");; esac
  done
  left=("${nxt[@]}")
  [ ${#left[@]} -eq 0 ] && break
  echo "$(date -u +%H:%M) still waiting on: ${left[*]}" >> "$LOG"
  sleep 600
done
echo "=== repush complete: every district stored" >> "$LOG"
