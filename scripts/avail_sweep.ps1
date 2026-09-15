# Intraday developer-availability sweep (6 Sep 2026): every two hours, parse any PDF the listener captured since the last
# pass, refresh the availability index, recompute launched / sold / on-sheet / remaining, fold it onto the cards and the
# search index. The 06:30 daily refresh still does the full run; this keeps the "left to sell" numbers same-day.
#
# 13 Sep 2026 (Data Spine Phase 1): runs through scripts\refresh_runner.py (chain "sweep"), same steps as before, plus the
# availability volume check (a sheet whose units collapse is held until a second sheet agrees). Every step is recorded in
# data\runs\; a developer PDF that parses to zero units is still a failure, never a quiet success. The acknowledgement to
# Naj (sweep_ack.py --send, approved by Kendall 08 Sep 2026) still sends only when something new was parsed.
# Log output goes to logs\avail_sweep_<yyyymmdd>.log.
$env:PYTHONIOENCODING = "utf-8"
Set-Location C:\Dev\naj-market-pulse
python scripts\refresh_runner.py sweep
exit $LASTEXITCODE
