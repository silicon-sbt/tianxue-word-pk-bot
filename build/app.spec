# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置。

产物：dist/天学网单词PK助手/天学网单词PK助手.exe（单目录）

关键决策：
  1. 不用 pywebview。它的 Windows 后端依赖 pythonnet(.NET)，PyInstaller 打包后
     CLR 找不到 .NETStandard 运行时，报
       RuntimeError: Failed to resolve Python.Runtime.Loader.Initialize
     实测重定位 Python.Runtime.dll 无效（CLR 初始化问题，不是路径问题）。
     改用 Edge --app 套壳：零 .NET 依赖，体积从 110MB 降到 35MB 左右。
  2. 单目录而非单文件。单文件每次启动解压 100MB+，冷启动 5-10 秒。
  3. console=False —— 不弹黑框（用户明确要求）。
"""
import sys
from pathlib import Path

ROOT = Path(SPECPATH).resolve().parent   # SPECPATH 是 build/ 目录
APP = ROOT / "app"

a = Analysis(
    [str(APP / "launcher.py")],
    pathex=[str(APP), str(ROOT / "src"), str(ROOT / "tools")],
    binaries=[],
    datas=[
        (str(APP / "index.html"), "."),
    ],
    hiddenimports=[
        "av",
        "PIL.Image",
        "PIL.ImageGrab",
        "adb_parse",
        "adb_driver",
        "screen_stream",
        "config",
        "ai_judge",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter", "unittest", "pydoc", "doctest", "test",
        "numpy", "pandas", "matplotlib", "scipy",
        "PyQt5", "PyQt6", "PySide2", "PySide6",
        "IPython", "jupyter", "notebook",
        "setuptools", "pip", "wheel",
        "webview", "clr", "pythonnet", "clr_loader",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=None,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=None)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="TianxuePK",   # ASCII 名：中文名会让 Inno 安装包初始化失败
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ROOT / "assets" / "app.ico") if (ROOT / "assets" / "app.ico").exists() else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="TianxuePK",   # ASCII 名：中文名会让 Inno 安装包初始化失败
)