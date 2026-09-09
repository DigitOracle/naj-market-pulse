# Intraday developer-availability sweep (6 Sep 2026): every two hours, parse any PDF the listener captured since the last
# pass, refresh the availability index, recompute launched / sold / on-sheet / remaining, fold it onto the cards and the
# search index. The 06:30 daily refresh still does the full run; this keeps the "left to sell" numbers same-day.
$ErrorActionPreference = "Continue"
$env:PYTHONIOENCODING = "utf-8"
Set-Location C:\Dev\naj-market-pulse
$log = "logs\avail_sweep_$(Get-Date -Format yyyyMMdd).log"
"=== sweep $(Get-Date -Format s)" | Out-File $log -Append -Encoding utf8
& python scripts\listener_health.py 2>&1 | Out-File $log -Append -Encoding utf8
$before = (Get-ChildItem data\avail\*.json | Measure-Object -Property LastWriteTime -Maximum).Maximum
& python scripts\extract_avail.py --scan 2>&1 | Tee-Object -Variable scanOut | Out-File $log -Append -Encoding utf8
# a developer-group PDF that parses to zero units is a FAILURE (a new sheet format), never a quiet success
$zero = ($scanOut | Select-String -Pattern '^extracted: .* 0 units$')
if ($zero) { "!! PARSE FAILURE - $($zero.Count) developer PDF(s) yielded 0 units (new format?):" | Out-File $log -Append -Encoding utf8; $zero | ForEach-Object { "   " + $_.Line } | Out-File $log -Append -Encoding utf8 }
$after = (Get-ChildItem data\avail\*.json | Measure-Object -Property LastWriteTime -Maximum).Maximum
if ($after -gt $before) {
  "new sheet(s) parsed - rebuilding" | Out-File $log -Append -Encoding utf8
  foreach ($s in @("scripts\build_avail_index.py", "scripts\remaining_inventory.py", "scripts\build_unit_mix.py", "scripts\build_search_index.py")) {
    "--- $s" | Out-File $log -Append -Encoding utf8
    & python $s 2>&1 | Out-File $log -Append -Encoding utf8
  }
} else { "no new sheets" | Out-File $log -Append -Encoding utf8 }
# every run: the twin maturity audit (names, bindings, grades per district) goes to the Worker so the rail badges stay current
"--- twin audit" | Out-File $log -Append -Encoding utf8
& python scripts\twin_audit.py 2>&1 | Out-File $log -Append -Encoding utf8
& python -c "import json,sys; sys.path.insert(0,'scripts'); from build_avail_index import env_token, push; d=json.load(open('data/board/twin_audit.json',encoding='utf-8')); print('twin_audit ->', push('twin_audit', {'generated': d['generated'], 'districts': d['districts']}, env_token('INGEST_TOKEN')))" 2>&1 | Out-File $log -Append -Encoding utf8
# acknowledge to Naj what was parsed and where it landed (approved by Kendall 08 Sep 2026 - sends after every sweep)
& python scripts\sweep_ack.py --send 2>&1 | Out-File $log -Append -Encoding utf8
"done $(Get-Date -Format s)" | Out-File $log -Append -Encoding utf8
