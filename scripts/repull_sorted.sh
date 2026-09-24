#!/usr/bin/env bash
# Re-pull every FINISHED dataset whose rows the pull dropped as repeats. 25 Sep 2026.
#
# Until 419348a the pull dropped every row identical to one already seen, and the loader ran DISTINCT on top. For a read
# sorted to a known last page that deleted genuine records of registers with no key (containers: 985,946 kept of 5,222,714
# served, the portal's exact count). For an unordered read the repeats were the gateway serving rows twice as its order
# drifted - each one standing in for a row never served. Either way the fix is the same: read again, sorted by every column
# from page 1 (--order-by full), keeping every row (repeats_kept). The list is data/raw_downloads/dda/prod/repull_list.json,
# built from the manifest: status ok, raw_rows > rows, not already repeats_kept, not being pulled by finish_all.sh.
# --force starts each afresh; a failed re-pull keeps the last good file (dda_pull_all's refresh rule).
# Two lanes, smallest first so landings arrive early; the machine-wide cap (DDA_RATE_MAX=40) still bounds the total rate.
set -u
cd /c/Dev/naj-market-pulse
export PYTHONIOENCODING=utf-8 DDA_RATE_S=4.0 DDA_RATE_MAX=40
D=data/raw_downloads/dda/prod
mapfile -t L < <(python -c "
import json; l = json.load(open('$D/repull_list.json'))
big = ['dm_container_of_the_consignments-open-api', 'customs_air_manifest_destination-open-api',
       'ded_initial_approval_activities-open-api', 'rta_average_speed_per_line_buses-open-api']
small = [x for x in l if x not in big]
print(' '.join(small[0::2] + [b for b in big[2:4] if b in l]))
print(' '.join(small[1::2] + [b for b in big[0:2][::-1] if b in l]))")

lane () {
  local name=$1; shift
  for ds in $@; do
    echo "$(date '+%m-%d %H:%M') [$name] $ds"
    python -u scripts/dda_pull_all.py --prod --datasets "$ds" --force --order-by full --dataset-minutes 900 --max-pages 60000 >> $D/repull_$name.log 2>&1
    echo "$(date '+%m-%d %H:%M') [$name] $ds -> $(python -c "
import json; d = json.load(open('$D/MANIFEST.json', encoding='utf-8'))
v = next(v for k, v in d.items() if k.split('/')[1] == '$ds')
print(v.get('status'), v.get('rows'), 'of', v.get('raw_rows'), 'kept' if v.get('repeats_kept') else 'NOT kept')")"
  done
  echo "$(date '+%m-%d %H:%M') [$name] LANE DONE"
}
lane R1 ${L[0]} &
lane R2 ${L[1]} &
wait
echo "REPULL EXIT"
