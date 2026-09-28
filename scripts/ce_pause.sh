#!/usr/bin/env bash
# Pause the CityEngine lane without killing anything: wait for the current holder to release
# data/ce/.ce_lock, then hold it with a marker that names NO pid.
#
# ce_batch_v2.acquire_lock waits up to 20 minutes on a held lock and then exits "nothing touched", and
# lock_is_stale() treats any lock it cannot prove dead as alive - a lock with no pid can never be proved
# dead. So every generate that follows waits, gives up cleanly, and a running rollout drains without
# touching the scene. Written on 28 Sep, when stopping a background task left the rebuild running.
#
#   bash scripts/ce_pause.sh            take the lock as soon as it is free, and hold it
#   rm data/ce/.ce_lock                 resume (only if it says PAUSED)
cd "$(dirname "$0")/.." || exit 1
LOCK=data/ce/.ce_lock
while [ -f "$LOCK" ]; do
  case "$(cat "$LOCK" 2>/dev/null)" in PAUSED*) echo "already paused: $(cat "$LOCK")"; exit 0;; esac
  sleep 5
done
echo "PAUSED by Kendall's request, no pid - held on purpose $(date -Iseconds)" > "$LOCK"
echo "$(date +%H:%M:%S)  lock taken and held: $(cat "$LOCK")"
