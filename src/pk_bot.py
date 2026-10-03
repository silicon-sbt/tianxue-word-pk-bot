"""PK 自动答题主程序。

4 秒预算下的调度策略：
  ┌─ 阶段1 定位：dump(2.5s) 拿题面 + 选项 + 每个选项的实时坐标
  ├─ 阶段2 判定：本地词库(1ms)
  ├─ 阶段3 点击：input tap(0.16s)
  └─ 阶段4 抢时间：用 screencap(0.6s) 轮询题干指纹，一变就说明换题了，
                    立刻回到阶段1

为什么这样排：dump 太慢，但它给的坐标是权威的（选项位置随机，必须现取）。
快路径只是用来「尽早发现换题」，避免在等待中干耗，把响应提前。

用法:
  python pk_bot.py --dry      只看判定不点击（先验证准确率）
  python pk_bot.py            实打
  python pk_bot.py --max 20   只打 20 题
"""
from __future__ import annotations

import argparse
import json
import json
import pathlib
import re
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from pk_core import Question, WordBank, parse_screen, resolve, split_prompt  # noqa: E402
from adb_driver import Device  # noqa: E402
from ai_judge import judge  # noqa: E402
from config import load as load_config  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
BANK = ROOT / "data" / "wordbank.json"
LEARNED = ROOT / "data" / "learned.json"
UNKNOWN = ROOT / "data" / "unknown.jsonl"
# 单一日志源：控制台看到的、查看日志.bat 打开的、启动.vbs 读的，都是这一份。
# 只在 python 这层写，不靠 shell 的 stdout 重定向——否则「可见」和「隐藏」
# 两种启动方式会各自留下一份内容不同、且互相重复的日志。
LOG = ROOT / "logs" / "live_out.txt"
STDERR_LOG = ROOT / "logs" / "stderr.txt"

# 题干框（1260x2800 实测）
PROMPT_RECT = (340, 690, 920, 850)


def log(msg: str) -> None:
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def reset_log() -> None:
    """每次运行清空日志，免得上一局内容混进来（结果摘要只看本次）。"""
    LOG.parent.mkdir(parents=True, exist_ok=True)
    LOG.write_text("", encoding="utf-8")


def _norm(s: str) -> str:
    return re.sub(r"[\s\-_]+", "", (s or "").strip().lower())


def load_bank() -> WordBank:
    bank = WordBank()
    if BANK.exists():
        data = json.loads(BANK.read_text(encoding="utf-8"))
        for word, senses in data.get("words", {}).items():
            bank.words.add(word)
            for item in senses:
                gloss, pos = (list(item) + [""])[:2]
                bank.add_sense(word, gloss, pos or None)
                bank.by_gloss.setdefault(_norm(gloss), set()).add(word)
    # 人工登记 / AI 兜底记下来的映射，优先级最高。
    # 一个 prompt 只会是中文或英文，所以按方向分别登记：
    #   中文题面 -> 英文答案（zh2en），英文题面 -> 中文答案（en2zh）
    if LEARNED.exists():
        try:
            learned = json.loads(LEARNED.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            learned = {}
        for prompt, answer in learned.items():
            if not isinstance(answer, str) or not answer.strip():
                continue
            bank.by_gloss.setdefault(_norm(prompt), set()).add(_norm(answer))
            if _is_ascii(prompt):
                pos, gloss = split_prompt(answer)
                bank.add_sense(prompt, gloss, pos)
    return bank


def _is_ascii(s: str) -> bool:
    """题面是否是英文（en2zh 方向）。"""
    return bool(s) and not any("\u4e00" <= c <= "\u9fff" for c in s)


def append_jsonl(path: pathlib.Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


PK_PACKAGE = "com.up366.mobile"
# 连续多久看不到答题页就退出（秒）。用时间而不是次数，避免每次 dump 2.5s 导致
# 「等 12 次」实际要等 36s。
NOT_IN_PK_SECONDS = 8.0


def ai_budget(seconds_left: int | None, configured: float,
              tap_reserve: float = 0.4) -> float:
    """算这次问 AI 最多能花多久。

    取「配置上限」和「界面剩余时间减去点击余量」中更小的那个。
    剩余时间不够就返回 0，调用方直接走本地猜测——绝不能因为等 AI 超时。
    """
    budget = float(configured)
    if seconds_left is not None:
        budget = min(budget, float(seconds_left) - tap_reserve)
    return max(0.0, budget)


class ScoreController:
    """控分器：让最终正确率贴近目标值。

    做法是比例控制，而不是「先全对、最后再错几道」——后者在榜单上
    看起来像突然放弃。这里每一题都按当前进度微调概率：

        目标 = target * 已答题数
        偏差 = 目标 - 已答对数
        p(答对) = target + 偏差 * gain   （再夹到 [0,1]）

    偏差为负（答得太好）就压低答对概率，为正（落后）就提高。
    """

    def __init__(self, target: float, gain: float = 0.5, rng=None) -> None:
        import random
        self.target = min(max(target, 0.0), 1.0)
        self.gain = gain
        self.rng = rng or random.Random()
        self.n = 0        # 已答
        self.k = 0        # 计划答对

    def take(self) -> bool:
        """轮到下一题：返回 True 表示这题该答对，False 表示故意答错。"""
        self.n += 1
        deficit = self.target * self.n - self.k
        p = self.target + deficit * self.gain
        p = min(max(p, 0.0), 1.0)
        correct = self.rng.random() < p
        if correct:
            self.k += 1
        return correct

    @property
    def planned_accuracy(self) -> float:
        return self.k / self.n if self.n else 0.0


class Runner:
    def __init__(self, dev: Device, dry: bool, cfg=None) -> None:
        self.dev = dev
        self.dry = dry
        self.cfg = cfg
        self.bank = load_bank()
        self.stat = {"hit": 0, "miss": 0, "taps": 0, "guess": 0,
                     "ai": 0, "ai_fail": 0, "faked": 0}
        self._last_key = None
        self._not_in_pk = 0
        self._no_q_since: float | None = None
        self._warned_no_key = False

        self.ai_cfg = getattr(cfg, "ai", None) if cfg else None
        sc = getattr(cfg, "score", None) if cfg else None
        self.score = None
        if sc is not None and getattr(sc, "enabled", False):
            self.score = ScoreController(float(getattr(sc, "target_accuracy", 0.7)))

    def solve(self, q: Question) -> str | None:
        return resolve(q, self.bank)

    def rank(self, q: Question) -> list[tuple[float, str]]:
        try:
            return self.bank.rank_options(q)
        except Exception:
            return []

    def best_guess(self, q: Question):
        """兜底猜测：语义最接近的那个，实在没有就随机。

        为什么不是纯随机：即使相似度低于阈值，第一名往往仍是最相关的候选
        （实测 '宏伟的' vs '雄伟的' 只有 0.45，但第一名就是正确答案）。
        """
        if not q.options:
            return None
        ranked = self.rank(q)
        if ranked and ranked[0][0] > 0:
            top = ranked[0][1]
            return next((o for o in q.options if o.text == top), None)
        import random
        return random.choice(q.options)

    def pick_wrong(self, q: Question, correct: str | None):
        """控分要故意答错时，挑一个「像样」的错项。

        优先取语义第二接近的选项——看起来像真答错了，而不是乱点。
        """
        if not q.options:
            return None
        ranked = [t for _, t in self.rank(q) if t != correct]
        pool = ranked[:3] or [o.text for o in q.options if o.text != correct]
        if not pool:
            return None
        import random
        pick = random.choice(pool)
        return next((o for o in q.options if o.text == pick), None)

    def ask_ai(self, q: Question) -> tuple[str | None, bool]:
        """问 AI 要答案。返回 (选项原文, 是否来自 AI)。

        超时预算 = min(配置上限, 界面剩余秒数 - 点击余量)。
        这样即使 AI 很慢，也只是这一题退化成猜测，绝不会拖过答题时限。
        """
        cfg = self.ai_cfg
        if cfg is None or not getattr(cfg, "enabled", False):
            return None, False
        if not getattr(cfg, "api_key", ""):
            if not self._warned_no_key:
                log("[ai] 已启用但没配 api_key（config.toml 或环境变量 PK_API_KEY），跳过")
                self._warned_no_key = True
            return None, False

        budget = ai_budget(q.seconds_left, getattr(cfg, "timeout", 1.8))
        if budget < 0.3:
            log(f"[ai] 剩余 {q.seconds_left}s，来不及问，直接猜")
            return None, False

        t0 = time.perf_counter()
        res = judge(q, cfg, timeout=budget)
        dt = time.perf_counter() - t0

        if res.text is None:
            self.stat["ai_fail"] += 1
            log(f"[ai] 未取到答案（{dt:.2f}s，{res.raw[:60]}）")
            return None, False

        log(f"[ai] {q.prompt!r} -> {res.text!r} 置信 {res.confidence:.2f} "
            f"用时 {dt:.2f}s")
        if getattr(cfg, "remember", True):
            self.remember(q, res.text)
        return res.text, True

    @staticmethod
    def remember(q: Question, answer: str) -> None:
        """把 AI 的答案存进 learned.json，下次直接命中、不再联网。

        这是 AI 兜底最划算的部分：同一个词一辈子只问一次。
        """
        try:
            data = {}
            if LEARNED.exists():
                data = json.loads(LEARNED.read_text(encoding="utf-8"))
            data[q.gloss] = answer
            LEARNED.parent.mkdir(parents=True, exist_ok=True)
            LEARNED.write_text(json.dumps(data, ensure_ascii=False, indent=1),
                               encoding="utf-8")
        except (OSError, json.JSONDecodeError) as e:
            log(f"[ai] 缓存失败: {e}")

    def run(self, max_q: int, deadline: float | None = None) -> None:
        log(f"词库 {len(self.bank.by_gloss):,} 键 / {len(self.bank.words):,} 词 | dry={self.dry}")
        total_time: list[float] = []

        while self.stat["hit"] + self.stat["miss"] + self.stat["guess"] < max_q:
            if deadline and time.time() > deadline:
                log("到达时间上限，退出")
                break

            # 每轮先确认还在天学网，否则立刻收工（避免在别的 App 上空转）
            pkg = self.dev.current_package()
            if pkg and not pkg.startswith(PK_PACKAGE):
                self._not_in_pk += 1
                if self._not_in_pk >= 3:
                    log(f"前台已是 {pkg}，不在 PK 页，退出")
                    break
                log(f"前台={pkg}，等待回到 PK…")
                time.sleep(1.0)
                continue
            self._not_in_pk = 0

            t0 = time.perf_counter()
            try:
                xml = self.dev.dump_ui_stable()
            except Exception as e:
                log(f"dump 失败: {str(e)[:80]}")
                time.sleep(0.3)
                continue
            dump_dt = time.perf_counter() - t0

            q = parse_screen(xml)
            if q is None:
                if self._no_q_since is None:
                    self._no_q_since = time.time()
                    log("当前不是答题页（房间页/结算页），等待进入 PK…")
                waited = time.time() - self._no_q_since
                if waited >= NOT_IN_PK_SECONDS:
                    log(f"已等待 {waited:.0f}s 仍未见答题页，退出")
                    break
                time.sleep(0.4)
                continue
            if self._no_q_since is not None:
                log(f"已进入答题页（等待了 {time.time()-self._no_q_since:.1f}s）")
                self._no_q_since = None
            self._not_in_pk = 0

            key = (q.progress, q.prompt, tuple(sorted(q.option_texts())))
            if key == self._last_key:
                # 同一题重复读到：dry 模式下不会变；live 模式下说明点了但题没变，
                # 短暂等待后重读，不要空转 dump。
                time.sleep(0.12)
                continue
            self._last_key = key

            answer = self.solve(q)
            total_time.append(dump_dt)

            if answer is None:
                # 本地判不出来。先问 AI（只有这一步才联网，且超时预算按界面
                # 倒计时动态收紧，绝不会因为等 AI 而拖过答题时限）。
                answer, from_ai = self.ask_ai(q)

                if answer is None:
                    # AI 没启用/没赶上/也没答案 → 本地猜一个，绝不留空。
                    guess = self.best_guess(q)
                    append_jsonl(UNKNOWN, {
                        "progress": q.progress, "prompt": q.prompt, "gloss": q.gloss,
                        "pos": q.pos, "direction": q.direction,
                        "options": q.option_texts(),
                        "guessed": guess.text if guess else None,
                    })
                    if guess is None:
                        self.stat["miss"] += 1
                        log(f"[?] {q.progress} [{q.direction}] {q.prompt!r} 无可选项，跳过")
                        time.sleep(0.15)
                        continue
                    answer = guess.text
                    self.stat["guess"] += 1
                    tag = "猜"
                else:
                    self.stat["ai"] += 1
                    tag = "AI"
            else:
                tag = "命中"

            # 控分：该故意答错时，换成一个「像样」的错项
            if self.score is not None and not self.score.take() and answer:
                wrong = self.pick_wrong(q, answer)
                if wrong is not None:
                    log(f"[-] {q.progress} [{q.direction}] {q.prompt!r} 控分："
                        f"本应 {answer!r}，改选 {wrong.text!r}")
                    answer = wrong.text
                    self.stat["faked"] += 1
                    tag = "控分"

            self.stat["hit"] += 1
            target = next((o for o in q.options if o.text == answer), None)
            if target is None:
                self.stat["hit"] -= 1
                self.stat["miss"] += 1
                log(f"[!] 选项已消失，跳过: {answer!r}")
                time.sleep(0.15)
                continue

            # 安全闸：确认目标选项在当前画面里确实存在且坐标在屏内，
            # 否则宁可不点（点错 = 直接丢分，比不答更糟）。
            if not (0 < target.cx < 1260 and 0 < target.cy < 2800):
                log(f"[!] 坐标越界，跳过: {answer!r} @({target.cx},{target.cy})")
                self.stat["hit"] -= 1
                self.stat["miss"] += 1
                time.sleep(0.15)
                continue

            log(f"[+] {q.progress} [{q.direction}] {q.prompt!r} -> {answer!r} "
                f"@({target.cx},{target.cy}) {tag} dump {dump_dt:.2f}s")
            if not self.dry:
                self.dev.tap(target.cx, target.cy)
                self.stat["taps"] += 1

            time.sleep(0.1)

        avg = sum(total_time) / len(total_time) if total_time else 0
        parts = [f"确定命中={self.stat['hit']}", f"猜测={self.stat['guess']}"]
        if self.stat["ai"]:
            parts.append(f"AI={self.stat['ai']}")
        if self.stat["ai_fail"]:
            parts.append(f"AI未答={self.stat['ai_fail']}")
        if self.stat["faked"]:
            parts.append(f"控分={self.stat['faked']}")
        parts += [f"跳过={self.stat['miss']}", f"点击={self.stat['taps']}",
                  f"平均 dump {avg:.2f}s"]
        log("结束 " + " ".join(parts))
        if self.score is not None and self.score.n:
            log(f"控分目标 {self.score.target:.0%}，本局计划正确率 "
                f"{self.score.planned_accuracy:.0%}（{self.score.k}/{self.score.n}）")



def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true", help="只判定不点击")
    ap.add_argument("--max", type=int, default=130)
    ap.add_argument("--minutes", type=float, default=5.0,
                    help="最长运行分钟数，到点自动退出（默认 5）")
    a = ap.parse_args()

    cfg = load_config()
    dev = Device()
    dev.ensure_connected()
    log(f"设备 {dev.serial} {dev.screen_size()}")
    pkg = dev.current_package()
    if pkg and not pkg.startswith(PK_PACKAGE):
        log(f"警告：前台是 {pkg}，不是天学网。请先切到 PK 答题页再运行。")
    deadline = time.time() + a.minutes * 60
    try:
        Runner(dev, a.dry, cfg).run(a.max, deadline=deadline)
    except KeyboardInterrupt:
        log("已中断")



if __name__ == "__main__":
    main()
