"""手机画面流：screenrecord(H.264) -> PyAV 解码 -> 最新帧缓存。

为什么不用 screencap：
  `adb exec-out screencap -p` 单帧实测 600-800ms（PNG 编码 + 传输 500KB-1MB），
  这是 adb 截图协议的上限，换写法救不了（raw 输出 2.8s 更慢）。
  连续画面必须走视频流。

为什么不用 scrcpy：
  scrcpy 画面在它自己的 SDL 窗口里，要嵌进我们的窗口得做 Win32 SetParent，
  跨进程窗口重父化在 DPI/边框/时序上很容易出问题。而 screenrecord 的
  H.264 流可以直接进 Python 解码，帧还能直接塞进现有 HTTP 接口。

代价：
  screenrecord 单次最长约 180 秒，所以进程断了要自动重启（这里做了）。
"""
from __future__ import annotations

import io
import subprocess
import threading
import time

import av
from PIL import Image

ADB = None  # 由调用方注入，避免重复实现 adb 定位


class NoSeekRaw:
    """给 av.open 用的只读不可 seek 流。

    为什么需要：PyAV 在容器 close() 时会尝试 seek 回起点，
    而 subprocess 管道不可 seek，会抛
      OSError [Errno 22] Invalid argument  (av/container/pyio.py)
    包一层显式声明「只读且不可 seek」，PyAV 就跳过这一步。
    """

    def __init__(self, raw) -> None:
        self._raw = raw

    def read(self, size: int = -1) -> bytes:
        try:
            return self._raw.read(size)
        except Exception:  # noqa: BLE001
            return b""

    def seekable(self) -> bool:
        return False

    def seek(self, *a, **k):
        raise OSError("not seekable")

    def tell(self) -> int:
        return 0

    def close(self) -> None:
        pass


class ScreenStream:
    """持续解码手机画面，维护「最新一帧」JPEG。"""

    def __init__(self, adb_path: str, serial_getter, target_width: int = 420,
                 quality: int = 62, max_fps: int = 20,
                 cmd_builder=None) -> None:
        self.adb = adb_path
        self.serial_getter = serial_getter
        self.target_width = target_width
        self.quality = quality
        self.min_interval = 1.0 / max_fps
        # 允许注入命令构造器，便于用假数据跑集成测试（不依赖真机）
        self._cmd_builder = cmd_builder or self._default_cmd

        self._lock = threading.Lock()
        self._frame = b""
        self._ts = 0.0
        self._err = ""
        self._fps = 0.0
        self._decoded = 0
        self._proc: subprocess.Popen | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # ------------------------------------------------------------ 生命周期

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._kill_proc()
        if self._thread:
            self._thread.join(timeout=3)

    def _kill_proc(self) -> None:
        p = self._proc
        self._proc = None
        if p is None:
            return
        try:
            p.terminate()
            p.wait(timeout=2)
        except Exception:  # noqa: BLE001
            try:
                p.kill()
            except Exception:  # noqa: BLE001
                pass

    # ------------------------------------------------------------ 主循环

    def _run(self) -> None:
        """外层循环：流断了（设备掉线 / screenrecord 到时）就重启。"""
        backoff = 1.0
        while not self._stop.is_set():
            serial = self.serial_getter()
            if not serial:
                with self._lock:
                    self._err = "未连接"
                self._stop.wait(1.0)
                continue
            try:
                self._stream_once(serial)
                backoff = 1.0
            except Exception as e:  # noqa: BLE001
                with self._lock:
                    self._err = f"{type(e).__name__}: {str(e)[:60]}"
            finally:
                self._kill_proc()
            if self._stop.is_set():
                break
            # screenrecord 到时会自己退出，这里短暂停顿后重启
            self._stop.wait(backoff)
            backoff = min(backoff * 1.5, 5.0)

    def _default_cmd(self, serial: str) -> list[str]:
        # 480x1066 是按 1260x2800 等比算的（高度取偶数）
        return [
            self.adb, "-s", serial, "exec-out",
            "screenrecord",
            "--output-format=h264",
            "--bit-rate", "4000000",
            "--size", "480x1066",
            "-",
        ]

    def _stream_once(self, serial: str) -> None:
        proc = subprocess.Popen(
            self._cmd_builder(serial),
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0)
        self._proc = proc

        container = av.open(NoSeekRaw(proc.stdout), format="h264")
        stream = container.streams.video[0]

        last_emit = 0.0
        window: list[float] = []
        for frame in container.decode(stream):
            if self._stop.is_set():
                return
            now = time.perf_counter()
            if now - last_emit < self.min_interval:
                continue
            last_emit = now

            img = frame.to_image()
            w, h = img.size
            tw = self.target_width
            img = img.resize((tw, int(h * tw / w)), Image.LANCZOS)
            buf = io.BytesIO()
            img.save(buf, "JPEG", quality=self.quality)

            window.append(now)
            if len(window) > 20:
                window.pop(0)
            fps = 0.0
            if len(window) >= 2 and window[-1] > window[0]:
                fps = (len(window) - 1) / (window[-1] - window[0])

            with self._lock:
                self._frame = buf.getvalue()
                self._ts = time.time()
                self._err = ""
                self._fps = fps
                self._decoded += 1

    # ------------------------------------------------------------ 读取

    def latest(self) -> bytes:
        with self._lock:
            return self._frame

    def stats(self) -> dict:
        with self._lock:
            age = round(time.time() - self._ts, 2) if self._ts else None
            return {
                "mode": "stream",
                "size": len(self._frame),
                "age": age,
                "fps": round(self._fps, 1),
                "decoded": self._decoded,
                "err": self._err,
            }
