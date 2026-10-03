"""双向判定评估：用真实抓屏数据检验 zh2en 与 en2zh 两条路径。"""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from pk_core import Question, Option, WordBank, resolve, split_prompt  # noqa: E402

BANK = pathlib.Path(__file__).resolve().parent.parent / "data" / "wordbank.json"


def load() -> WordBank:
    bank = WordBank()
    data = json.loads(BANK.read_text(encoding="utf-8"))
    for word, senses in data["words"].items():
        bank.words.add(word)
        for gloss, pos in senses:
            bank.add_sense(word, gloss, pos or None)
            bank.by_gloss.setdefault(gloss.strip().lower(), set()).add(word)
    return bank


def Q(prompt, options):
    pos, gloss = split_prompt(prompt)
    return Question(prompt=prompt, pos=pos, gloss=gloss,
                    options=[Option(t, 0, 0) for t in options], screen_h=2800)


# ---- 全部来自真实抓屏 ----
CASES = [
    # zh2en：题干中文，选项英文
    ("adj.宏伟的", ["exhibition", "painter", "grand", "additional", "kettle", "exact"], "grand"),
    ("adj.活的", ["complex", "living", "dollar", "format", "analyst", "ensure"], "living"),
    ("n.鹰", ["inspire", "eagle", "comb", "exactly", "France", "match"], "eagle"),
    ("v.破坏", ["school", "mechanic", "compete", "destroy", "weed", "goal"], "destroy"),
    # en2zh：题干英文，选项中文
    ("harmony", ["n. 歌", "vt. 催促", "adj. 幸运的", "n.融洽相处", "n. 聚集", "n. 沉渣"], "n.融洽相处"),
]


def main() -> None:
    bank = load()
    ok = 0
    for prompt, opts, want in CASES:
        q = Q(prompt, opts)
        got = resolve(q, bank)
        mark = "OK " if got == want else "MISS"
        if got == want:
            ok += 1
        print(f"[{mark}] [{q.direction}] {prompt!r:14} 期望={want!r:16} 判定={got!r}")
    print(f"\n准确率: {ok}/{len(CASES)}")

    print("\n-- harmony 义项 --")
    print(" ", bank.senses_of("harmony"))
    print("-- destroy 义项 --")
    print(" ", bank.senses_of("destroy"))


if __name__ == "__main__":
    main()
