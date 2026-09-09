$ErrorActionPreference="Continue"; $env:PYTHONIOENCODING="utf-8"
Set-Location C:\Dev\naj-market-pulse
$log = "logs\amenities_$(Get-Date -Format yyyyMMdd_HHmm).log"
"start $(Get-Date -Format s)" | Out-File $log -Encoding utf8
& python scripts\amenities.py 2>&1 | Out-File $log -Append -Encoding utf8
"done $(Get-Date -Format s)" | Out-File $log -Append -Encoding utf8
