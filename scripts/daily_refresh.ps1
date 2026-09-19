# Najma daily refresh - runs the full pipeline on this PC (the DLD gateway blocks cloud IPs, so this cannot run in GitHub
# Actions; the Windows scheduled task Najma_Daily_Refresh drives it at 05:00 - moved from 06:30 on 19 Sep 2026).
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
#
# 19 Sep 2026 (Kendall): the task now starts at 05:00, not 06:30, so fresh data is in Azimuth BEFORE the 06:00 morning feed
# (a good run takes about 25 minutes; the 06:30 start meant the feed always read the day before's data). The task wakes the
# laptop, and on 19 Sep the network was not up yet: every download failed with "getaddrinfo failed" and nothing was built.
# So wait for the network first - up to 10 minutes, checking every 20 s - before starting the chain.
$env:PYTHONIOENCODING = "utf-8"
Set-Location "C:\Dev\naj-market-pulse"
$deadline = (Get-Date).AddMinutes(10)
while ((Get-Date) -lt $deadline) {
    try { [System.Net.Dns]::GetHostAddresses("azimuth-2.digitalchemy.workers.dev") | Out-Null; break } catch { Start-Sleep -Seconds 20 }
}
python scripts\refresh_runner.py daily
exit $LASTEXITCODE
