@echo off
rem ---------------------------------------------------------------------------
rem JMeter Control Center launcher (Windows)
rem  - service installed and running: just opens http://localhost:8090
rem  - otherwise: first-time setup if needed, then runs the app in this window
rem    (close the window to stop it; tests already running on the Master keep running)
rem ---------------------------------------------------------------------------
setlocal
cd /d "%~dp0..\.."
powershell -NoProfile -Command "try{(New-Object Net.Sockets.TcpClient('127.0.0.1',8090)).Close();exit 0}catch{exit 1}"
if %errorlevel%==0 (
  start "" http://localhost:8090
  exit /b 0
)
if not exist ".venv\Scripts\python.exe" (
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0..\service\install_windows.ps1" -NoService || (pause & exit /b 1)
)
title JMeter Control Center - keep this window open
start "" /b powershell -NoProfile -Command "for($i=0;$i -lt 60;$i++){try{(New-Object Net.Sockets.TcpClient('127.0.0.1',8090)).Close();Start-Process 'http://localhost:8090';break}catch{Start-Sleep -Milliseconds 500}}"
".venv\Scripts\python.exe" run.py --mode aws
if errorlevel 1 pause
