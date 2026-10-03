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
import pathlib
import re
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from pk_core import Question, WordBank, parse_screen, resolve, split_prompt  # noqa: E402
from adb_driver import Device  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
BANK = ROOT / "data" / "wordbank.json"
LEARNED = ROOT / "data" / "learned.json"
UNKNOWN = ROOT / "data" / "unknown.jsonl"
LOG = ROOT / "logs" / "pk.log"

# 题干框（1260x2800 实测）
PROMPT_RECT = (340, 690, 920, 850)


def log(msg: str) -> None:
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


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
    # 人工/自动补的高置信映射优先
    if LEARNED.exists():
        for gloss, word in json.loads(LEARNED.read_text(encoding="utf-8")).items():
            bank.by_gloss.setdefault(_norm(gloss), set()).add(_norm(word))
    return bank


def append_jsonl(path: pathlib.Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


PK_PACKAGE = "com.up366.mobile"
# 连续多久看不到答题页就退出（秒）。用时间而不是次数，避免每次 dump 2.5s 导致
# 「等 12 次」实际要等 36s。
NOT_IN_PK_SECONDS = 8.0


class Runner:
    def __init__(self, dev: Device, dry: bool) -> None:
        self.dev = dev
        self.dry = dry
        self.bank = load_bank()
        self.stat = {"hit": 0, "miss": 0, "taps": 0, "guess": 0}
        self._last_key = None
        self._not_in_pk = 0
        self._no_q_since: float | None = None

    def solve(self, q: Question) -> str | None:
        return resolve(q, self.bank)

    def best_guess(self, q: Question):
        """兜底猜测：优先反向打分第一名，其次随机。

        为什么不是纯随机：即使相似度低于阈值，第一名往往仍是最相关的候选
        （实测 '宏伟的' vs '雄伟的' 只有 0.45，但第一名就是正确答案）。
        """
        if not q.options:
            return None
        try:
            if q.direction == "en2zh":
                senses = self.bank.senses_of(q.gloss)
                ranked = sorted(
                    q.options,
                    key=lambda o: -self.bank._best_sense_score(
                        o.text, senses, q.pos) if senses else 0,
                )
                if senses and self.bank._best_sense_score(
                        ranked[0].text, senses, q.pos) > 0:
                    return ranked[0]
            else:
                scored = self.bank.score_options(q.gloss, q.option_texts(), q.pos)
                if scored:
                    top = scored[0][1]
                    return next((o for o in q.options if o.text == top), None)
        except Exception:
            pass
        import random
        return random.choice(q.options)

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
                # 全自动模式：拿不准也要作答（空着必 0 分，猜有 ~1/6 概率）。
                # 但「猜」不是乱猜——优先用反向打分的第一名（哪怕低于阈值），
                # 那通常是语义最接近的一个；完全无候选才随机。
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
                self.stat["guess"] += 1
                log(f"[~] {q.progress} [{q.direction}] {q.prompt!r} 未匹配，"
                    f"猜 {guess.text!r} @({guess.cx},{guess.cy}) dump {dump_dt:.2f}s")
                if not self.dry:
                    self.dev.tap(guess.cx, guess.cy)
                    self.stat["taps"] += 1
                time.sleep(0.1)
                continue

            self.stat["hit"] += 1
            target = next(o for o in q.options if o.text == answer)

            # 安全闸：确认目标选项在当前画面里确实存在且坐标在屏内，
            # 否则宁可不点（点错 = 直接丢分，比不答更糟）。
            if not (0 < target.cx < 1260 and 0 < target.cy < 2800):
                log(f"[!] 坐标越界，跳过: {answer!r} @({target.cx},{target.cy})")
                self.stat["hit"] -= 1
                self.stat["miss"] += 1
                time.sleep(0.15)
                continue

            log(f"[+] {q.progress} [{q.direction}] {q.prompt!r} -> {answer!r} "
                f"@({target.cx},{target.cy}) dump {dump_dt:.2f}s")
            if not self.dry:
                self.dev.tap(target.cx, target.cy)
                self.stat["taps"] += 1
            time.sleep(0.1)

        avg = sum(total_time) / len(total_time) if total_time else 0
        log(f"结束 确定命中={self.stat['hit']} 猜测={self.stat['guess']} "
            f"跳过={self.stat['miss']} 点击={self.stat['taps']} 平均 dump {avg:.2f}s")



def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true", help="只判定不点击")
    ap.add_argument("--max", type=int, default=130)
    ap.add_argument("--minutes", type=float, default=5.0,
                    help="最长运行分钟数，到点自动退出（默认 5）")
    a = ap.parse_args()

    dev = Device()
    dev.ensure_connected()
    log(f"设备 {dev.serial} {dev.screen_size()}")
    pkg = dev.current_package()
    if pkg and not pkg.startswith(PK_PACKAGE):
        log(f"警告：前台是 {pkg}，不是天学网。请先切到 PK 答题页再运行。")
    deadline = time.time() + a.minutes * 60
    try:
        Runner(dev, a.dry).run(a.max, deadline=deadline)
    except KeyboardInterrupt:
        log("已中断")



if __name__ == "__main__":
    main()
