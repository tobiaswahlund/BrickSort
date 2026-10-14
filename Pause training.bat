@echo off
rem Double-click to pause the training (or the making of training pictures).
rem Nothing is lost except the round that was running. Double-click Train.bat to carry on.
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='python.exe' or Name='cmd.exe'\" | Where-Object { $_.CommandLine -match 'legosorter\.(train|render)|Train\.bat' } | Sort-Object Name | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"
echo Paused. Double-click Train.bat to carry on where it stopped.
pause
