"""AI 兜底判定：用 Jev 的决策格式让模型在选项里挑一个。

为什么值得做：本地词库约 12% 的题判不出来（教材释义不在 ed.db 里）。
这些题原来只能猜（1/6 概率），交给 AI 能显著提高正确率。

延迟：Jev 这类决策模型实测 70-500ms 一次调用（Amplitude 独立评测），
配合 dump 的 ~3.5s，6 秒限时内来得及。

两种模式：
  chat —— 任何 OpenAI 兼容接口（DeepSeek / OpenAI / OpenRouter / 本地 Ollama），
          要求模型按 Jev 格式返回 JSON
  jev  —— 原生 Jev 决策模型（OpenRouter 的 /api/alpha/decisions）

两者返回同一种结构，所以解析只有一份：
  {"answers": {"answer": {"type": "choice", "choice": "o3", "confidence": 0.9}}}
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request

from pk_core import Question

# 用 o0/o1/... 做选项标签，比让模型原样回显英文单词更稳
_LABEL = re.compile(r"^o(\d+)$")

_INSTRUCTIONS = "选出与题面意思一致的选项"

_SYSTEM = (
    "你是一个只输出结构化决定的判定器。"
    "用户会给你一个题目和一组带编号的候选选项。"
    "你必须只输出一个 JSON 对象，不要任何解释文字，格式严格如下："
    '{"answers":{"answer":{"type":"choice","choice":"o<编号>","confidence":<0到1的小数>}}}'
)


class AIResult:
    __slots__ = ("text", "confidence", "raw")

    def __init__(self, text: str | None, confidence: float, raw: str = "") -> None:
        self.text = text
        self.confidence = confidence
        self.raw = raw

    def __repr__(self) -> str:
        return f"<AIResult {self.text!r} conf={self.confidence:.2f}>"


def build_request(q: Question, model: str) -> dict:
    """按 Jev 的 state + questions 结构组装请求体。"""
    options = q.option_texts()
    return {
        "model": model,
        "state": {
            "question": q.prompt,
            "direction": q.direction,
            "options": options,
        },
        "questions": {
            "answer": {
                "type": "choice",
                "instructions": _INSTRUCTIONS,
                "criteria": {f"o{i}": text for i, text in enumerate(options)},
            }
        },
    }


def parse_answer(payload: object, options: list[str]) -> AIResult:
    """从模型返回里取出选择。兼容 Jev 原生结构与模型直出的简化结构。"""
    raw = json.dumps(payload, ensure_ascii=False)[:400] if not isinstance(payload, str) else payload
    data = payload
    if isinstance(payload, str):
        data = _loose_json(payload)
    if not isinstance(data, dict):
        return AIResult(None, 0.0, raw)

    node = data
    answers = data.get("answers")
    if isinstance(answers, dict):
        node = answers.get("answer") or (next(iter(answers.values())) if answers else {})

    if not isinstance(node, dict):
        return AIResult(None, 0.0, raw)

    conf = node.get("confidence")
    try:
        conf = float(conf)
    except (TypeError, ValueError):
        conf = 0.0

    choice = node.get("choice")
    if choice is None:
        choice = node.get("noul") or node.get("score")

    # 优先按 o<编号> 解析
    if isinstance(choice, str):
        m = _LABEL.match(choice.strip())
        if m:
            i = int(m.group(1))
            if 0 <= i < len(options):
                return AIResult(options[i], conf, raw)
        # 模型直接把选项原文抄回来了
        if choice.strip() in options:
            return AIResult(choice.strip(), conf, raw)
    elif isinstance(choice, int) and 0 <= choice < len(options):
        return AIResult(options[choice], conf, raw)

    # 兜底：在返回里找概率最高的选项
    probs = node.get("probabilities")
    if isinstance(probs, dict) and probs:
        best, best_p = None, -1.0
        for k, v in probs.items():
            try:
                p = float(v)
            except (TypeError, ValueError):
                continue
            if p > best_p:
                best_p = p
                m = _LABEL.match(str(k).strip())
                idx = int(m.group(1)) if m else None
                if idx is not None and 0 <= idx < len(options):
                    best = options[idx]
                elif str(k).strip() in options:
                    best = str(k).strip()
        if best:
            return AIResult(best, max(best_p, conf), raw)

    return AIResult(None, conf, raw)


def _loose_json(s: str) -> object:
    """从可能夹着说明文字的输出里抠出 JSON 对象。"""
    s = s.strip()
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", s).strip()
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{.*\}", s, re.S)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            return None
    return None


def _post(url: str, payload: dict, headers: dict, timeout: float) -> object:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    for k, v in headers.items():
        req.add_header(k, v)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def judge(q: Question, cfg, timeout: float | None = None) -> AIResult:
    """判定一题。任何失败都返回 text=None，调用方照常走本地猜测。

    timeout 由调用方按"界面剩余秒数"传进来，确保不会因为等 AI 而超时。
    """
    if not getattr(cfg, "enabled", False):
        return AIResult(None, 0.0, "disabled")
    key = getattr(cfg, "api_key", "")
    if not key:
        return AIResult(None, 0.0, "no api_key")

    options = q.option_texts()
    if len(options) < 2:
        return AIResult(None, 0.0, "too few options")

    t = float(timeout if timeout is not None else getattr(cfg, "timeout", 1.8))
    t = max(0.3, min(t, 10.0))
    mode = str(getattr(cfg, "mode", "chat")).lower()

    try:
        if mode == "jev":
            url = str(getattr(cfg, "base_url", "")).rstrip("/") + "/decisions"
            payload = build_request(q, getattr(cfg, "model", "typesafe/jev-1.13"))
            out = _post(url, payload, {"Authorization": f"Bearer {key}"}, t)
            return parse_answer(out, options)

        # chat 模式：把 Jev 结构当契约塞给模型，要求原样返回 Jev 答案结构
        url = str(getattr(cfg, "base_url", "")).rstrip("/") + "/chat/completions"
        payload = {
            "model": getattr(cfg, "model", "deepseek-chat"),
            "temperature": 0,
            "max_tokens": 120,
            "messages": [
                {"role": "system", "content": _SYSTEM},
                {"role": "user",
                 "content": json.dumps(build_request(q, "-"), ensure_ascii=False)},
            ],
        }
        out = _post(url, payload, {"Authorization": f"Bearer {key}"}, t)
        if not isinstance(out, dict):
            return AIResult(None, 0.0, "bad response")
        choices = out.get("choices") or []
        content = ""
        if choices and isinstance(choices[0], dict):
            content = (choices[0].get("message") or {}).get("content") or ""
        return parse_answer(content, options)

    except urllib.error.HTTPError as e:
        return AIResult(None, 0.0, f"HTTP {e.code}")
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return AIResult(None, 0.0, f"网络: {type(e).__name__}")
    except Exception as e:  # noqa: BLE001 - 兜底绝不能影响答题
        return AIResult(None, 0.0, f"异常: {type(e).__name__}")
