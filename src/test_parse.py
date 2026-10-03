"""用真实抓取的屏幕样本验证 parse_screen。"""
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from pk_core import parse_screen, split_prompt  # noqa: E402

SAMPLE = pathlib.Path(__file__).resolve().parent.parent / "samples" / "raw_u4.xml"

xml = SAMPLE.read_text(encoding="utf-8", errors="replace")
q = parse_screen(xml)

assert q is not None, "解析失败"
print(f"题干   : {q.prompt!r}")
print(f"词性   : {q.pos!r}")
print(f"释义   : {q.gloss!r}")
print(f"进度   : {q.progress}")
print(f"倒计时 : {q.seconds_left}s")
print(f"选项   : {q.option_texts()}")
print(f"屏高   : {q.screen_h}")

# 断言：题干应是中文释义，选项应是纯英文
assert q.gloss and any("\u4e00" <= c <= "\u9fff" for c in q.gloss), f"题干不像中文释义: {q.prompt}"
assert len(q.options) >= 2, f"选项太少: {len(q.options)}"
for o in q.options:
    assert not any("\u4e00" <= c <= "\u9fff" for c in o.text), f"选项含中文: {o.text!r}"
    assert o.cy > q.screen_h * 0.35, f"选项 y 坐标异常: {o.text}@{o.cy}"

# split_prompt 单测
assert split_prompt("adj.宏伟的") == ("adj.", "宏伟的")
assert split_prompt("n.鹰") == ("n.", "鹰")
assert split_prompt("鹰") == (None, "鹰")
assert split_prompt("v. 使确信") == ("v.", "使确信")

print("\n[OK] parse_screen 全部断言通过")
