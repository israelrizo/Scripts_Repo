@echo off
rem Double-click to install, repair or update the JMeter Control Center for YOUR Windows user.
rem Runs install_windows.ps1 with "ExecutionPolicy Bypass" for this run only (no system setting is changed).
rem Do NOT use "Run as administrator".
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install_windows.ps1" %*
echo.
pause
