# paid Places geocoding across all 40 districts (Kendall approved 6 Sep), then identity + cards + audit
$ErrorActionPreference = "Continue"; $env:PYTHONIOENCODING = "utf-8"
Set-Location C:\Dev\naj-market-pulse
$log = "logs\refresh_geocode_$(Get-Date -Format yyyyMMdd_HHmm).log"
"start $(Get-Date -Format s)" | Out-File $log -Encoding utf8
& python scripts\bind_dld_buildings.py 2>&1 | Out-File $log -Append -Encoding utf8
& python scripts\bind_register_buildings.py 2>&1 | Out-File $log -Append -Encoding utf8
foreach ($s in @("scripts\resolve_identity.py","scripts\apply_identity.py","scripts\build_unit_mix.py","scripts\build_search_index.py","scripts\twin_audit.py")) {
  "=== $s $(Get-Date -Format HH:mm:ss)" | Out-File $log -Append -Encoding utf8
  & python $s 2>&1 | Out-File $log -Append -Encoding utf8
}
& python -c "import json,sys; sys.path.insert(0,'scripts'); from build_avail_index import env_token, push; d=json.load(open('data/board/twin_audit.json',encoding='utf-8')); print('twin_audit ->', push('twin_audit', {'generated': d['generated'], 'districts': d['districts']}, env_token('INGEST_TOKEN')))" 2>&1 | Out-File $log -Append -Encoding utf8
"done $(Get-Date -Format s)" | Out-File $log -Append -Encoding utf8
