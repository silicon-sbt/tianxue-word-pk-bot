"""回归测试：全部来自实机抓屏的真实题目，防止改动把已对的改坏。

每次实打遇到的新题都应该补进来。
"""
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


# (题干, 选项, 正确项)  —— 全部为实机抓屏所见
CASES = [
    # --- 早期抓屏 ---
    ("adj.宏伟的", ["exhibition", "painter", "grand", "additional", "kettle", "exact"], "grand"),
    ("adj.活的", ["complex", "living", "dollar", "format", "analyst", "ensure"], "living"),
    ("n.鹰", ["inspire", "eagle", "comb", "exactly", "France", "match"], "eagle"),
    ("v.破坏", ["school", "mechanic", "compete", "destroy", "weed", "goal"], "destroy"),
    ("harmony", ["n. 歌", "vt. 催促", "adj. 幸运的", "n.融洽相处", "n. 聚集", "n. 沉渣"], "n.融洽相处"),
    ("v.使可能", ["enable", "school", "weed", "goal", "kettle", "less"], "enable"),
    # --- 首次实打（live run）实际遇到并答对的题 ---
    ("photographer", ["n. 摄影师", "n. 蔬菜", "vt. 庆祝", "n. 悲剧"], "n. 摄影师"),
    ("v.阻挡", ["prevent", "register", "statue", "elderly", "clear", "help"], "prevent"),
    ("n.无线网络", ["Wi-Fi", "shoe", "translate", "midday", "less", "help"], "Wi-Fi"),
    ("barrier", ["n. 障碍", "n. 锅", "v. 恢复", "n. 习语"], "n. 障碍"),
    ("n.锅", ["pot", "barrier", "measure", "idiom", "help", "less"], "pot"),
    ("recover", ["v. 恢复", "n. 障碍", "n. 习作", "v. 阻挡"], "v. 恢复"),
    ("idiom", ["n. 习语", "n. 锅", "n. 无线网络", "v. 恢复"], "n. 习语"),
    ("measure", ["v. 量", "n. 习语", "v. 阻挡", "n. 障碍"], "v. 量"),
    # --- 曾失败的题（教材释义与词典不同源），修复后应通过 ---
    ("adj.异常的", ["register", "statue", "clear", "unusual", "elderly", "originality"], "unusual"),
    # --- 第2局实打遇到的题 ---
    ("narrow", ["adj.狭窄的", "n.材料", "v.保持", "n.好处"], "adj.狭窄的"),
    ("n.克", ["gram", "valley", "material", "anxious"], "gram"),
    ("n.谷", ["valley", "gram", "basin", "benefit"], "valley"),
    ("material", ["n.材料", "adj.狭窄的", "v.保持", "n.盆地"], "n.材料"),
    ("adj.焦虑的", ["anxious", "benefit", "basin", "plain"], "anxious"),
    ("maintain", ["v.保持", "n.材料", "n.好处", "n.盆地"], "v.保持"),
    ("n.好处", ["benefit", "basin", "valley", "gram"], "benefit"),
    ("n.盆地", ["basin", "benefit", "valley", "plain"], "basin"),
    ("n.习语", ["idiom", "postpone", "patience", "wrap"], "idiom"),
    ("postpone", ["v.使延期", "n.耐心", "v.包", "n.素质"], "v.使延期"),
    ("patience", ["n.耐心", "n.素质", "v.包", "n.鲸"], "n.耐心"),
    ("wrap", ["v.包", "n.鲸", "n.素质", "n.耐心"], "v.包"),
    ("quality", ["n.素质", "n.鲸", "v.包", "n.耐心"], "n.素质"),
    ("whale", ["n.鲸", "n.素质", "v.包", "n.耐心"], "n.鲸"),
    ("adj.简单的", ["plain", "river", "update", "joint"], "plain"),
    ("n.住处", ["accommodation", "river", "update", "classic"], "accommodation"),
    ("recover", ["v.恢复", "n.障碍", "n.习作", "v.阻挡"], "v.恢复"),
    ("adv.永远", ["forever", "river", "considerate", "joint"], "forever"),
    ("n.无线网络", ["Wi-Fi", "river", "update", "classic"], "Wi-Fi"),
    ("prove", ["v.证明", "n.商品", "n.素质", "n.耐心"], "v.证明"),
    ("goods", ["n.商品", "v.证明", "n.耐心", "n.鲸"], "n.商品"),
    # --- 误判回归：这两题算法本来是对的（1.00 / 0.75），
    #     当时是读到了切题瞬间的混合画面。这里锁定判定结果不许退化。 ---
    ("shock", ["vi. & vt. 游泳", "n. 震惊", "adj. 焦虑的", "n. 材料", "v. 保持", "n. 好处"], "n. 震惊"),
    ("tend", ["vi. & vt.举起", "v. 倾向", "n. 素质", "n. 鲸", "v. 包", "n. 耐心"], "v. 倾向"),
    # --- 误判回归：run4 实测 'n.图像' 被答成 resemble（因 key '像' 是 '图像' 的单字子串）。
    #     修好后 image/picture 并列 0.45，算法应判定「不确定」返回 None（转猜），
    #     绝不能再返回 resemble。这里断言的就是「不能是 resemble」。 ---
    ("n.图像", ["image", "resemble", "picture", "scene", "structure", "advance"], None),
]


def main() -> None:
    bank = load()
    ok = 0
    fails = []
    for prompt, opts, want in CASES:
        q = Q(prompt, opts)
        got = resolve(q, bank)
        if got == want:
            ok += 1
            print(f"[OK ] [{q.direction}] {prompt!r:16} -> {got!r}")
        else:
            fails.append((prompt, want, got))
            print(f"[MISS] [{q.direction}] {prompt!r:16} 期望={want!r} 实得={got!r}")
    print(f"\n准确率: {ok}/{len(CASES)} = {ok/len(CASES)*100:.0f}%")
    if fails:
        print("\n失败项:")
        for f in fails:
            print(f"  {f[0]!r} 期望 {f[1]!r} 实得 {f[2]!r}")
        sys.exit(1)


if __name__ == "__main__":
    main()
