# Najma government-data week (13 Sep 2026, Data Spine Phase 1) - scheduled task Najma_Gov_Weekly, Fridays 03:00.
# Governed API pull (staging until production credentials arrive, ticket 876938549) -> load -> feed contract (full duplicate
# scan) -> realness gate (held datasets leave v_gov_usable) -> portal manifest contract. Runs through
# scripts\refresh_runner.py (chain "gov-weekly"); every step lands in data\runs\ and Kendall gets one line if anything is held.
# The governed API answers UAE addresses only, so this must run from a machine in the UAE.
$env:PYTHONIOENCODING = "utf-8"
Set-Location "C:\Dev\naj-market-pulse"
python scripts\refresh_runner.py gov-weekly
exit $LASTEXITCODE
