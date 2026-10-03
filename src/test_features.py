"""新增功能的测试：配置加载 / 控分 / AI 解析 / 超时预算 / 选错项。

跑法：python -X utf8 src/test_features.py
"""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))

from ai_judge import AIResult, build_request, judge, parse_answer  # noqa: E402
from config import Config, DEFAULTS, load  # noqa: E402
from pk_bot import ScoreController, ai_budget, load_bank  # noqa: E402
from pk_core import Option, Question, split_prompt  # noqa: E402

FAILS = []


def check(name: str, got, want) -> None:
    ok = got == want
    print(f"  [{'OK ' if ok else 'FAIL'}] {name}: {got!r}" + ("" if ok else f"  期望 {want!r}"))
    if not ok:
        FAILS.append(name)


def Q(prompt, options, seconds=None):
    pos, gloss = split_prompt(prompt)
    return Question(prompt=prompt, pos=pos, gloss=gloss,
                    options=[Option(t, 0, 0) for t in options],
                    screen_h=2800, seconds_left=seconds)


# ---------------------------------------------------------------- 配置
print("\n== 配置 ==")
c = Config()
check("缺省 ai.enabled", c.ai.enabled, False)
check("缺省 score.target", c.score.target_accuracy, 0.70)
check("缺省 bot 限时", c.bot.question_seconds, 6.0)

check("target 写 70 -> 0.7", Config({"score": {"target_accuracy": 70}}).score.target_accuracy, 0.7)
check("target 写 5 -> 5%（>1 视作百分数）",
      Config({"score": {"target_accuracy": 5}}).score.target_accuracy, 0.05)
check("target 写 500 -> 夹到 1.0",
      Config({"score": {"target_accuracy": 500}}).score.target_accuracy, 1.0)
check("负数夹紧", Config({"score": {"target_accuracy": -1}}).score.target_accuracy, 0.0)
check("timeout 字符串能转", Config({"ai": {"timeout": "2.5"}}).ai.timeout, 2.5)
check("timeout 乱写回落默认",
      Config({"ai": {"timeout": "abc"}}).ai.timeout, DEFAULTS["ai"]["timeout"])
check("未知字段不影响", Config({"ai": {"nope": 1}}).ai.enabled, False)
check("部分配置合并", Config({"ai": {"enabled": True}}).ai.timeout, DEFAULTS["ai"]["timeout"])

# 坏 TOML 不应该崩
bad = pathlib.Path(r"E:\code\单词pk\logs\_bad.toml")
bad.parent.mkdir(parents=True, exist_ok=True)
bad.write_text("this is [not valid toml", encoding="utf-8")
check("坏 TOML 回退默认", load(bad).ai.enabled, False)
bad.unlink(missing_ok=True)


# ---------------------------------------------------------------- 超时预算
print("\n== 超时预算 ==")
check("界面剩 5s，配置 1.8 -> 1.8", ai_budget(5, 1.8), 1.8)
check("界面剩 1.5s -> 1.1（扣点击余量）", round(ai_budget(1.5, 1.8), 3), 1.1)
check("界面剩 0.2s -> 0（来不及）", ai_budget(0.2, 1.8), 0.0)
check("不返回负数", ai_budget(-5, 1.8), 0.0)
check("界面没倒计时就取配置", ai_budget(None, 1.8), 1.8)


# ---------------------------------------------------------------- 控分
print("\n== 控分 ==")
for target in (0.0, 0.4, 0.7, 1.0):
    sc = ScoreController(target)
    for _ in range(2000):
        sc.take()
    acc = sc.planned_accuracy
    ok = abs(acc - target) < 0.05
    print(f"  [{'OK ' if ok else 'FAIL'}] 目标 {target:.0%} -> 实际 {acc:.1%}")
    if not ok:
        FAILS.append(f"控分收敛 {target}")

sc = ScoreController(0.6)
check("第一次 take 返回布尔", isinstance(sc.take(), bool), True)
sc2 = ScoreController(0.0)
check("目标 0 时永远答错", all(sc2.take() is False for _ in range(50)), True)
sc3 = ScoreController(1.0)
check("目标 1 时永远答对", all(sc3.take() is True for _ in range(50)), True)


# ---------------------------------------------------------------- AI 解析
print("\n== AI 返回解析 ==")
OPTS = ["grand", "kettle", "exact", "painter"]

# Jev 原生结构
native = {"answers": {"answer": {"type": "choice", "choice": "o2",
                                 "confidence": 0.91,
                                 "probabilities": {"o2": 0.91, "o0": 0.09}}}}
r = parse_answer(native, OPTS)
check("Jev 原生 choice", r.text, "exact")
check("Jev 原生 confidence", round(r.confidence, 2), 0.91)

# 模型直出的简化结构
check("裸 choice", parse_answer({"choice": "o0"}, OPTS).text, "grand")
# 直接回显选项原文
check("回显选项原文", parse_answer({"choice": "painter"}, OPTS).text, "painter")
# 数字下标
check("数字下标", parse_answer({"choice": 1}, OPTS).text, "kettle")
# 被 ```json 包起来
check("代码块包裹", parse_answer('```json\n{"choice":"o3"}\n```', OPTS).text, "painter")
# 夹带说明文字
check("夹带文字", parse_answer('好的，答案是 {"choice":"o2"}', OPTS).text, "exact")
# 只能靠 probabilities 推断
check("靠概率推断", parse_answer({"probabilities": {"o1": 0.8, "o2": 0.2}}, OPTS).text, "kettle")
# 各种垃圾输入都必须安全返回 None，不能让答题崩掉
for junk in ("", "not json", "[]", "null", {"choice": "o99"}, {"choice": "不存在"},
             {"answers": {}}, '{"answers":{"answer":{}}}', 12345):
    got = parse_answer(junk, OPTS)
    ok = isinstance(got, AIResult) and got.text is None
    print(f"  [{'OK ' if ok else 'FAIL'}] 垃圾输入 {junk!r:.24} -> {got.text!r}")
    if not ok:
        FAILS.append(f"垃圾输入 {junk!r}")

# 请求体结构符合 Jev 规范
req = build_request(Q("adj.宏伟的", OPTS), "typesafe/jev-1.13")
check("请求含 state.question", req["state"]["question"], "adj.宏伟的")
check("请求含 questions.answer.type", req["questions"]["answer"]["type"], "choice")
check("criteria 是编号键", sorted(req["questions"]["answer"]["criteria"]),
      ["o0", "o1", "o2", "o3"])

# 未启用时不能联网
off = Config({"ai": {"enabled": False}})
check("未启用时不调用", judge(Q("adj.宏伟的", OPTS), off.ai).text, None)


# ---------------------------------------------------------------- 选项排序 / 选错项
print("\n== 选项排序与选错项 ==")
bank = load_bank()
q = Q("adj.宏伟的", ["exhibition", "painter", "grand", "additional", "kettle", "exact"])
ranked = bank.rank_options(q)
check("排序首位是正确答案", ranked[0][1] if ranked else None, "grand")

q2 = Q("harmony", ["n. 歌", "vt. 催促", "adj. 幸运的", "n.融洽相处", "n. 聚集"])
ranked2 = bank.rank_options(q2)
check("en2zh 排序首位正确", ranked2[0][1] if ranked2 else None, "n.融洽相处")

# pick_wrong 绝不能返回正确答案（那等于控分失败）
import random  # noqa: E402
from pk_bot import Runner  # noqa: E402
dummy = Runner.__new__(Runner)
dummy.bank = bank
random.seed(7)
bad = 0
for _ in range(200):
    w = dummy.pick_wrong(q, "grand")
    if w is not None and w.text == "grand":
        bad += 1
check("pick_wrong 从不选中正确答案", bad, 0)
check("pick_wrong 返回的是选项之一",
      dumb := (dummy.pick_wrong(q, "grand") is not None), True)


# ---------------------------------------------------------------- AI 答案回填闭环
print("\n== AI 答案回填（这是兜底最划算的地方）==")
import shutil  # noqa: E402
from pk_bot import LEARNED  # noqa: E402

backup = None
if LEARNED.exists():
    backup = LEARNED.read_bytes()
try:
    # 'element' 在本地词库里查不到 'n.基本部分'，属于典型的需要 AI 的题
    hard = Q("element", ["adj. 不合法的", "n.基本部分", "vt. 提取", "n. 装置", "n. 顾问"])
    before = load_bank().lookup_word(hard.gloss, hard.option_texts(), hard.pos)
    check("回填前：本地查不到", before, None)

    # 模拟 AI 给出答案后被记住
    Runner.remember(hard, "n.基本部分")

    after = load_bank().lookup_word(hard.gloss, hard.option_texts(), hard.pos)
    check("回填后：本地直接命中", after, "n.基本部分")

    # 反向（zh2en）也要能回填
    hard2 = Q("adj.某个没收录的词", ["someterm", "other", "third"])
    check("回填前 zh2en 查不到", load_bank().lookup(hard2.gloss, hard2.option_texts()), None)
    Runner.remember(hard2, "someterm")
    check("回填后 zh2en 命中",
          load_bank().lookup(hard2.gloss, hard2.option_texts()), "someterm")
finally:
    # 别把测试数据留在真实配置里
    if backup is not None:
        LEARNED.write_bytes(backup)
    elif LEARNED.exists():
        LEARNED.unlink()
print("  (已还原 data/learned.json)")

print()
if FAILS:
    print(f"失败 {len(FAILS)} 项: {FAILS}")
    sys.exit(1)
print("全部通过")
