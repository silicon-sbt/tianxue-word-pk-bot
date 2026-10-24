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
import re
import subprocess
import threading
import time

import proc as nowin
import av
from PIL import Image

class NoSeekRaw:
    """给 av.open 用的只读不可 seek 流。

    为什么需要：PyAV 的 pyio 契约是「只要对象有 seek+tell 且 seekable()
    返回 True，就注册 seek 回调」。Windows 管道是 BufferedReader，
    seekable() 返回 True，但 seek(-1, SEEK_END) 会抛
      OSError [Errno 22] Invalid argument  (av/container/pyio.py)
    实测发生在 av.open() 阶段（不是 close）。
    只暴露 read()、不给 seek/tell，PyAV 就不注册 seek 回调，能正常解码。

    注意：read() 不吞异常。管道断了必须让 OSError 冒到解码循环，
    否则会被伪装成「正常流结束」，退避逻辑永远升不上去，坏流会以 1Hz 热重启。
    """

    def __init__(self, raw) -> None:
        self._raw = raw

    def read(self, size: int = -1) -> bytes:
        return self._raw.read(size)

    def seekable(self) -> bool:
        return False


class ScreenStream:
    """持续解码手机画面，维护「最新一帧」JPEG。"""

    # 画面只给人看，不参与判定，所以压小压快：
    # 420 宽（原图 1260）够看清题目，BILINEAR 缩放比 LANCZOS 快约 30%
    TARGET_WIDTH = 420
    QUALITY = 62
    MAX_FPS = 20

    def __init__(self, adb_path: str, serial_getter, cmd_builder=None) -> None:
        self.adb = adb_path
        self.serial_getter = serial_getter
        self.min_interval = 1.0 / self.MAX_FPS
        # 允许注入命令构造器，便于用假数据跑集成测试（不依赖真机）
        self._cmd_builder = cmd_builder or self._default_cmd
        # 设备尺寸按 serial 缓存：wm size 要 100ms+，不能每次重开流都问
        self._sizes: dict[str, str] = {}

        self._lock = threading.Lock()
        # 新帧通知：消费端（MJPEG）阻塞等，不用轮询 stats() 猜有没有新帧
        self._cond = threading.Condition(self._lock)
        self._seq = 0              # 单调递增的帧序号，0 表示还没有帧
        self._frame = b""
        self._ts = 0.0
        self._err = ""
        self._decoded = 0
        self._proc: subprocess.Popen | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _capture_size(self, serial: str) -> str:
        """按设备真实分辨率等比算 screenrecord 的 --size。

        让**手机端直接编成目标宽度**（TARGET_WIDTH），解码后就不用再缩放。
        实测：直出 420x932 是 3.28ms/帧，先出 480x1066 再缩是 8.41ms/帧，
        快 2.6 倍（省掉 PIL resize 的 4.3ms）。
        原先还硬编码 480x1066，换机型会拉伸或直接失败。
        """
        cached = self._sizes.get(serial)
        if cached:
            return cached
        tw = self.TARGET_WIDTH
        th = int(round(2800 * tw / 1260 / 2) * 2)   # 1260x2800 的回退比例
        try:
            p = nowin.run([self.adb, "-s", serial, "shell", "wm", "size"],
                          capture_output=True, timeout=8)
            out = (p.stdout + p.stderr).decode("utf-8", "replace")
            m = re.search(r"(\d+)x(\d+)", out)
            if m:
                w, h = int(m.group(1)), int(m.group(2))
                th = int(round(h * tw / w / 2) * 2)      # 偶数
        except Exception:  # noqa: BLE001 - 探测失败就用回退值
            pass
        if not (100 <= th <= 2000):
            th = int(round(2800 * tw / 1260 / 2) * 2)
        size = f"{tw}x{th}"
        self._sizes[serial] = size
        return size


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
        return [
            self.adb, "-s", serial, "exec-out",
            "screenrecord",
            "--output-format=h264",
            "--bit-rate", "4000000",
            "--size", self._capture_size(serial),
            "-",
        ]

    def _stream_once(self, serial: str) -> None:
        proc = nowin.popen(
            self._cmd_builder(serial),
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0)
        self._proc = proc

        container = av.open(NoSeekRaw(proc.stdout), format="h264")
        stream = container.streams.video[0]

        last_emit = 0.0
        for frame in container.decode(stream):
            if self._stop.is_set():
                return
            now = time.perf_counter()
            if now - last_emit < self.min_interval:
                continue
            last_emit = now

            img = frame.to_image()
            w, h = img.size
            # 手机端已按 TARGET_WIDTH 编码，正常情况这里不用缩放。
            # 若机型不支持该 --size 导致实际宽度不同，才兜底缩一次。
            if w != self.TARGET_WIDTH:
                img = img.resize(
                    (self.TARGET_WIDTH, int(h * self.TARGET_WIDTH / w)),
                    Image.BILINEAR)
            buf = io.BytesIO()
            img.save(buf, "JPEG", quality=self.QUALITY)

            with self._cond:
                self._frame = buf.getvalue()
                self._ts = time.time()
                self._err = ""
                self._decoded += 1
                self._seq += 1
                self._cond.notify_all()

    # ------------------------------------------------------------ 读取

    def wait_frame(self, seq: int, timeout: float = 5.0):
        """阻塞等到比 seq 更新的帧。

        返回 (新序号, jpeg)；超时或流已停时返回 (seq, b"")。
        有了这个，消费端不用 sleep 轮询 stats()['decoded'] 猜有没有新帧。
        """
        with self._cond:
            self._cond.wait_for(
                lambda: self._seq > seq or self._stop.is_set(), timeout)
            if self._seq <= seq:
                return seq, b""
            return self._seq, self._frame

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
                "decoded": self._decoded,
                "err": self._err,
            }
