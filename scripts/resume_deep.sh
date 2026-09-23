#!/usr/bin/env bash
# Finish the pull, giving the deep datasets a cap that fits them. 23 Sep 2026.
#
# resume_when_up.sh named its four big datasets by hand. Three of them have since landed, so re-running that list would spend
# hours re-pulling finished work. The distinction that actually matters is not which dataset it is but why it stopped:
#   timeout  - the cap ran out while rows were still coming, so it needs a LONGER cap, not another 45 minutes
#   anything else (404, 408, blocked) - the gateway refused, so time will not help; one ordinary pass is enough to find out
# Deriving the two lists from status keeps this correct as datasets land, which a hardcoded list does not.
set -u
cd /c/Dev/naj-market-pulse
export PYTHONIOENCODING=utf-8 DDA_RATE_MAX=40 DDA_RATE_S=2.0
LOG=data/raw_downloads/dda/prod/pull_retry.log
PROBE='import sys; sys.path.insert(0,"scripts"); import dda_api as api
c=api.cfg(); c["DDA_BASE_URL"]=c["DDA_BASE_URL_PROD"]; c["DDA_ENV"]="PROD"
for k in ("APP_ID","SECURITY_APP_IDENTIFIER","CLIENT_ID","CLIENT_SECRET"): c["DDA_"+k]=c["DDA_PROD_"+k]
code,raw,tok=api.auth_get(c, api.data_url(c,"dld","dld_projects-open-api",page=1,pageSize=3), None)
print(code)'
LISTS='import json
d = json.load(open("data/raw_downloads/dda/prod/MANIFEST.json", encoding="utf-8"))
pick = lambda f: ",".join(k.split("/")[1] for k, v in sorted(d.items(), key=lambda kv: -(kv[1].get("rows") or 0)) if f(v))
print(pick(lambda v: v.get("status") == "timeout"))
print(pick(lambda v: v.get("status") in ("http_408","http_0","blocked","unstable","truncated","http_400","http_404")))'

for i in $(seq 1 144); do          # up to 24 hours of probing, every 10 min
  CODE=$(python -c "$PROBE" 2>/dev/null | tail -1)
  echo "$(date '+%m-%d %H:%M') probe $CODE"
  [ "$CODE" = "200" ] && break
  sleep 600
done
if [ "${CODE:-}" != "200" ]; then
  echo "$(date '+%H:%M') gave up waiting - still not serving"; echo "RESUME WATCH EXIT 1"; exit 1
fi

mapfile -t L < <(python -c "$LISTS")
DEEP="${L[0]:-}"; REST="${L[1]:-}"

# the deep ones one at a time, so a slow dataset cannot eat another's cap
if [ -n "$DEEP" ]; then
  for DS in $(echo "$DEEP" | tr ',' ' '); do
    echo "$(date '+%H:%M') === $DS alone, 300 min cap (stopped on the cap, not the gateway)"
    python -u scripts/dda_pull_all.py --prod --datasets "$DS" --dataset-minutes 300 --max-pages 40000 >> $LOG 2>&1
  done
fi
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
