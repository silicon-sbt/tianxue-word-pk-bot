@echo off
REM ============================================================
REM  天学网单词PK助手 - 一键启动
REM  用法: 双击本文件，或在命令行执行
REM ============================================================
setlocal
cd /d "%~dp0"

echo.
echo ============================================
echo   天学网单词PK助手
echo ============================================
echo.

REM --- 检查 python ---
where python >nul 2>&1
if errorlevel 1 (
    echo [错误] 找不到 python，请先安装 Python 3.10+
    pause
    exit /b 1
)

REM --- 检查 adb ---
set "ADB=C:\Users\%USERNAME%\AppData\Local\Android\Sdk\platform-tools\adb.exe"
if not exist "%ADB%" (
    if exist "C:\platform-tools\adb.exe" set "ADB=C:\platform-tools\adb.exe"
)
if not exist "%ADB%" (
    echo [错误] 找不到 adb.exe
    echo        请安装 Android Platform Tools，或修改本文件里的 ADB 路径
    pause
    exit /b 1
)

echo [1/3] 检查手机连接...
"%ADB%" devices
echo.

echo [2/3] 检查词库...
if not exist "data\wordbank.json" (
    echo       词库不存在，正在从 ed.db 构建...
    python -X utf8 src\build_bank.py
    if errorlevel 1 (
        echo [错误] 词库构建失败
        pause
        exit /b 1
    )
)
echo       词库就绪
echo.

echo [3/3] 启动助手
echo.
echo   >>> 现在请在手机上打开天学网，进入 PK 房间 <<<
echo   >>> 脚本会自动等待答题页出现，然后开始答题   <<<
echo.
echo   按 Ctrl+C 可随时停止
echo.

python -X utf8 src\run_watch.py --live --max 130 --minutes 30 --wait 600

echo.
echo 已结束。日志见 logs\live_out.txt
pause
