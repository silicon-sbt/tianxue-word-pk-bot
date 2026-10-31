"""天学网单词PK助手 - 打包入口（无控制台）

架构选择：**不用 pywebview，改用 Edge --app 套壳**。

原因：pywebview 的 Windows 后端依赖 pythonnet（.NET），打包后常因
CLR 初始化失败而无法启动（Failed to resolve Python.Runtime.Loader.Initialize）。
这是运行时环境问题，重定位 DLL 无法解决。

Edge --app 的好处：
  - 零 .NET 依赖，exe 从 110MB 降到 ~35MB
  - 窗口是独立窗口，无地址栏、无标签页、无浏览器菜单
  - Windows 10/11 通常自带 Edge，无需额外安装

代价：依赖系统 Edge。找不到时回退到用默认浏览器打开（并提示）。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import traceback
import urllib.request
from pathlib import Path

HOST, PORT = "127.0.0.1", 8791
URL = f"http://{HOST}:{PORT}/"
# 页面 <title> 与窗口判据都必须是这一个字符串。
WINDOW_TITLE = "天学网单词PK助手"

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


def _local_opener() -> urllib.request.OpenerDirector:
    """访问回环地址用的 opener：显式绕过系统/环境变量代理。

    如果系统设置了 HTTP_PROXY，urllib 默认会把 http://127.0.0.1:8791
    也交给代理：既增加延迟，也可能在代理不稳定时误判「后端没起来」。
    回环地址不需要代理，直接连接。
    """
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


def wait_server(timeout: float = 20.0) -> bool:
    """等后端端口起来。没起来就开窗口会看到「无法访问」。

    每次尝试的异常和耗时都写进 debug.log，便于区分「后端未就绪」
    与「探测被代理/防火墙拦截」。
    """
    opener = _local_opener()
    deadline = time.time() + timeout
    attempt = 0
    t_start = time.time()
    while time.time() < deadline:
        attempt += 1
        t0 = time.time()
        try:
            with opener.open(URL + "api/status", timeout=1.5) as r:
                if r.status == 200:
                    _dbg(f"wait_server ok attempt={attempt} "
                         f"elapsed={time.time() - t_start:.3f}s")
                    return True
                _dbg(f"wait_server attempt={attempt} status={r.status} "
                     f"cost={time.time() - t0:.3f}s")
        except Exception as e:  # noqa: BLE001
            _dbg(f"wait_server attempt={attempt} {type(e).__name__}: "
                 f"{str(e)[:120]} cost={time.time() - t0:.3f}s")
            time.sleep(0.3)
    _dbg(f"wait_server timeout after {attempt} attempts, "
         f"{time.time() - t_start:.2f}s")
    return False


def _port_listener_pid(port: int = PORT) -> int | None:
    """8791 上 LISTENING 的 PID。用来区分「自己的后端」和「别的实例」。"""
    try:
        p = _run_hidden(["netstat", "-ano", "-p", "TCP"],
                        capture_output=True, timeout=10)
        for line in p.stdout.decode("utf-8", "replace").splitlines():
            parts = line.split()
            #  Proto  Local  Foreign  State  PID
            if (len(parts) >= 5 and parts[3] == "LISTENING"
                    and parts[1].endswith(f":{port}")):
                return int(parts[4])
    except Exception:  # noqa: BLE001
        return None
    return None


def _api_is_ours(timeout: float = 1.5) -> bool:
    """端口上的服务是不是本程序的（/api/status 结构对不对）。"""
    try:
        with _local_opener().open(URL + "api/status", timeout=timeout) as r:
            if r.status != 200:
                return False
            d = json.loads(r.read().decode("utf-8", "replace"))
            return isinstance(d, dict) and "stats" in d and "device" in d
    except Exception:  # noqa: BLE001
        return False


def _focus_existing_window() -> bool:
    """把已经在跑的实例窗口提到前台，避免用户以为没启动。"""
    try:
        import ctypes
        from ctypes import wintypes
        found: list[int] = []

        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def _cb(hwnd, _):
            n = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
            if n > 0:
                buf = ctypes.create_unicode_buffer(n + 1)
                ctypes.windll.user32.GetWindowTextW(hwnd, buf, n + 1)
                if buf.value.strip() == WINDOW_TITLE:
                    found.append(hwnd)
            return True

        ctypes.windll.user32.EnumWindows(_cb, 0)
        if found:
            ctypes.windll.user32.ShowWindow(found[0], 9)   # SW_RESTORE
            ctypes.windll.user32.SetForegroundWindow(found[0])
            return True
    except Exception:  # noqa: BLE001
        pass
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
        # 必须关掉 msEdgeSync 特性：旧版 Edge 的同步服务会因客户端版本过旧
        # 报 SyncServiceImpl unusable: Client version not supported，
        # 导致 --app 窗口创建失败（进程起来但没有窗口）。
        # 显式禁用整个同步特性集可绕开版本检查。
        "--disable-features=msEdgeSync,Translate,msEdgeSidebar,msEdgeCollections",
        "--disable-component-update",
        "--no-service-autorun",
        # 沙箱必须禁用：部分 Edge 版本被本程序（无控制台的冻结进程）拉起时，
        # renderer 进程无法创建，窗口一直空白、标题停在 127.0.0.1。
        # 加 --no-sandbox 后页面才能正常加载。
        # 注意不要加 --disable-gpu-sandbox：Edge 不支持该标志，会在提示里点名。
        # --no-sandbox 同样会触发「不受支持的命令行标志」黄色横条，
        # 所以必须跟 --test-type 把这提示关掉（Chromium 预留的测试开关）。
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

    # 单实例：端口上已经有本程序在服务，就聚焦旧窗口后退出，不再起第二个后端。
    # 旧实例关窗后可能仍短暂占用 8791；此时新实例的后端会绑定失败，
    # 而 wait_server 拿到的 200 可能来自旧实例 —— 这正是「接口 200 却没窗口」的来源。
    owner = _port_listener_pid()
    _dbg(f"start pid={os.getpid()} frozen={getattr(sys, 'frozen', False)} "
         f"root={root} bundle={bundle} port_owner={owner}")
    if owner and owner != os.getpid():
        if not _api_is_ours():
            crash_log.write_text(f"端口 {PORT} 被其他程序占用：PID {owner}\n",
                                 encoding="utf-8")
            _error(f"端口 {PORT} 被其他程序占用（PID {owner}），无法启动。\n"
                   "请关闭该程序后重试。")
            return 1
        if _focus_existing_window():
            _dbg(f"another instance serving 8791 (pid={owner}), focused it")
            return 0
        # 端口还是我们的、但没有窗口：多半是上一个实例刚关窗，正在 6 秒收尾里。
        # 这时直接退出会让用户「关了又开，什么都没有」，等它退干净再自己启动。
        _dbg(f"port owned by {owner} but no window; waiting for it to exit")
        for _ in range(16):
            time.sleep(0.5)
            if _port_listener_pid() in (None, os.getpid()):
                break
        else:
            _error("程序已经在运行，但没找到窗口。\n"
                   "请先在任务管理器结束 TianxuePK.exe 再启动。")
            return 0
        _dbg("previous instance gone, continue startup")

    try:
        import main as app_main
    except Exception:  # noqa: BLE001
        crash_log.write_text(traceback.format_exc(), encoding="utf-8")
        _error(f"启动失败，详见 {crash_log}")
        return 1

    # 后端跑在后台线程（main.serve），这里只负责开窗口
    import threading

    def _serve() -> None:
        try:
            app_main.serve()
        except Exception:  # noqa: BLE001 - 线程异常没人看得到，必须落盘
            tb = traceback.format_exc()
            try:
                (log_dir / "serve_error.log").write_text(tb, encoding="utf-8")
            except Exception:
                pass
            _dbg(f"serve() failed: {tb.splitlines()[-1]}")

    threading.Thread(target=_serve, daemon=True).start()
    _dbg("serve thread started")

    if not wait_server():
        owner_now = _port_listener_pid()
        crash_log.write_text(
            "后端 20 秒内没起来\n"
            f"本进程 PID: {os.getpid()}\n"
            f"{PORT} 当前监听 PID: {owner_now}\n"
            "详见 logs/debug.log 与 logs/serve_error.log\n",
            encoding="utf-8")
        _error("服务启动超时。请检查是否有其他实例占用端口 8791。")
        return 1

    owner_now = _port_listener_pid()
    _dbg(f"server ok listener={owner_now} self={os.getpid()} edge={find_edge()!r}")
    # 必须确认 200 来自自己的后端，否则后面所有接口都在跟别的实例说话
    if owner_now is not None and owner_now != os.getpid():
        crash_log.write_text(
            f"{PORT} 的监听者不是本进程：{owner_now} != {os.getpid()}\n",
            encoding="utf-8")
        _error("启动异常：8791 被其他进程接管。请结束后重试。")
        return 1

    edge = find_edge()
    profile = root / "data" / "browser-profile"
    try:
        profile.mkdir(parents=True, exist_ok=True)
    except (FileExistsError, NotADirectoryError):
        # 如果 data 被误建成文件（例如复制资源时路径写错），
        # mkdir 会抛 FileExistsError；退回 exe 同级目录，保证窗口能开。
        crash_log.write_text(
            f"data 目录不可用（{root / 'data'}），退回到 {root / 'browser-profile'}\n",
            encoding="utf-8")
        profile = root / "browser-profile"
        profile.mkdir(parents=True, exist_ok=True)

    # 清掉 Edge 记住的窗口尺寸：Edge 会沿用上一次的尺寸，
    # 导致启动参数里的 --window-size 不生效。
    pref = profile / "Default" / "Preferences"
    if pref.exists():
        try:
            d = json.loads(pref.read_text(encoding="utf-8"))
            if "browser" in d and "app_window_placement" in d["browser"]:
                del d["browser"]["app_window_placement"]
                pref.write_text(json.dumps(d), encoding="utf-8")
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

    # 不能只等 proc.wait()：Edge 是单例架构，启动后会把工作转交给已有进程，
    # 自己很快退出（Popen 的 returncode 会变成非 None）。若据此退出，
    # 窗口刚开就会消失。这里改为轮询窗口状态，给 25 秒首窗预算。
    t_win = time.time()
    while time.time() - t_win < 25:
        if _has_visible_window():
            break
        time.sleep(0.5)
    if not _has_visible_window():
        _dbg(f"no visible window in {time.time() - t_win:.1f}s, exit")
        crash_log.write_text(
            "后端已启动，但 25 秒内没有出现程序窗口。\n"
            "设 PK_EDGE_DEBUG=1 后重试可拿到 logs/edge.log、edge_stderr.log。\n",
            encoding="utf-8")
        return 2
    _dbg(f"window ready in {time.time() - t_win:.1f}s")

    # 画面流放到窗口之后再初始化：ADB 探测最坏要 15 秒，不能挡住启动
    def _screen() -> None:
        t0 = time.time()
        _dbg("start_screen begin")
        try:
            app_main.start_screen()
        except Exception:  # noqa: BLE001
            _dbg(f"start_screen failed: {traceback.format_exc().splitlines()[-1]}")
        _dbg(f"start_screen end {time.time() - t0:.2f}s")

    threading.Thread(target=_screen, daemon=True).start()

    # 退出判据只看「自己的窗口还在不在」。
    # 不要用「系统里有没有 msedge 进程」：用户自己开着 Edge 时这个条件永远为真。
    # 窗口标题也必须精确匹配：标题里含「天学网单词PK助手」的窗口（IDE、文件夹）
    # 会被误认为程序窗口，导致关窗后进程不退、端口一直被占。
    idle = 0
    while True:
        time.sleep(1.0)
        if not _port_alive():
            _dbg("backend down, exit")
            return 0
        if _has_visible_window():
            idle = 0
        else:
            idle += 1
            if idle >= 6:
                _dbg("window gone 6s, exit")
                return 0


def _dbg(msg: str) -> None:
    try:
        p = app_root() / "logs" / "debug.log"
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%H:%M:%S')} {msg}\n")
    except Exception:
        pass



def _port_alive() -> bool:
    try:
        with _local_opener().open(URL + "api/status", timeout=2) as r:
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


def _is_our_window_title(title: str) -> bool:
    """窗口标题是不是本程序的。

    精确匹配，不能用 `in`：任何标题含「天学网单词PK助手」的窗口
    （IDE、资源管理器、任务管理器）都会被误认成我们的窗口。
    """
    t = (title or "").strip()
    return t == WINDOW_TITLE or t == "127.0.0.1"


def _has_visible_window() -> bool:
    """有没有我们自己的可见窗口。"""
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
            # 页面加载完是 WINDOW_TITLE，加载中/失败时是 "127.0.0.1"
            # （不带端口号，避免误匹配浏览器其它 127.0.0.1 页面）
            if _is_our_window_title(buf.value):
                found.append(buf.value.strip())
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
