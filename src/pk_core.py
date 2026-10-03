"""天学网单词PK — 核心：读题 / 判定答案 / 决定点击。

职责分离：
  - parse_screen(): UI XML -> Question（题目 + 选项 + 坐标）
  - resolve_answer(): Question -> 答案选项（本地词库，离线）
  - 点击由调用方执行（保持 core 可单测）

设计约束：
  - 纯离线判定，不依赖网络（PK 有 5s 倒计时，网络往返太慢）
  - UI XML 直接解析，不做 OCR（实测题目文本在无障碍树里）
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Iterable

# 题目节点在屏幕顶部，选项节点在下方。
# 实测 1260x2800：题目 y≈766，选项 y≈1192~2264。
# 用相对阈值而不是硬编码像素，适配不同分辨率。
QUESTION_Y_RATIO = 0.35

# 排除的 UI 文本（进度/计时/比分）
_NOISE = re.compile(
    r"^(\d+\s*/\s*\d+|\d+s|Score:\s*\d+|Total:\s*\d+|Accuracy:\s*\d+%|"
    r"用时:.*|PK.*|.*计分赛|.*个)$"
)


@dataclass
class Option:
    text: str
    cx: int
    cy: int
    w: int = 0
    h: int = 0

    @property
    def bbox(self) -> tuple[int, int, int, int]:
        return (self.cx - self.w // 2, self.cy - self.h // 2,
                self.cx + self.w // 2, self.cy + self.h // 2)


@dataclass
class Question:
    prompt: str                      # 题干原文，如 "adj.宏伟的" 或 "harmony"
    pos: str | None                  # 词性，如 "adj."
    gloss: str                       # 去掉词性后的题干，如 "宏伟的" / "harmony"
    options: list[Option] = field(default_factory=list)
    screen_h: int = 0
    progress: tuple[int, int] | None = None
    seconds_left: int | None = None

    def option_texts(self) -> list[str]:
        return [o.text for o in self.options]

    @property
    def direction(self) -> str:
        """'zh2en' 题干中文选英文；'en2zh' 题干英文选中文。"""
        return "en2zh" if _is_ascii_word(self.gloss) else "zh2en"


def _is_ascii_word(s: str) -> bool:
    """题干是否是英文单词/短语（不含中文）。"""
    if not s:
        return False
    if any("\u4e00" <= c <= "\u9fff" for c in s):
        return False
    return bool(re.search(r"[A-Za-z]", s))



def _parse_bounds(node: ET.Element) -> tuple[int, int, int, int] | None:
    raw = node.get("bounds")
    if not raw:
        return None
    m = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", raw)
    if not m:
        return None
    return tuple(int(g) for g in m.groups())  # type: ignore[return-value]


def _iter_nodes(root: ET.Element) -> Iterable[ET.Element]:
    yield root
    for child in root:
        yield from _iter_nodes(child)


def decode_dump(data: bytes | str) -> str:
    """把 uiautomator dump 的原始内容解码成 str。

    实测坑：`adb shell cat` 在本机返回 UTF-16LE（每个 ASCII 字符后跟一个 NUL），
    按 UTF-8 硬解会得到带 \\x00 的乱码，所有 text="..." 都匹配不到。
    """
    if isinstance(data, bytes):
        if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
            s = data.decode("utf-16", "replace")
        elif len(data) > 8 and data[1:2] == b"\x00" and data[3:4] == b"\x00":
            s = data.decode("utf-16-le", "replace")
        else:
            s = data.decode("utf-8", "replace")
    else:
        s = data

    # 已是 str 但带大量 NUL：\x00 插在字符之间
    if s.count("\x00") > len(s) * 0.2:
        try:
            s = s.encode("latin-1", "ignore").decode("utf-16-le", "replace")
        except (UnicodeDecodeError, UnicodeEncodeError):
            s = s.replace("\x00", "")
    return s


def parse_screen(xml_text: str | bytes) -> Question | None:
    """把 uiautomator dump 的 XML 解析成 Question。解析不出题目返回 None。"""
    xml_text = decode_dump(xml_text)
    # BOM / 残留 NUL 清理，ElementTree 会直接抛 ParseError
    xml_text = xml_text.replace("\x00", "").lstrip("\ufeff\ufffe").strip()
    if not xml_text:
        return None
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        # 退化路径：切出第一个 <hierarchy ...> 元素再试
        m = re.search(r"<hierarchy\b.*</hierarchy>", xml_text, re.S)
        if not m:
            return None
        try:
            root = ET.fromstring(m.group(0))
        except ET.ParseError:
            return None

    screen_h = 0
    b = _parse_bounds(root)
    if b:
        screen_h = b[3]
    if not screen_h:
        # 根 <hierarchy> 常无 bounds：取所有节点 y2 的最大值作为屏高
        screen_h = max(
            (bb[3] for n in _iter_nodes(root) if (bb := _parse_bounds(n))),
            default=0,
        )
    if not screen_h:
        return None

    prompt_node: tuple[str, int, int, int, int] | None = None
    raw_options: list[Option] = []
    progress = None
    seconds_left = None

    for node in _iter_nodes(root):
        text = (node.get("text") or "").strip()
        bounds = _parse_bounds(node)
        if not bounds:
            continue
        x1, y1, x2, y2 = bounds
        w, h = x2 - x1, y2 - y1
        if w <= 0 or h <= 0:
            continue
        cx, cy = (x1 + x2) // 2, (y1 + y2) // 2

        if not text:
            continue

        m = re.match(r"^(\d+)\s*/\s*(\d+)$", text)
        if m:
            progress = (int(m.group(1)), int(m.group(2)))
            continue
        if re.match(r"^\d+s$", text):
            seconds_left = int(text[:-1])
            continue
        if _NOISE.match(text):
            continue

        # 题目：位于屏幕上半部，通常是中文释义或 "词性.释义"
        if cy < screen_h * QUESTION_Y_RATIO:
            # 取最大的那个节点作为题干（避开顶部比分栏里的小字）
            if prompt_node is None or w * h > prompt_node[3] * prompt_node[4]:
                prompt_node = (text, cx, cy, w, h)
            continue

        raw_options.append(Option(text=text, cx=cx, cy=cy, w=w, h=h))

    if prompt_node is None or not raw_options:
        return None

    # 去重：题目切换瞬间 dump 会把新旧两题的选项混在一起（实测出现过 7 个且末项重复）。
    # 同文本只保留第一个（坐标更新的那个通常是新题）。
    dedup: list[Option] = []
    seen: set[str] = set()
    for o in raw_options:
        k = o.text.strip()
        if k in seen:
            continue
        seen.add(k)
        dedup.append(o)
    raw_options = dedup

    prompt = prompt_node[0]
    pos, gloss = split_prompt(prompt)

    return Question(
        prompt=prompt,
        pos=pos,
        gloss=gloss,
        options=raw_options,
        screen_h=screen_h,
        progress=progress,
        seconds_left=seconds_left,
    )


_PROMPT_RE = re.compile(r"^\s*([a-zA-Z]+\.)\s*(.+?)\s*$")

# 'vi. & vt.举起' / 'vi.&vt. 举起' 这类复合词性前缀
_MULTI_POS_RE = re.compile(
    r"^\s*((?:[a-zA-Z]+\.\s*(?:&\s*)?)+)\s*(.+?)\s*$"
)


def split_prompt(prompt: str) -> tuple[str | None, str]:
    """'adj.宏伟的' -> ('adj.', '宏伟的')；'鹰' -> (None, '鹰')

    实测坑：选项里会出现复合词性前缀，如 'vi. & vt.举起'、'vi.&vt. 举起'。
    只剥离「词性 + 可选连字符」这一段，且必须后面还有释义，否则会把
    'vt. & vi.' 整段吃掉、留下 '&' 这种垃圾。
    """
    m = _MULTI_POS_RE.match(prompt)
    if m:
        pos_part = re.sub(r"\s+", "", m.group(1))
        gloss = m.group(2).strip()
        if gloss and re.search(r"[\u4e00-\u9fff]", gloss):
            return pos_part.lower(), gloss
    m = _PROMPT_RE.match(prompt)
    if m:
        return m.group(1).lower(), m.group(2)
    return None, prompt.strip()



# ---------------------------------------------------------------- 答案判定

def _normalize(s: str) -> str:
    return re.sub(r"[\s\-_]+", "", s.strip().lower())


class WordBank:
    """离线词库：中文释义 -> 英文单词。

    支持一个释义对应多个单词（同义词），判定时取「在选项中且匹配度最高」的。
    """

    def __init__(self) -> None:
        # gloss -> set(words)
        self.by_gloss: dict[str, set[str]] = {}
        self.words: set[str] = set()
        # word -> [(gloss, pos)]  反向打分用
        self._senses: dict[str, list[tuple[str, str | None]]] = {}

    def add(self, word: str, gloss: str, pos: str | None = None) -> None:
        w = _normalize(word)
        if not w:
            return
        self.words.add(w)
        for g in _split_glosses(gloss):
            key = _normalize(g)
            if key:
                self.by_gloss.setdefault(key, set()).add(w)
        if pos:
            key = _normalize(gloss)
            if key:
                self.by_gloss.setdefault(key, set()).add(w)

    def __len__(self) -> int:
        return len(self.words)

    def lookup(self, gloss: str, options: list[str], pos: str | None = None) -> str | None:
        """在 options 中找出 gloss 对应的单词。返回选项原文，找不到返回 None。

        保守原则：拿不准就返回 None（跳过这题），绝不给「可能错」的答案——
        误判比漏答严重得多。
        """
        norm_gloss = _normalize(gloss)
        opt_map = {_normalize(o): o for o in options}

        # 1) 精确命中：唯一可靠，直接返回
        hit = self.by_gloss.get(norm_gloss)
        if hit:
            for w in hit:
                if w in opt_map:
                    return opt_map[w]

        # 2) 包含匹配：收集所有候选，按匹配长度取最优。
        #    实测坑：key '像'（resemble）是 norm_gloss '图像' 的子串，
        #    会被当成唯一候选直接返回，导致 '图像' 答成 resemble。
        #    因此要求「较短的那个至少 2 个字」，单字子串不算匹配。
        cands: dict[str, int] = {}
        for key, words in self.by_gloss.items():
            if not key or len(key) < 2:
                continue
            if key in norm_gloss or norm_gloss in key:
                if min(len(key), len(norm_gloss)) < 2:
                    continue
                score = min(len(key), len(norm_gloss))
                for w in words:
                    if w in opt_map and score > cands.get(w, 0):
                        cands[w] = score
        if len(cands) == 1:
            return opt_map[next(iter(cands))]
        if len(cands) > 1:
            best_len = max(cands.values())
            top = [w for w, s in cands.items() if s == best_len]
            if len(top) == 1:
                return opt_map[top[0]]
            # 多个并列 -> 不确定，落到第 3 步打分

        # 3) 反向打分：拿「选项里每个词」的全部释义，与题干比相似度，取最高分。
        #    这是应对「教材释义 ≠ 词典释义」的关键手段。
        scored = self.score_options(gloss, options, pos)
        if not scored:
            return None

        top_score, top_word = scored[0]
        second = scored[1][0] if len(scored) > 1 else 0.0

        # 3a) 绝对达标
        if top_score >= self.MIN_SCORE:
            return top_word
        # 3b) 分数不高但「明显领先第二名」时也可信
        #     （如 宏伟的 vs 雄伟的 只有 0.45，但其余候选全是 0）
        if top_score >= self.MIN_MARGIN_SCORE and top_score - second >= self.MIN_MARGIN:
            return top_word
        return None

    # 反向打分的接受阈值（相似度）
    MIN_SCORE = 0.55
    # 领先判定：第一名至少这么高，且比第二名高出这么多
    MIN_MARGIN_SCORE = 0.30
    MIN_MARGIN = 0.20

    def score_options(self, gloss: str, options: list[str],
                      pos: str | None = None) -> list[tuple[float, str]]:
        """对每个选项词，用它的全部释义与题干算相似度，降序返回 [(score, 选项原文)]。"""
        out: list[tuple[float, str]] = []
        for opt in options:
            senses = self.senses_of(_normalize(opt))
            if not senses:
                continue
            best = 0.0
            for sense_gloss, sense_pos in senses:
                s = _sense_score(gloss, sense_gloss, pos, sense_pos)
                best = max(best, s)
            if best > 0:
                out.append((best, opt))
        out.sort(key=lambda t: -t[0])
        return out

    def add_sense(self, word: str, gloss: str, pos: str | None = None) -> None:
        """登记一个词的义项，用于反向打分。"""
        w = _normalize(word)
        self._senses.setdefault(w, []).append((gloss.strip(), pos))

    def senses_of(self, word: str) -> list[tuple[str, str | None]]:
        return self._senses.get(_normalize(word), [])

    # ------------------------------------------------ en2zh：题干英文，选项中文
    def lookup_word(self, word: str, options: list[str], pos: str | None = None) -> str | None:
        """题干是英文单词时，在中文选项里找它对应的释义。返回选项原文。"""
        senses = self.senses_of(word)
        if not senses:
            return None

        # 1) 选项文本与义项精确/包含匹配
        best: tuple[float, str] | None = None
        for opt in options:
            o = opt.strip()
            o_pos, o_gloss = split_prompt(o)
            for gloss, sp in senses:
                score = sense_similarity(o_gloss, gloss)
                if pos and sp and o_pos and pos == o_pos:
                    score = min(1.0, score * 1.35)
                # 完全包含时给足分
                if _normalize(gloss) in _normalize(o_gloss) or \
                   _normalize(o_gloss) in _normalize(gloss):
                    score = max(score, 0.9)
                if score > 0 and (best is None or score > best[0]):
                    best = (score, opt)
        if best and best[0] >= self.MIN_SCORE:
            return best[1]
        if best and best[0] >= self.MIN_MARGIN_SCORE:
            # 只有一个候选有分时才接受（保守：有并列就不猜）
            others = [o for o in options
                      if o != best[1] and self._best_sense_score(o, senses, pos) > 0]
            if not others:
                return best[1]
        return None

    def _best_sense_score(self, opt: str, senses, pos: str | None) -> float:
        _, o_gloss = split_prompt(opt.strip())
        b = 0.0
        for gloss, sp in senses:
            s = sense_similarity(o_gloss, gloss)
            if pos and sp and pos == sp:
                s = min(1.0, s * 1.35)
            b = max(b, s)
        return b




def _sense_score(gloss: str, sense_gloss: str,
                 pos: str | None, sense_pos: str | None) -> float:
    """单条义项打分：相似度 + 词性加权。

    针对实测误判 'n.图像' -> resemble（义项仅 '像'，单字）：
    单字义项与双字题干的重合属于「子串巧合」，不是语义相同。
    这里对「义项只有 1 个实义字、而题干有 2+ 字」的情况降权，
    但**不动全局相似度公式**——那样会连带压低正确项（实测会丢 3 题）。
    """
    s = sense_similarity(gloss, sense_gloss)
    if s <= 0:
        return 0.0

    n_sense = len(_chars(sense_gloss))
    n_gloss = len(_chars(gloss))
    if n_sense == 1 and n_gloss >= 2:
        s *= 0.5          # 单字义项对多字题干：可信度减半
    elif n_sense == 1 and n_gloss == 1:
        s *= 0.8

    # 词性一致时加权（题干 'adj.宏伟的' 优先 adj 义项）
    if pos and sense_pos and pos == sense_pos:
        s = min(1.0, s * 1.35)
    return s


def _split_glosses(gloss: str) -> list[str]:
    """'宏伟的；壮丽的' -> ['宏伟的', '壮丽的']"""
    parts = re.split(r"[;；,，/、]", gloss)
    return [p.strip() for p in parts if p.strip()]


def resolve(q: "Question", bank: "WordBank") -> str | None:
    """统一入口：按题型方向判定答案，返回应点击的选项原文。"""
    if q.direction == "en2zh":
        return bank.lookup_word(q.gloss, q.option_texts(), q.pos)
    return bank.lookup(q.gloss, q.option_texts(), q.pos)



# ------------------------------------------------------------ 高中词表适配
# PK 题干用的是教材释义（'宏伟的'），而通用词典写的是近义词（'雄伟的'）。
# 这两者字面不同但语义相同，靠精确查表必然漏。用「汉字集合重合度」兜底。
_STOP = set("的地得了着之其一二三很非常个把被使等以及")


def _chars(s: str) -> set[str]:
    return {c for c in s if "\u4e00" <= c <= "\u9fff"} - _STOP


def sense_similarity(a: str, b: str) -> float:
    """中文释义相似度 [0,1]。用 Jaccard + 包含关系 + 同义字表。

    实测三类难题：
      1) '宏伟的' vs '雄伟的'  -> 共享'伟'字，靠 margin 规则救回
      2) '异常的' vs '不寻常的' -> 汉字零交集，靠同义词归一化
      3) **陷阱**：'像' vs '图像' -> '像' 是 '图像' 的子串，旧实现给 0.75，
         导致 resemble（像）压过 image（影像/形象），实测造成误判。
         修正：短释义（≤1 个实义字）做包含匹配时**不给加成**，
         因为单字与双字词的子串关系没有语义必然性。
    """
    ca, cb = _chars(a), _chars(b)
    if not ca or not cb:
        return 0.0

    na, nb = _synonym_normalize(a), _synonym_normalize(b)
    ca2, cb2 = _chars(na), _chars(nb)
    if ca2 and cb2:
        ca, cb = ca2, cb2

    inter = len(ca & cb)
    if inter == 0:
        return 0.0
    jac = inter / len(ca | cb)

    # 包含关系加成：'活的' ⊂ '活的，有生命的' 这类才算。
    # 但单字释义（如 '像'、'雕'）不享受加成——它对任何含该字的词都会命中。
    shorter = min(len(ca), len(cb))
    if shorter >= 2 and (ca <= cb or cb <= ca):
        jac = max(jac, 0.75)
    return jac



# 教材释义 vs 通用词典释义 的常见用词差异。
# 这两套词表不同源（PK 用教材版，ed.db 是通用版），必须人工搭桥。
# 只收「实测/明显」的同义替换，不猜。
_SYNONYM_MAP = {
    "异常": "不寻常", "反常": "不寻常", "奇特": "不寻常",
    "寻常": "普通", "平常": "普通", "一般": "普通",
    "宏伟": "雄伟", "壮丽": "雄伟", "宏大": "雄伟",
    "巨大": "庞大", "宏大": "庞大",
    "快速": "迅速", "飞快": "迅速",
    "高兴": "快乐", "愉快": "快乐",
    "悲伤": "难过", "伤心": "难过",
    "美丽": "漂亮", "好看": "漂亮",
    "聪明": "伶俐", "机敏": "伶俐",
    "困难": "艰难", "艰苦": "艰难",
    "害怕": "恐惧", "惊恐": "恐惧",
    "生气": "愤怒", "恼怒": "愤怒",
    "明白": "理解", "懂得": "理解",
    "使用": "利用", "采用": "利用",
    "增加": "增多", "增长": "增多",
    "减少": "降低", "削减": "降低",
    "开始": "着手", "开端": "着手",
    "结束": "完毕", "终止": "完毕",
    "方法": "办法", "方式": "办法",
    "重要": "重大", "关键": "重大",
    "明显": "显著", "显然": "显著",
    "完全": "彻底", "十分": "彻底",
    "立刻": "马上", "立即": "马上",
    "也许": "可能", "大概": "可能",
    "但是": "然而", "可是": "然而",
    "因此": "所以", "因而": "所以",
    "虽然": "尽管", "即使": "尽管",
}

# 归一化时忽略的虚词/修饰字（'不' 会把 '不寻常的' 与 '寻常的' 混同，保留它）
_SYN_STOP = set("的地得了着之其很非常个把被使等以及")


def _synonym_normalize(s: str) -> str:
    """把释义里的用词替换成统一说法，让不同词表的同义词能对上。"""
    out = s
    # 长词优先，避免 '异常' 被 '常' 之类的短键误伤
    for k in sorted(_SYNONYM_MAP, key=len, reverse=True):
        if k in out:
            out = out.replace(k, _SYNONYM_MAP[k])
    return out


