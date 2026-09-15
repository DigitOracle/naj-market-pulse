# Nightly copy of Azimuth's edge-only state to disk (13 Sep 2026, Data Spine Phase 1) - scheduled task Najma_Edge_Backup, 02:30.
# Both key-value namespaces (meeting-capture and azimuth-2) are read through the Cloudflare API, credentials and rebuildable
# pushed assets skipped, into data\edge_backup\<date>\ (14 days kept). Runs through scripts\refresh_runner.py (chain
# "edge-nightly"); a failure reaches Kendall as one WhatsApp line.
$env:PYTHONIOENCODING = "utf-8"
Set-Location "C:\Dev\naj-market-pulse"
python scripts\refresh_runner.py edge-nightly
exit $LASTEXITCODE
