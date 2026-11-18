#Requires -Version 5.1
<#
.SYNOPSIS
  Installs (or repairs / updates) the JMeter Control Center on Windows for the current user.
.DESCRIPTION
  Easiest way: double-click install_windows.cmd (same folder). It runs this script with
  "-ExecutionPolicy Bypass" for this run only, so the "running scripts is disabled on this system" error
  does not appear and no system setting is changed.

  * Checks the prerequisites (Python 3.9+, Git, AWS CLI v2, Session Manager plugin, OpenSSH client) and offers
    to install the missing ones with winget (Windows may ask for confirmation for some of them)
  * Python environment (.venv) and your first Control Center login
  * Your SSH key for copying scripts to the servers (created if you have none)
  * Background service: a Task Scheduler task that starts the app at logon (hidden, restarts after a crash)
  * "JMeter Control Center" shortcuts (Start menu + Desktop) with the icon
  Run it from a NORMAL PowerShell window (not "Run as administrator"): the app, the service and your keys belong
  to your Windows user.
.PARAMETER NoService
  Only prepare the environment and shortcuts; start the app manually with the shortcut.
.PARAMETER Yes
  Answer "yes" to the prerequisite installation questions.
.EXAMPLE
  install_windows.cmd
.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File webapp\tools\service\install_windows.ps1
#>
param([switch]$NoService, [switch]$Yes, [switch]$AllowAdmin)
$ErrorActionPreference = 'Stop'
$WebApp = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$Port = 8090
$TaskPath = '\JMeterControlCenter\'
$TaskName = 'JMeter Control Center'
Set-Location $WebApp

function Say($m) { Write-Host "==> $m" -ForegroundColor Cyan }
function Test-Cmd($Name) { [bool](Get-Command $Name -ErrorAction SilentlyContinue) }
function Test-Port { try { $c = New-Object Net.Sockets.TcpClient('127.0.0.1', $Port); $c.Close(); $true } catch { $false } }
function Ask($q) { if ($Yes) { return $true }; $a = Read-Host "$q [Y/n]"; return ($a -eq '' -or $a -match '^[YySs]') }
function Refresh-Path {
  $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [Environment]::GetEnvironmentVariable('Path', 'User')
}

# ---- 0. never as Administrator ----------------------------------------------------------------
$id = [Security.Principal.WindowsIdentity]::GetCurrent()
$isAdmin = (New-Object Security.Principal.WindowsPrincipal($id)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if ($isAdmin -and -not $AllowAdmin) {
  Write-Host ''
  Write-Host 'This window runs as Administrator. Do not install the Control Center this way:' -ForegroundColor Yellow
  Write-Host 'the service, the files and your SSH key must belong to YOUR user (same issue as "sudo" on macOS).'
  Write-Host 'Close this window and double-click webapp\tools\service\install_windows.cmd (or open PowerShell'
  Write-Host 'normally, without "Run as administrator").'
  exit 1
}
if (-not (Test-Path (Join-Path $WebApp 'run.py'))) { throw "run.py not found under $WebApp" }

# ---- 1. prerequisites ------------------------------------------------------------------------------
function Find-Python {
  # The Microsoft Store placeholder (...\WindowsApps\python.exe) is not Python: skip it.
  $cands = @()
  if (Test-Cmd 'py') { $cands += , @('py', '-3') }
  Get-Command python, python3 -All -ErrorAction SilentlyContinue | Where-Object { $_.Source -notmatch '\\WindowsApps\\' } |
    ForEach-Object { $cands += , @($_.Source) }
  Get-ChildItem "$env:LOCALAPPDATA\Programs\Python\Python3*\python.exe", "$env:ProgramFiles\Python3*\python.exe" -ErrorAction SilentlyContinue |
    Sort-Object FullName -Descending | ForEach-Object { $cands += , @($_.FullName) }
  foreach ($c in $cands) {
    try {
      $exe = $c[0]; $pre = @($c | Select-Object -Skip 1)
      $ok = & $exe @pre -c 'import sys; print(1 if sys.version_info >= (3, 9) else 0)' 2>$null
      if ($LASTEXITCODE -eq 0 -and "$ok".Trim() -eq '1') { return , $c }
    } catch { }
  }
  return $null
}

$Py = Find-Python
$missing = @()
if (-not $Py) { $missing += 'Python 3.12|Python.Python.3.12|--scope user' }
if (-not (Test-Cmd 'git')) { $missing += 'Git|Git.Git|' }
if (-not (Test-Cmd 'aws')) { $missing += 'AWS CLI v2|Amazon.AWSCLI|' }
if (-not (Test-Cmd 'session-manager-plugin') -and -not (Test-Path "$env:ProgramFiles\Amazon\SessionManagerPlugin\bin\session-manager-plugin.exe")) {
  $missing += 'AWS Session Manager plugin|Amazon.SessionManagerPlugin|'
}
if ($missing.Count) {
  Write-Host ''
  Write-Host 'Missing prerequisites:' -ForegroundColor Yellow
  $missing | ForEach-Object { Write-Host ('  - ' + $_.Split('|')[0]) }
  if (-not (Test-Cmd 'winget')) {
    Write-Host 'winget is not available: install them manually (python.org - tick "Add python.exe to PATH";'
    Write-Host 'git-scm.com; aws.amazon.com/cli; Session Manager plugin for Windows) and run this again.'
    exit 1
  }
  if (Ask 'Install them now with winget?') {
    foreach ($m in $missing) {
      $name, $wid, $extra = $m.Split('|')
      Say "Installing $name"
      $wargs = @('install', '-e', '--id', $wid, '--accept-package-agreements', '--accept-source-agreements')
      if ($extra) { $wargs += $extra.Split(' ') }
      & winget @wargs
      if ($LASTEXITCODE -and $LASTEXITCODE -ne -1978335189) { Write-Warning "winget could not install $name (exit $LASTEXITCODE)" }
    }
    Refresh-Path
    $Py = Find-Python
  }
}
if (-not $Py) {
  Write-Host 'Python 3.9+ is still not available. Install it from python.org (tick "Add python.exe to PATH"),' -ForegroundColor Red
  Write-Host 'or turn off the "python.exe" App execution alias (Settings > Apps > Advanced app settings), then run this again.'
  exit 1
}
if (-not (Test-Cmd 'ssh')) {
  Write-Warning 'OpenSSH client not found: Settings > System > Optional features > Add a feature > "OpenSSH Client".'
}
foreach ($c in 'git', 'aws') { if (-not (Test-Cmd $c)) { Write-Warning "$c is still not on PATH: open a new PowerShell window after installing it." } }

# ---- 2. Python environment and first login ----------------------------------------------------------
$VenvPy = Join-Path $WebApp '.venv\Scripts\python.exe'
$VenvPyw = Join-Path $WebApp '.venv\Scripts\pythonw.exe'
if ((Test-Path $VenvPy) -and -not (& $VenvPy -c 'print(1)' 2>$null)) {
  Say 'The Python environment is broken (Python was moved or reinstalled): recreating it'
  Remove-Item -Recurse -Force (Join-Path $WebApp '.venv')
}
if (-not (Test-Path $VenvPy)) {
  Say 'Creating the Python environment'
  $pre = @($Py | Select-Object -Skip 1)
  & $Py[0] @pre -m venv .venv
  if ($LASTEXITCODE) { throw 'venv creation failed' }
}
Say 'Installing / updating the Python packages'
& $VenvPy -m pip install -q --disable-pip-version-check --upgrade pip
& $VenvPy -m pip install -q --disable-pip-version-check -r requirements.txt
if ($LASTEXITCODE) { throw 'pip install failed (proxy? try again on the office network or VPN)' }

& $VenvPy -c 'from srapp import users; import sys; sys.exit(0 if users.count() else 1)'
if ($LASTEXITCODE) {
  Say 'Create your Control Center login (local to this computer)'
  $u = Read-Host 'Username'
  & $VenvPy manage_users.py add $u --role admin
  if ($LASTEXITCODE) { throw 'User not created' }
}

# ---- 3. SSH key used to copy the scripts to the servers -------------------------------------------------
& $VenvPy -c 'from srapp import push_sync; import sys; sys.exit(0 if push_sync.key_path() else 1)' 2>$null
if ($LASTEXITCODE) {
  if (Ask 'No SSH key found. Create one now (used only to copy scripts to the load generators)?') {
    & $VenvPy -m srapp.push_sync --make-key
  }
}

# ---- 4. shortcuts --------------------------------------------------------------------------------------
$Ico = Join-Path $WebApp 'tools\launcher\icon.ico'
$Bat = Join-Path $WebApp 'tools\launcher\jmeter-control-center.bat'
$Wsh = New-Object -ComObject WScript.Shell
foreach ($dir in [Environment]::GetFolderPath('Programs'), [Environment]::GetFolderPath('Desktop')) {
  $lnk = $Wsh.CreateShortcut((Join-Path $dir 'JMeter Control Center.lnk'))
  $lnk.TargetPath = $Bat
  $lnk.WorkingDirectory = $WebApp
  $lnk.IconLocation = "$Ico,0"
  $lnk.Description = 'Open the JMeter Control Center'
  $lnk.WindowStyle = 7
  $lnk.Save()
}
Say 'Shortcuts created (Start menu and Desktop)'

if ($NoService) { Say 'Done. Open it with the "JMeter Control Center" shortcut.'; exit 0 }

# ---- 5. background service (Task Scheduler, at logon, as you) -----------------------------------------
$existing = Get-ScheduledTask -TaskPath $TaskPath -TaskName $TaskName -ErrorAction SilentlyContinue
if ((Test-Port) -and -not $existing) {
  throw "Port $Port is in use (the app is open in a console window?). Close it and run this again."
}
$Me = $id.Name
$Action = New-ScheduledTaskAction -Execute $VenvPyw -Argument 'run.py --service windows-task' -WorkingDirectory $WebApp
$Trigger = New-ScheduledTaskTrigger -AtLogOn -User $Me
$Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
  -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero) `
  -MultipleInstances IgnoreNew
$Principal = New-ScheduledTaskPrincipal -UserId $Me -LogonType Interactive -RunLevel Limited
try {
  Register-ScheduledTask -TaskPath $TaskPath -TaskName $TaskName -Action $Action -Trigger $Trigger `
    -Settings $Settings -Principal $Principal -Description 'JMeter Control Center (scheduled performance runs)' -Force | Out-Null
} catch {
  Write-Host 'Could not (re)register the service task. If it was created before from an Administrator window,' -ForegroundColor Red
  Write-Host 'remove it once with: uninstall_windows.cmd -Elevated   and then run install_windows.cmd again.'
  throw
}
Stop-ScheduledTask -TaskPath $TaskPath -TaskName $TaskName -ErrorAction SilentlyContinue
Get-CimInstance Win32_Process -Filter "Name = 'pythonw.exe'" -ErrorAction SilentlyContinue |
  Where-Object { $_.CommandLine -like '*run.py --service*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Start-ScheduledTask -TaskPath $TaskPath -TaskName $TaskName
Say "Service installed: Task Scheduler > $TaskPath$TaskName (log: webapp\instance\service.log)"

for ($i = 0; $i -lt 40 -and -not (Test-Port); $i++) { Start-Sleep -Milliseconds 500 }
if (Test-Port) { Start-Process "http://localhost:$Port" } else { Write-Warning 'The app did not open the port yet; see webapp\instance\service.log' }

Write-Host ''
Write-Host 'Next: Settings > AWS (profile, region, instance ids) > Test connection; Settings > E-mail (App Password).'
Write-Host 'Tip: Settings > System > Power: "When plugged in, put my device to sleep after" = Never for night schedules.'
