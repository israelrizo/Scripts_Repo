#Requires -Version 5.1
<# Removes the JMeter Control Center background service, its wake timers and shortcuts. Data in webapp\instance is kept. #>
$ErrorActionPreference = 'Continue'
$TaskPath = '\JMeterControlCenter\'
Get-ScheduledTask -TaskPath $TaskPath -ErrorAction SilentlyContinue | ForEach-Object {
  Stop-ScheduledTask -TaskPath $TaskPath -TaskName $_.TaskName -ErrorAction SilentlyContinue
  Unregister-ScheduledTask -TaskPath $TaskPath -TaskName $_.TaskName -Confirm:$false
  Write-Host "Removed task $($_.TaskName)"
}
Get-CimInstance Win32_Process -Filter "Name = 'pythonw.exe'" -ErrorAction SilentlyContinue |
  Where-Object { $_.CommandLine -like '*run.py --service*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
foreach ($dir in [Environment]::GetFolderPath('Programs'), [Environment]::GetFolderPath('Desktop')) {
  Remove-Item (Join-Path $dir 'JMeter Control Center.lnk') -ErrorAction SilentlyContinue
}
Write-Host 'JMeter Control Center service removed.'
