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
REM Search range mirrors src/adb_driver.py _find_adb(), otherwise this
REM pre-flight reports a false failure when adb lives elsewhere.
set "ADB_FOUND="
where adb >nul 2>&1 && set "ADB_FOUND=1"
if not defined ADB_FOUND if exist "%LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe" set "ADB_FOUND=1"
if not defined ADB_FOUND if exist "C:\platform-tools\adb.exe" set "ADB_FOUND=1"
if not defined ADB_FOUND if exist "D:\platform-tools\adb.exe" set "ADB_FOUND=1"
if not defined ADB_FOUND (
    echo [ERROR] adb.exe not found. Install Android Platform Tools and add it to PATH.
    echo         https://developer.android.com/tools/releases/platform-tools
    call :pause_if_visible
    exit /b 1
)

if not defined HIDDEN (
    echo [1/3] Checking device connection...
    adb devices
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
    REM Hidden mode: user cannot see the console, so capture output into the
    REM log file. The .vbs launcher reads its last line to show what happened.
    python -X utf8 src\run_watch.py --live --max 130 --minutes 30 --wait 600 >> "logs\live_out.txt" 2>&1
) else (
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