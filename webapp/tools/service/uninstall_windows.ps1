#Requires -Version 5.1
<#
.SYNOPSIS
  Removes the JMeter Control Center from this Windows user: background service (Task Scheduler), wake timers,
  running app, shortcuts. Settings, users, run history and reports in webapp\instance are KEPT unless -RemoveData.
.PARAMETER Purge
  Also delete the Python environment (webapp\.venv): the next install_windows.cmd recreates it from scratch.
  Use it when a reinstall fails (Python moved/updated, environment created from an Administrator window...).
.PARAMETER RemoveData
  Also delete webapp\instance (settings, encrypted tokens, users, history, downloaded reports). Asks first.
.PARAMETER Elevated
  Re-run this script as Administrator (UAC prompt) to remove a task that was registered from an elevated window.
.EXAMPLE
  uninstall_windows.cmd -Purge
#>
param([switch]$Purge, [switch]$RemoveData, [switch]$Elevated)
$ErrorActionPreference = 'Continue'
$WebApp = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$TaskPath = '\JMeterControlCenter\'

if ($Elevated) {
  $a = "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`""
  if ($Purge) { $a += ' -Purge' }
  Start-Process powershell -Verb RunAs -ArgumentList $a -Wait
  exit
}

# 1. service tasks (and wake-timer tasks created by the app)
$failed = $false
Get-ScheduledTask -TaskPath $TaskPath -ErrorAction SilentlyContinue | ForEach-Object {
  Stop-ScheduledTask -TaskPath $TaskPath -TaskName $_.TaskName -ErrorAction SilentlyContinue
  try {
    Unregister-ScheduledTask -TaskPath $TaskPath -TaskName $_.TaskName -Confirm:$false -ErrorAction Stop
    Write-Host "Removed task $($_.TaskName)"
  } catch { $failed = $true; Write-Warning "Could not remove task $($_.TaskName): $($_.Exception.Message)" }
}
if ($failed) { Write-Host 'Some tasks belong to an Administrator session: run  uninstall_windows.cmd -Elevated' -ForegroundColor Yellow }

# 2. running app (service or console window)
Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
  Where-Object { $_.Name -in 'python.exe', 'pythonw.exe' -and $_.CommandLine -like '*run.py*' -and $_.CommandLine -like "*$WebApp*" -or
                 ($_.Name -eq 'pythonw.exe' -and $_.CommandLine -like '*run.py --service*') } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue; Write-Host "Stopped app process $($_.ProcessId)" }

# 3. shortcuts
foreach ($dir in [Environment]::GetFolderPath('Programs'), [Environment]::GetFolderPath('Desktop')) {
  Remove-Item (Join-Path $dir 'JMeter Control Center.lnk') -ErrorAction SilentlyContinue
}
Write-Host 'Service and shortcuts removed.'

# 4. optional clean-up
if ($Purge) {
  Remove-Item -Recurse -Force (Join-Path $WebApp '.venv') -ErrorAction SilentlyContinue
  Get-ChildItem $WebApp -Recurse -Directory -Filter '__pycache__' -ErrorAction SilentlyContinue | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
  Write-Host 'Python environment deleted (.venv). install_windows.cmd recreates it.'
}
if ($RemoveData) {
  $inst = Join-Path $WebApp 'instance'
  $ans = Read-Host "Delete ALL settings, users, tokens, history and reports in $inst ? Type DELETE to confirm"
  if ($ans -ceq 'DELETE') { Remove-Item -Recurse -Force $inst; Write-Host 'Data deleted.' } else { Write-Host 'Data kept.' }
}
Write-Host ''
Write-Host 'To install again: double-click webapp\tools\service\install_windows.cmd (NOT as Administrator).'
