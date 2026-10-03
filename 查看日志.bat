@echo off
REM View the run log (works while the bot is running - shows current progress).
setlocal
set "LOG=%~dp0logs\live_out.txt"
if not exist "%LOG%" (
    echo No log yet. Run the .vbs launcher first.
    pause
    exit /b 1
)
start "" notepad "%LOG%"