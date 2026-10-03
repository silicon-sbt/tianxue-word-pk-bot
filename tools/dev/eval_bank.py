"""离线评估：用真实 PK 题目检验词库判定准确率。"""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from pk_core import WordBank, sense_similarity  # noqa: E402

BANK = pathlib.Path(r"E:\code\单词pk\data\wordbank.json")


def load() -> WordBank:
    bank = WordBank()
    data = json.loads(BANK.read_text(encoding="utf-8"))
    for word, senses in data["words"].items():
        bank.words.add(word)
        for gloss, pos in senses:
            bank.add_sense(word, gloss, pos or None)
    return bank


# (题干, 词性, 选项, 正确答案)  —— 全部来自真实抓屏
CASES = [
    ("宏伟的", "adj.", ["exhibition", "painter", "grand", "additional", "kettle", "exact"], "grand"),
    ("活的", "adj.", ["complex", "living", "dollar", "format", "analyst", "ensure"], "living"),
    ("鹰", "n.", ["inspire", "eagle", "comb", "exactly", "France", "match"], "eagle"),
]


def main() -> None:
    bank = load()
    ok = 0
    for gloss, pos, opts, want in CASES:
        ranked = bank.score_options(gloss, opts, pos)
        got = bank.lookup(gloss, opts, pos)
        mark = "OK " if got == want else "MISS"
        if got == want:
            ok += 1
        print(f"[{mark}] {pos}{gloss}  期望={want}  判定={got}")
        for sc, w in ranked[:4]:
            print(f"        {sc:.2f}  {w}" + ("   <-- 期望" if w == want else ""))
        print()
    print(f"准确率: {ok}/{len(CASES)}")

    # 相似度单测
    print("\n-- 相似度 --")
    for a, b in [("宏伟的", "雄伟的"), ("宏伟的", "壮丽的"),
                 ("活的", "活着的"), ("鹰", "雕"), ("鹰", "组合")]:
        print(f"  {a} vs {b} = {sense_similarity(a,b):.2f}")


if __name__ == "__main__":
    main()
