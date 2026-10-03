@echo off
REM Stop the running bot. Only kills THIS project's python processes.
setlocal
echo.
echo Looking for the bot process...
powershell -NoProfile -Command "$p = Get-CimInstance Win32_Process | Where-Object { $_.Name -like 'python*' -and $_.CommandLine -match 'run_watch|pk_bot' }; if ($p) { $p | ForEach-Object { Write-Host ('  stopping PID ' + $_.ProcessId); Stop-Process -Id $_.ProcessId -Force } } else { Write-Host '  no bot is running' }"
echo.
echo Done.
timeout /t 3 >nul