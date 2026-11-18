@echo off
rem Double-click to remove the JMeter Control Center service and shortcuts (settings and reports are kept).
rem Options:  -Purge       also delete the Python environment (.venv) so the next install starts clean
rem           -RemoveData  also delete settings, users, history and reports (webapp\instance) - asks first
rem           -Elevated    remove a service task that was created from an Administrator window
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0uninstall_windows.ps1" %*
echo.
pause
