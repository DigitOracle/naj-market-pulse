# restore_tasks.ps1 - register Najma's scheduled tasks on the always-on host (Data Spine Phase 6, 13 Sep 2026).
#
# The XML files beside this script were exported from the laptop on 13 Sep 2026. There every task runs only while
# kwils is signed in (logon type Interactive), which an unattended machine never is. Here each task is registered to run
# whether or not anyone is signed in (S4U: no stored password; internet access works, Windows file shares do not), with
# the repo root and the Python path rewritten when they differ from the laptop's. Registering S4U tasks needs an
# elevated prompt. A task whose script is missing on this machine is reported and skipped, never registered broken.
#
#   powershell -ExecutionPolicy Bypass -File restore_tasks.ps1 -WhatIf          # what would be registered, and what is missing
#   powershell -ExecutionPolicy Bypass -File restore_tasks.ps1                  # register all (elevated)
#   powershell -ExecutionPolicy Bypass -File restore_tasks.ps1 -Only Najma_Avail_Sweep,DA_Azimuth_Listener_Naj
param(
  [string]$DevRoot = "C:\Dev",
  [string]$User = "$env:USERDOMAIN\$env:USERNAME",
  [string[]]$Only = @(),
  [switch]$WhatIf
)
$ErrorActionPreference = "Stop"
$Only = @($Only | ForEach-Object { $_ -split "," } | ForEach-Object { $_.Trim() } | Where-Object { $_ })   # -File passes "a,b" as one string
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$laptopPython = "C:\Users\kwils\AppData\Local\Programs\Python\Python312\python.exe"
$python = (Get-Command python -ErrorAction SilentlyContinue).Source

foreach ($f in Get-ChildItem $here -Filter *.xml | Sort-Object Name) {
  if ($Only.Count -and $Only -notcontains $f.BaseName) { continue }
  $xml = Get-Content $f.FullName -Raw -Encoding Unicode
  $xml = $xml.Replace("C:\Dev\", $DevRoot.TrimEnd("\") + "\")
  if ($python) { $xml = $xml.Replace($laptopPython, $python) }
  $xml = $xml -replace '<LogonType>InteractiveToken</LogonType>', '<LogonType>S4U</LogonType>'
  $xml = $xml -replace '<UserId>[^<]*</UserId>', ('<UserId>' + [Security.SecurityElement]::Escape($User) + '</UserId>')
  $xml = $xml -replace '<DisallowStartIfOnBatteries>true</', '<DisallowStartIfOnBatteries>false</'
  $xml = $xml -replace '<StopIfGoingOnBatteries>true</', '<StopIfGoingOnBatteries>false</'

  # every absolute script or program the task names must exist here; relative ones resolve against WorkingDirectory
  $wd = [regex]::Match($xml, '<WorkingDirectory>([^<]+)</WorkingDirectory>').Groups[1].Value
  $paths = @([regex]::Matches($xml, '[A-Za-z]:\\[^"<]+?\.(ps1|py|exe)') | ForEach-Object { $_.Value })
  if ($wd) { $paths += @([regex]::Matches($xml, '(?<=[\s>])scripts\\[^"<\s]+\.py') | ForEach-Object { [IO.Path]::Combine($wd, $_.Value) }) }
  $missing = @($paths | Where-Object { -not (Test-Path $_) } | Select-Object -Unique)
  $doc = [xml]$xml                                                   # a rewrite that broke the XML stops here
  if ($doc.Task.Principals.Principal.LogonType -ne "S4U") { throw "$($f.BaseName): logon type not rewritten" }

  if ($WhatIf) {
    $note = if ($missing.Count) { "  MISSING: " + ($missing -join ", ") } else { "" }
    "{0,-26} would register as {1}, runs with nobody signed in{2}" -f $f.BaseName, $User, $note
    continue
  }
  if ($missing.Count) { "{0,-26} NOT registered - missing: {1}" -f $f.BaseName, ($missing -join ", "); continue }
  Register-ScheduledTask -TaskName $f.BaseName -Xml $xml -Force | Out-Null
  "{0,-26} registered" -f $f.BaseName
}
