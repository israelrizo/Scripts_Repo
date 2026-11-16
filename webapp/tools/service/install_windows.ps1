#Requires -Version 5.1
<#
.SYNOPSIS
  Installs the JMeter Control Center on Windows for the current user.
.DESCRIPTION
  * Python environment (.venv) and your first Control Center login
  * Background service: a Task Scheduler task that starts the app at logon (hidden, restarts after a
    crash, keeps running on battery) so scheduled runs fire without opening anything.
    The app itself keeps Windows awake while a run is close and registers wake timers for each slot.
  * "JMeter Control Center" shortcuts (Start menu + Desktop) with the icon
  No administrator rights are needed.
.PARAMETER NoService
  Only prepare the environment and shortcuts; start the app manually with jmeter-control-center.bat.
.EXAMPLE
  powershell -ExecutionPolicy Bypass -File webapp\tools\service\install_windows.ps1
#>
param([switch]$NoService)
$ErrorActionPreference = 'Stop'
$WebApp = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$Port = 8090
$TaskPath = '\JMeterControlCenter\'
$TaskName = 'JMeter Control Center'
Set-Location $WebApp

function Test-Cmd($Name) { [bool](Get-Command $Name -ErrorAction SilentlyContinue) }
function Test-Port { try { $c = New-Object Net.Sockets.TcpClient('127.0.0.1', $Port); $c.Close(); $true } catch { $false } }

if (-not (Test-Path (Join-Path $WebApp 'run.py'))) { throw "run.py not found under $WebApp" }
if (Test-Cmd 'py') { $PyExe = 'py'; $PyArgs = @('-3') }
elseif (Test-Cmd 'python') { $PyExe = 'python'; $PyArgs = @() }
else { throw 'Python 3.9+ not found. Install it from python.org (tick "Add python.exe to PATH") and run this again.' }
foreach ($c in 'git', 'aws', 'session-manager-plugin') {
  if (-not (Test-Cmd $c)) { Write-Warning "$c not found on PATH (needed to control the load generators)" }
}

$VenvPy = Join-Path $WebApp '.venv\Scripts\python.exe'
$VenvPyw = Join-Path $WebApp '.venv\Scripts\pythonw.exe'
if (-not (Test-Path $VenvPy)) {
  Write-Host '==> Creating the Python environment'
  & $PyExe @PyArgs -m venv .venv
  if ($LASTEXITCODE) { throw 'venv creation failed' }
}
& $VenvPy -m pip install -q --upgrade pip
& $VenvPy -m pip install -q -r requirements.txt
if ($LASTEXITCODE) { throw 'pip install failed' }

& $VenvPy -c 'from srapp import users; import sys; sys.exit(0 if users.count() else 1)'
if ($LASTEXITCODE) {
  Write-Host '==> Create your Control Center login'
  $u = Read-Host 'Username'
  & $VenvPy manage_users.py add $u --role admin
  if ($LASTEXITCODE) { throw 'User not created' }
}

# ---- shortcuts (open the browser on the running app) -------------------------------------------
$Ico = Join-Path $WebApp 'tools\launcher\icon.ico'
$Bat = Join-Path $WebApp 'tools\launcher\jmeter-control-center.bat'
$Wsh = New-Object -ComObject WScript.Shell
$Targets = @([Environment]::GetFolderPath('Programs'), [Environment]::GetFolderPath('Desktop'))
foreach ($dir in $Targets) {
  $lnk = $Wsh.CreateShortcut((Join-Path $dir 'JMeter Control Center.lnk'))
  $lnk.TargetPath = $Bat
  $lnk.WorkingDirectory = $WebApp
  $lnk.IconLocation = "$Ico,0"
  $lnk.Description = 'Open the JMeter Control Center'
  $lnk.WindowStyle = 7   # minimized: the .bat only opens the browser when the service is running
  $lnk.Save()
}
Write-Host '==> Shortcuts created (Start menu and Desktop)'

if ($NoService) {
  Write-Host '==> Done. Start it with the "JMeter Control Center" shortcut.'
  exit 0
}

# ---- background service: Task Scheduler task at logon -----------------------------------------
if ((Test-Port) -and -not (Get-ScheduledTask -TaskPath $TaskPath -TaskName $TaskName -ErrorAction SilentlyContinue)) {
  throw "Port $Port is in use (the app is open in a console window?). Close it and run this again."
}
$Me = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$Action = New-ScheduledTaskAction -Execute $VenvPyw -Argument 'run.py --service windows-task' -WorkingDirectory $WebApp
$Trigger = New-ScheduledTaskTrigger -AtLogOn -User $Me
$Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
  -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero) `
  -MultipleInstances IgnoreNew
$Principal = New-ScheduledTaskPrincipal -UserId $Me -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskPath $TaskPath -TaskName $TaskName -Action $Action -Trigger $Trigger `
  -Settings $Settings -Principal $Principal -Description 'JMeter Control Center (scheduled performance runs)' -Force | Out-Null
Stop-ScheduledTask -TaskPath $TaskPath -TaskName $TaskName -ErrorAction SilentlyContinue
Start-ScheduledTask -TaskPath $TaskPath -TaskName $TaskName
Write-Host "==> Service installed: Task Scheduler > $TaskPath$TaskName (log: webapp\instance\service.log)"

for ($i = 0; $i -lt 40 -and -not (Test-Port); $i++) { Start-Sleep -Milliseconds 500 }
if (Test-Port) { Start-Process "http://localhost:$Port" } else { Write-Warning 'The app did not open the port yet; see webapp\instance\service.log' }

Write-Host ''
Write-Host 'Tip: Settings > System > Power > "When plugged in, put my device to sleep after" = Never (or allow wake'
Write-Host '     timers in the power plan) so night schedules are not missed.'
