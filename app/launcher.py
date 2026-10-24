"""天学网单词PK助手 - 打包入口（无控制台）

架构选择：**不用 pywebview，改用 Edge --app 套壳**。

原因：pywebview 的 Windows 后端依赖 pythonnet（.NET），而 PyInstaller 打包后
CLR 找不到 .NETStandard 运行时，报
  RuntimeError: Failed to resolve Python.Runtime.Loader.Initialize
实测重定位 Python.Runtime.dll 也没用（是 CLR 初始化问题，不是路径问题）。

Edge --app 的好处：
  - 零 .NET 依赖，exe 从 110MB 降到 ~35MB
  - 窗口是独立窗口，无地址栏、无标签页、无浏览器菜单
  - 本机 Edge 必然存在（Windows 10/11 自带）

代价：依赖系统 Edge。找不到时回退到用默认浏览器打开（并提示）。
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
import traceback
import urllib.request
from pathlib import Path

HOST, PORT = "127.0.0.1", 8791
URL = f"http://{HOST}:{PORT}/"

# Edge 常见位置（按优先级）
EDGE_PATHS = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]


def app_root() -> Path:
    """可写工作目录（config.toml / data / logs）。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def bundle_root() -> Path:
    """只读资源目录（index.html 等打包进去的东西）。

    单目录模式（COLLECT）下资源实际在 exe 同级的 _internal/ 里，
    不是 sys._MEIPASS（那是单文件模式的解压目录）。
    这里按优先级探测，找不到再退回 exe 同级。
    """
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        cands = []
        mp = getattr(sys, "_MEIPASS", None)
        if mp:
            cands.append(Path(mp))
        cands.append(exe_dir / "_internal")
        cands.append(exe_dir)
        for c in cands:
            if (c / "index.html").exists():
                return c
        return exe_dir
    return Path(__file__).resolve().parent


def find_edge() -> str:
    env = os.environ.get("PK_EDGE")
    if env and Path(env).exists():
        return env
    for p in EDGE_PATHS:
        if Path(p).exists():
            return p
    # 注册表兜底
    try:
        import winreg
        for hive, key in (
            (winreg.HKEY_LOCAL_MACHINE,
             r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\App Paths\msedge.exe"),
            (winreg.HKEY_LOCAL_MACHINE,
             r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\msedge.exe"),
        ):
            try:
                with winreg.OpenKey(hive, key) as k:
                    v, _ = winreg.QueryValueEx(k, "")
                    if v and Path(v).exists():
                        return v
            except OSError:
                continue
    except Exception:  # noqa: BLE001
        pass
    return ""


def wait_server(timeout: float = 20.0) -> bool:
    """等后端端口起来。没起来就开窗口会看到「无法访问」。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(URL + "api/status", timeout=1.5) as r:
                if r.status == 200:
                    return True
        except Exception:  # noqa: BLE001
            time.sleep(0.3)
    return False


def open_window(edge: str, profile_dir: Path) -> subprocess.Popen | None:
    """用 Edge --app 打开独立窗口。

    参数说明：
      --app=URL          独立窗口（无地址栏/标签页/菜单）
      --user-data-dir    独立配置目录，避免跟用户日常浏览的 Edge 抢实例
                         （不隔离的话会复用到已有窗口，--app 不生效）
      --no-first-run 等  跳过首次启动引导
    """
    args = [
        edge,
        f"--app={URL}",
        "--window-size=1280,820",
        f"--user-data-dir={profile_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-sync",
        "--disable-background-networking",
        # 必须关掉 msEdgeSync 特性：本机 Edge 131 太旧，同步服务会报
        #   SyncServiceImpl unusable: Client version not supported
        # 然后 --app 窗口创建失败（进程起来但没窗口，实测踩过）。
        # 显式禁用整个同步特性集可绕开版本检查。
        "--disable-features=msEdgeSync,Translate,msEdgeSidebar,msEdgeCollections",
        "--disable-component-update",
        "--no-service-autorun",
        # 沙箱必须禁用：本机 Edge 156 由本程序（PyInstaller 冻结的无控制台进程）
        # 拉起时，renderer 进程一个都创建不出来，窗口一直是空白、标题停在
        # 127.0.0.1_/。实测加 --no-sandbox 后 renderer 立刻 7-8 个、页面 6 秒内加载。
        # 注意不要加 --disable-gpu-sandbox：它是 Edge 不支持的标志，提示信息里
        # 会点名它；--no-sandbox 同样会弹出「不受支持的命令行标志」黄色横条，
        # 所以后面必须跟 --test-type 把这条提示关掉（Chromium 预留的测试开关）。
        # 本程序只访问 127.0.0.1 的本地页面，禁用沙箱风险可控。
        "--no-sandbox",
        "--test-type",
    ]
    # 排障用：PK_EDGE_FLAGS="--no-sandbox --disable-gpu" 可以临时追加参数，
    # 不用为了试一个组合反复改代码重打包。
    extra = os.environ.get("PK_EDGE_FLAGS", "").strip()
    if extra:
        args += extra.split()
        _dbg(f"extra edge flags: {extra}")
    # 调试开关：设了 PK_EDGE_DEBUG=1 就让 Chromium 自己写日志到 logs/edge.log，
    # 用来查「页面永远不加载 / renderer 起不来」这类窗口侧问题。
    stderr_target = subprocess.DEVNULL
    if os.environ.get("PK_EDGE_DEBUG"):
        try:
            log_dir = app_root() / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            err_file = (log_dir / "edge_stderr.log").open("ab")
            stderr_target = err_file
            args += [
                "--enable-logging",
                "--v=1",
                f"--log-file={log_dir / 'edge.log'}",
            ]
            _dbg(f"edge debug logging on: {log_dir / 'edge.log'}")
        except Exception:  # noqa: BLE001
            pass
    # 冻结态（--noconsole）下父进程没有控制台，子进程继承句柄会失败。
    # DETACHED_PROCESS 让 Edge 完全脱离父进程的会话/控制台，
    # 这是 GUI 程序启动 GUI 程序的标准做法。
    flags = 0
    if os.name == "nt":
        DETACHED_PROCESS = 0x00000008
        CREATE_NEW_PROCESS_GROUP = 0x00000200
        flags = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    try:
        return subprocess.Popen(
            args,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=stderr_target,
            close_fds=True,
            creationflags=flags,
        )
    except Exception:  # noqa: BLE001
        return None


def main() -> int:
    root = app_root()
    bundle = bundle_root()

    log_dir = root / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    crash_log = log_dir / "crash.log"

    os.environ["PK_APP_ROOT"] = str(root)
    os.environ["PK_BUNDLE_ROOT"] = str(bundle)

    # 资源目录里带 index.html 与打包进去的模块；
    # app/ 也要加进来 —— screen_stream.py 在那个目录，main.py 会 import 它。
    for p in (bundle, bundle / "app", root / "app", root / "src", root / "tools"):
        sp = str(p)
        if sp not in sys.path:
            sys.path.insert(0, sp)

    try:
        import main as app_main
    except Exception:  # noqa: BLE001
        crash_log.write_text(traceback.format_exc(), encoding="utf-8")
        _error(f"启动失败，详见 {crash_log}")
        return 1

    # 后端跑在后台线程（main.serve），这里只负责开窗口
    import threading
    threading.Thread(target=app_main.serve, daemon=True).start()
    app_main.start_screen()

    if not wait_server():
        crash_log.write_text("后端 20 秒内没起来\n", encoding="utf-8")
        _error("服务启动超时。请检查是否有其他实例占用端口 8791。")
        return 1

    _dbg(f"server ok, edge={find_edge()!r}")
    edge = find_edge()
    profile = root / "data" / "browser-profile"
    try:
        profile.mkdir(parents=True, exist_ok=True)
    except (FileExistsError, NotADirectoryError):
        # 实测坑：如果 data 被误建成文件（复制资源时路径写错），
        # 这里会抛 FileExistsError 而不是 NotADirectoryError，进程直接死掉。
        # 退回到 exe 同级目录，保证窗口能开。
        crash_log.write_text(
            f"data 目录不可用（{root / 'data'}），退回到 {root / 'browser-profile'}\n",
            encoding="utf-8")
        profile = root / "browser-profile"
        profile.mkdir(parents=True, exist_ok=True)

    # 清掉 Edge 记住的窗口尺寸：实测第二次启动会沿用上一次的尺寸，
    # 即使传了 --window-size 也不生效（Edge 131 的行为）。
    import json as _json
    pref = profile / "Default" / "Preferences"
    if pref.exists():
        try:
            d = _json.loads(pref.read_text(encoding="utf-8"))
            if "browser" in d and "app_window_placement" in d["browser"]:
                del d["browser"]["app_window_placement"]
                pref.write_text(_json.dumps(d), encoding="utf-8")
                _dbg("cleared window placement")
        except Exception:  # noqa: BLE001
            pass

    proc = open_window(edge, profile) if edge else None
    _dbg(f"open_window -> {proc}")
    if proc is not None:
        time.sleep(1.0)
        _dbg(f"  after 1s returncode={proc.poll()}")
        # 立刻查一次进程，看是不是真的没起来
        _dbg(f"  msedge pids right after: {len(_msedge_pids())}")
    if proc is None:
        import webbrowser
        webbrowser.open(URL)
        _error("没找到 Microsoft Edge，已用默认浏览器打开。")

    # 不能只等 proc.wait()：Edge 是单例架构，启动后会把工作转交给已有进程
    # 然后自己立刻退出（实测 Popen 返回后几秒 returncode 就非 None），
    # 直接退出会让窗口刚开就没。改成轮询窗口状态。
    # Edge 启动是异步的：Popen 返回后要等几秒进程才真正出现，
    # 这期间立刻判断「没有 msedge 进程」会误退出。
    time.sleep(6.0)

    idle = 0
    while True:
        time.sleep(2.0)
        if not _port_alive():
            _dbg("backend down, exit")
            return 0
        if not _msedge_pids():
            _dbg("no msedge process, exit")
            return 0
        if not _has_visible_window():
            idle += 1
            if idle >= 15:
                _dbg("no visible window 30s, exit")
                return 0
        else:
            idle = 0


def _dbg(msg: str) -> None:
    try:
        p = app_root() / "logs" / "debug.log"
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as f:
            f.write(msg + "\n")
    except Exception:
        pass



def _port_alive() -> bool:
    try:
        with urllib.request.urlopen(URL + "api/status", timeout=2) as r:
            return r.status == 200
    except Exception:  # noqa: BLE001
        return False


def _run_hidden(args: list[str], **kw) -> subprocess.CompletedProcess:
    """无控制台地跑控制台程序。

    打包后主程序没有控制台，每次 spawn tasklist / adb 这类控制台程序，
    Windows 都会给它分配一个新的控制台窗口 —— 主循环每 2 秒查一次
    msedge 进程，屏幕上就是每 2 秒闪一次黑框。CREATE_NO_WINDOW 关掉它。
    """
    if os.name == "nt":
        kw.setdefault("creationflags", 0x08000000)
    return subprocess.run(args, **kw)


def _msedge_pids() -> set[int]:
    """当前所有 msedge 进程 PID。用 tasklist，避免引入额外依赖。"""
    try:
        p = _run_hidden(["tasklist", "/FI", "IMAGENAME eq msedge.exe", "/FO", "CSV", "/NH"],
                        capture_output=True, timeout=10)
        out = p.stdout.decode("utf-8", "replace")
        pids = set()
        import csv as _csv
        import io as _io
        for row in _csv.reader(_io.StringIO(out)):
            # 格式: "msedge.exe","36080","Console","2","192,192 K"
            if len(row) >= 2 and row[1].strip().isdigit():
                pids.add(int(row[1].strip()))
        return pids
    except Exception:  # noqa: BLE001
        return set()


def _has_visible_window() -> bool:
    """有没有可见的 msedge 窗口。"""
    try:
        import ctypes
        from ctypes import wintypes
        found = []

        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def _cb(hwnd, _):
            if not ctypes.windll.user32.IsWindowVisible(hwnd):
                return True
            n = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
            if n <= 0:
                return True
            buf = ctypes.create_unicode_buffer(n + 1)
            ctypes.windll.user32.GetWindowTextW(hwnd, buf, n + 1)
            # 只认我们自己的窗口：标题是「天学网单词PK助手」，
            # 或页面还没加载完时的 "127.0.0.1"（不带端口号，避免误匹配浏览器的
            # 其它 127.0.0.1 页面）
            t = buf.value.strip()
            if "天学网单词PK助手" in t or t == "127.0.0.1":
                found.append(t)
            return True

        ctypes.windll.user32.EnumWindows(_cb, 0)
        return bool(found)
    except Exception:  # noqa: BLE001
        return True   # 查不到就当有，别误退出


def _error(msg: str) -> None:
    """无控制台时用系统弹窗，别让失败静默。"""
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, msg, "天学网单词PK助手", 0x10)
    except Exception:  # noqa: BLE001
        print(msg, file=sys.stderr)


if __name__ == "__main__":
    sys.exit(main())
