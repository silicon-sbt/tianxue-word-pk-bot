"""修复被压扁的 Python 缩进。

压缩规律：原来的缩进层被压成 1 空格/层（我的正则把连续空格压成一个）。
还原：按「行首空格数」乘回 N，N 取原标准的倍数。

难点：原文件 4 空格缩进，压扁后 1 空格/层 -> 乘 4 即还原。
先检测最小非零缩进，再统一放大。
"""
import pathlib
import re

ROOT = pathlib.Path(r"E:\code\单词pk")


def detect_unit(lines: list[str]) -> int:
    """检测最小非零行首空格数。"""
    units = set()
    for ln in lines:
        if not ln.strip():
            continue
        lead = len(ln) - len(ln.lstrip(" "))
        if lead > 0:
            units.add(lead)
    return min(units) if units else 1


def fix(path: pathlib.Path) -> bool:
    text = path.read_text(encoding="utf-8")
    lines = text.split("\n")
    unit = detect_unit(lines)
    if unit != 1:
        print(f"  {path.name}: 最小缩进 {unit}，可能未损坏，跳过")
        return False

    out = []
    for ln in lines:
        if not ln.strip():
            out.append("")
            continue
        lead = len(ln) - len(ln.lstrip(" "))
        out.append(" " * (lead * 4) + ln.lstrip(" "))
    path.write_text("\n".join(out), encoding="utf-8")
    print(f"  {path.name}: 缩进 x4 还原")
    return True


if __name__ == "__main__":
    targets = list((ROOT / "app").glob("*.py")) + list((ROOT / "tools").glob("*.py"))
    for p in targets:
        try:
            fix(p)
        except Exception as e:  # noqa: BLE001
            print(f"  {p.name}: 失败 {e}")
