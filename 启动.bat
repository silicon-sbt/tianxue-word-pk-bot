@echo off
REM ============================================================
REM  Tianxue Word PK Bot - launcher (visible console version)
REM
REM  Normal use : double-click the .vbs file (no console window)
REM  Debugging  : double-click THIS file (shows full output)
REM
REM  With "hidden" argument: no prompts, no pause
REM  (called by the .vbs launcher).
REM
REM  Kept ASCII-only on purpose: cmd.exe reads .bat in the system
REM  ANSI codepage, so non-ASCII text here breaks on other locales.
REM ============================================================
setlocal
cd /d "%~dp0"
if /i "%~1"=="hidden" set "HIDDEN=1"

if not defined HIDDEN (
    echo.
    echo ============================================
    echo   Tianxue Word PK Bot
    echo ============================================
    echo.
)

REM --- check python ---
where python >nul 2>&1
if errorlevel 1 (
    echo [ERROR] python not found. Install Python 3.10+ and tick "Add to PATH".
    call :pause_if_visible
    exit /b 1
)

REM --- check adb ---
REM Resolve the actual adb.exe PATH once and use that variable everywhere.
REM Calling bare "adb" fails whenever it is installed but not on PATH
REM (the common case for a plain Android SDK install).
REM Search order mirrors src/adb_driver.py _find_adb().
set "ADB="
for %%I in (adb.exe) do if not defined ADB set "ADB=%%~$PATH:I"
if not defined ADB if exist "%LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe" set "ADB=%LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe"
if not defined ADB if exist "C:\platform-tools\adb.exe" set "ADB=C:\platform-tools\adb.exe"
if not defined ADB if exist "D:\platform-tools\adb.exe" set "ADB=D:\platform-tools\adb.exe"
if not defined ADB if exist "E:\platform-tools\adb.exe" set "ADB=E:\platform-tools\adb.exe"
if not defined ADB (
    echo [ERROR] adb.exe not found. Install Android Platform Tools and add it to PATH.
    echo         https://developer.android.com/tools/releases/platform-tools
    call :pause_if_visible
    exit /b 1
)

if not defined HIDDEN (
    echo [1/3] Checking device connection...
    "%ADB%" devices
    echo.
    echo [2/3] Checking wordbank...
)

if not exist "data\wordbank.json" (
    if not defined HIDDEN echo       wordbank missing, building...
    python -X utf8 src\build_bank.py
    if errorlevel 1 (
        echo [ERROR] Failed to build wordbank. If data\ed.db is missing,
        echo         pull it from the phone as described in README.
        call :pause_if_visible
        exit /b 1
    )
)
if not defined HIDDEN echo       wordbank ready

if not defined HIDDEN (
    echo.
    echo [3/3] Starting bot
    echo.
    echo   ^>^>^> Open Tianxue app and enter a PK room on your phone ^<^<^<
    echo   ^>^>^> The bot waits for the quiz page, then answers automatically ^<^<^<
    echo.
    echo   Press Ctrl+C to stop at any time
    echo.
)

if defined HIDDEN (
    REM Hidden mode: the console is invisible, so run_watch.py writes the log
    REM file itself (logs\live_out.txt). Only unexpected tracebacks on stderr
    REM need capturing here - redirecting stdout as well would duplicate
    REM every line into the same file.
    python -X utf8 src\run_watch.py --live --max 130 --minutes 30 --wait 600 2>> "logs\stderr.txt"
) else (
    REM Visible mode: python prints to this console AND writes logs\live_out.txt,
    REM so "????.bat" shows the same thing you see here.
    python -X utf8 src\run_watch.py --live --max 130 --minutes 30 --wait 600
)
set "RC=%ERRORLEVEL%"


if not defined HIDDEN (
    echo.
    echo Finished. Log: logs\live_out.txt
)
call :pause_if_visible
exit /b %RC%

:pause_if_visible
if not defined HIDDEN pause
goto :eof