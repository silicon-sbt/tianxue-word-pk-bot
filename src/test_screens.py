"""结算页/房间页误判成题目的回归测试。

实测事故（2026-10-03 18:57 那一局）：10 题答完后回到结算页，
解析器把「宋博涛」（人名）当成题干、把 'Score' 当成选项，
于是白调一次 AI，还在结算页上乱点。

这里用真实样本 + 按事故症状构造的画面锁住修复。
跑法：python -X utf8 src/test_screens.py
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))

from pk_core import parse_screen  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
SAMPLES = ROOT / "samples"

FAILS = []


def check(name: str, got, want) -> None:
    ok = got == want
    print(f"  [{'OK ' if ok else 'FAIL'}] {name}: {got!r}" + ("" if ok else f"  期望 {want!r}"))
    if not ok:
        FAILS.append(name)


def node(text: str, x1: int, y1: int, x2: int, y2: int) -> str:
    return (f'<node index="0" text="{text}" resource-id="" class="android.widget.TextView" '
            f'package="com.up366.mobile" content-desc="" checkable="false" checked="false" '
            f'clickable="false" enabled="true" focusable="false" focused="false" '
            f'scrollable="false" long-clickable="false" password="false" selected="false" '
            f'bounds="[{x1},{y1}][{x2},{y2}]" drawing-order="0" hint="" />')


def screen(*nodes: str) -> str:
    # 真实 dump 里有全屏背景节点，屏高要靠它推出来（题干判定用的是
    # 「屏幕高度 35% 以上」这个相对阈值）。少了它，合成屏幕只有几百像素高，
    # 题干就会被算到分界线以下。
    root = node("", 0, 0, 1260, 2800)
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>'
            '<hierarchy rotation="0">' + root + "".join(nodes) + "</hierarchy>")


print("== 结算页（无倒计时）必须判为 None ==")
# 事故现场：人名当题干、Score 当选项、没有倒计时
bogus = screen(
    node("宋博涛", 300, 400, 560, 480),
    node("Score: 0", 300, 480, 560, 560),
    node("陈汝媛", 800, 400, 1060, 480),
    node("Score: 8", 800, 480, 1060, 560),
    node("Score", 300, 1000, 600, 1100),
    node("宋博涛", 200, 1200, 500, 1300),
    node("陈汝媛", 700, 1200, 1000, 1300),
)
check("结算页 -> None", parse_screen(bogus), None)

print("\n== 有倒计时但选项数异常，也必须判为 None ==")
# 房间页的花名册：几十个名字 + 一个倒计时残留
roster = [node("4s", 540, 360, 766, 584)]
for i in range(20):
    roster.append(node(f"同学{i}", 385, 1200 + i * 10, 1032, 1260 + i * 10))
check("选项过多 -> None", parse_screen(screen(*roster)), None)

print("\n== 真实答题页不能被误杀 ==")
real = screen(
    node("1 / 130", 532, 189, 745, 262),
    node("4s", 542, 360, 766, 584),
    node("adj.宏伟的", 339, 689, 920, 843),
    node("exhibition", 126, 1102, 574, 1281),
    node("painter", 203, 1200, 546, 1379),
    node("grand", 672, 1300, 1022, 1482),
    node("additional", 742, 1400, 1130, 1575),
    node("kettle", 133, 1500, 535, 1678),
    node("exact", 717, 1600, 1109, 1779),
)
q = parse_screen(real)
check("真实答题页能解析", q is not None, True)
if q:
    check("  题干", q.prompt, "adj.宏伟的")
    check("  选项数", len(q.options), 6)
    check("  倒计时", q.seconds_left, 4)

print("\n== 实机抓屏样本 ==")
expect_none = {"cap_1790996726_0", "cap_1790996729_1", "cap_1790996733_2",
               "cap_1790996736_3", "cap_1790996739_4", "cap_1790996742_5",
               "live2", "raw_u5"}
for f in sorted(SAMPLES.glob("*.xml")):
    if f.suffix == ".py":
        continue
    q = parse_screen(f.read_bytes())
    stem = f.stem
    if stem in expect_none:
        check(f"{f.name} -> None", q, None)
    else:
        check(f"{f.name} 有解析结果", q is not None, True)

print()
if FAILS:
    print(f"失败 {len(FAILS)} 项: {FAILS}")
    sys.exit(1)
print("全部通过")
