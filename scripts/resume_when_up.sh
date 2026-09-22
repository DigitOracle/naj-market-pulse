#!/usr/bin/env bash
# Wait out a DDA gateway outage, then finish the pull. 22 Sep 2026.
#
# The gateway goes down for maintenance at a time that MOVES: 20 Sep 04:25-06:31, 21 Sep from before 00:10, 22 Sep from ~03:20
# while serving normally at 02:26. So there is no window to schedule around - the only reliable approach is to probe and resume.
# Every page is checkpointed, so an outage costs time and nothing else.
#
# Probes one dataset every 10 minutes. On the first 200 it runs the four big datasets alone at a long cap (each is ~60% done and
# was cut short by an outage, not by the cap), then everything else still outstanding at the ordinary cap.
set -u
cd /c/Dev/naj-market-pulse
export PYTHONIOENCODING=utf-8 DDA_RATE_MAX=40 DDA_RATE_S=2.0
LOG=data/raw_downloads/dda/prod/pull_retry.log
PROBE='import sys; sys.path.insert(0,"scripts"); import dda_api as api
c=api.cfg(); c["DDA_BASE_URL"]=c["DDA_BASE_URL_PROD"]; c["DDA_ENV"]="PROD"
for k in ("APP_ID","SECURITY_APP_IDENTIFIER","CLIENT_ID","CLIENT_SECRET"): c["DDA_"+k]=c["DDA_PROD_"+k]
code,raw,tok=api.auth_get(c, api.data_url(c,"dld","dld_projects-open-api",page=1,pageSize=3), None)
print(code)'

for i in $(seq 1 144); do          # up to 24 hours of probing
  CODE=$(python -c "$PROBE" 2>/dev/null | tail -1)
  echo "$(date '+%m-%d %H:%M') probe $CODE"
  [ "$CODE" = "200" ] && break
  sleep 600
done

if [ "${CODE:-}" != "200" ]; then
  echo "$(date '+%H:%M') gave up waiting - still not serving"
  echo "RESUME WATCH EXIT 1"; exit 1
fi

for DS in rta_average_speed_per_line_buses-open-api det_companyactivity-open-api \
          ded_commerce_registry_activities-open-api rta_bus_ridership-open-api; do
  echo "$(date '+%H:%M') === $DS alone, 240 min cap"
  python -u scripts/dda_pull_all.py --prod --datasets "$DS" --dataset-minutes 240 --max-pages 20000 >> $LOG 2>&1
done

REST=$(python -c "
import json
d = json.load(open('data/raw_downloads/dda/prod/MANIFEST.json', encoding='utf-8'))
bad = [(k.split('/')[1], v.get('rows', 0) or 0) for k, v in d.items()
       if v.get('status') in ('timeout', 'http_408', 'http_0', 'blocked', 'unstable', 'truncated', 'http_400', 'http_404')]
bad.sort(key=lambda x: -x[1])
print(','.join(k for k, _ in bad))")
if [ -n "$REST" ]; then
  echo "$(date '+%H:%M') === remaining $(echo $REST | tr ',' '\n' | wc -l) datasets, 45 min cap"
  python -u scripts/dda_pull_all.py --prod --datasets "$REST" --dataset-minutes 45 --max-pages 20000 >> $LOG 2>&1
fi
python -c "
import json, collections
d = json.load(open('data/raw_downloads/dda/prod/MANIFEST.json', encoding='utf-8'))
print(dict(collections.Counter(v.get('status') for v in d.values())))
print('rows ok {:,}'.format(sum(v.get('rows', 0) or 0 for v in d.values() if v.get('status') == 'ok')))"
echo "RESUME WATCH EXIT 0"
