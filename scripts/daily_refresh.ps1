# Najma daily refresh - runs the full pipeline on this PC (the DLD gateway blocks cloud IPs, so this cannot run in GitHub
# Actions; the Windows scheduled task Najma_Daily_Refresh drives it at 06:30).
#
# 13 Sep 2026 (Data Spine Phase 1): the chain now runs through scripts\refresh_runner.py (chain "daily"). Same order as
# before - fetch DLD, build the pulse, ingest it, heat map, listener check, availability, DNA chain, cards, building meta,
# truth store - with four changes:
#   1. every step's exit code is recorded in data\runs\<date>\daily_<time>.json (run_ledger.py);
#   2. a step whose inputs failed is skipped instead of publishing from stale files;
#   3. cityLife is rebuilt into pulse.json before the ingest, and the golden gate + graph export and the governed-API
#      contract now run after the truth store;
#   4. when anything fails, is held or needs an eye, Kendall gets ONE WhatsApp line (notify_owner.py) - never Naj.
# The previous script (git history before 13 Sep 2026) ignored every exit code except the listener check.
# Log output still goes to daily_refresh.log.
$env:PYTHONIOENCODING = "utf-8"
Set-Location "C:\Dev\naj-market-pulse"
python scripts\refresh_runner.py daily
exit $LASTEXITCODE
