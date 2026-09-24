#!/usr/bin/env bash
# Finish every unfinished PROD dataset. 24 Sep 2026, Kendall: "finish all of them".
#
# Why not resume_deep.sh: it ran the deep list one at a time and gave everything else a 45-minute cap. Deep pages now take
# ~10-15 s each (ordered reads at large offsets), so the 11 partials hold ~19,700 pages - about 60 hours in one lane, and
# 45 minutes finishes none of them. The gateway, not the rate limit, is the bottleneck, so this runs FOUR lanes, each held
# to 15 requests/minute (DDA_RATE_S=4.0). DDA_RATE_MAX is NOT per lane: dda_api counts every process's requests in one
# rolling 60 s window (.rate.json), so 40 is the machine-wide ceiling, a third under the API's 60/minute.
#
# Lanes are balanced by remaining pages (longest-processing-time first), short datasets first within a lane so landings
# arrive early. Every dataset belongs to exactly one lane - two processes on one .part would corrupt it.
# Licence partners stays LAST (peer request 22 Sep: names individuals; the lake already holds the full portal copy).
# bus and metro ridership have no page total and are complete on the lake from the portal, so they go at the very end.
set -u
cd /c/Dev/naj-market-pulse
export PYTHONIOENCODING=utf-8 DDA_RATE_S=4.0 DDA_RATE_MAX=40
LOGDIR=data/raw_downloads/dda/prod
M=$LOGDIR/MANIFEST.json

status () { python -c "
import json,sys; d=json.load(open('$M',encoding='utf-8'))
print(next((v.get('status','') for k,v in d.items() if k.split('/')[1]=='$1'),'missing'))"; }

# one dataset to the end: retry while the stop was the cap, a transport failure or a deep-page 408 (the API's ~30 s page
# timeout - it passes on retry); a 404/400 refusal gets one more try after a pause, then the lane moves on
finish () {
  local ds=$1 lane=$2 n=0 st
  while [ $n -lt 6 ]; do
    n=$((n+1))
    echo "$(date '+%m-%d %H:%M') [$lane] $ds attempt $n"
    python -u scripts/dda_pull_all.py --prod --datasets "$ds" --dataset-minutes 900 --max-pages 60000 >> $LOGDIR/finish_$lane.log 2>&1
    st=$(status "$ds"); echo "$(date '+%m-%d %H:%M') [$lane] $ds -> $st"
    case "$st" in
      ok) return 0 ;;
      timeout|http_0|http_408|disk_low|unstable|truncated) sleep 60 ;;
      http_404|http_400|blocked) [ $n -ge 2 ] && return 1; sleep 600 ;;
      *) [ $n -ge 3 ] && return 1; sleep 120 ;;
    esac
  done
  return 1
}

lane () {       # lane name, then datasets in order
  local name=$1; shift
  for ds in "$@"; do finish "$ds" "$name"; done
  echo "$(date '+%m-%d %H:%M') [$name] LANE DONE"
}

# failures that never started a .part (mostly 404s) - computed now, shared out after the partials
REFUSED=$(python -c "
import json,os; d=json.load(open('$M',encoding='utf-8'))
skip={'ded_license_partners-open-api','rta_bus_ridership-open-api','rta_metro_ridership-open-api'}
out=[]
for k,v in sorted(d.items()):
    e,ds=k.split('/')
    if v.get('status')!='ok' and ds not in skip and not os.path.exists('$LOGDIR/%s__%s.json.part.state'%(e,ds)): out.append(ds)
print(' '.join(out))")
set -- $REFUSED; R=("$@"); H=$(( ${#R[@]} / 2 ))

lane A dm_payment_vouchers_details-open-api ded_license_partners-open-api &
lane B dm_food_health_certificate-open-api rta_marine_ridership-open-api "${R[@]:0:$H}" &
lane C det_ownership-open-api dm_consignments-open-api ded_inspection_report-open-api "${R[@]:$H}" rta_bus_ridership-open-api &
lane D da_flight_information_arrivals-open-api da_flight_information_departures-open-api ded_trade_name-open-api \
       ded_inspection_report_detail-open-api ded_initial_approval_partners-open-api rta_metro_ridership-open-api &
wait
python -c "
import json, collections
d = json.load(open('$M', encoding='utf-8'))
print(dict(collections.Counter(v.get('status') for v in d.values())))"
echo "FINISH ALL EXIT"
