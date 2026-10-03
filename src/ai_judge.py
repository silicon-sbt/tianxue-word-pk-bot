"""AI 兜底判定：用 Jev 的决策格式让模型在选项里挑一个。

为什么值得做：本地词库约 12% 的题判不出来（教材释义不在 ed.db 里）。
这些题原来只能猜（1/6 概率），交给 AI 能显著提高正确率。

延迟：Jev 这类决策模型实测 70-500ms 一次调用（也有本机实测 269ms 的记录），
配合读屏的 ~3.5s，6 秒限时内来得及。

两种模式：
  jev  —— TypeSafe 官方接口 POST https://api.typesafe.ai/v1/systemone
  chat —— 任何 OpenAI 兼容接口（DeepSeek / OpenAI / 本地 Ollama），
          要求模型按 Jev 格式返回 JSON

两种模式返回同一种结构，所以解析只有一份：
  {"answers": {"answer": {"type": "choice", "choice": "o3", "confidence": 0.9}}}

【本机实测的坑】api.typesafe.ai 的 DNS 被污染成 28.0.1.x（假地址），
直连必然连接重置。所以先走正常请求，网络层一失败就改走 DoH 查真 IP +
直连（SNI 与 Host 仍用真域名）。这一步不做的话在这台机器上根本连不上。
"""
from __future__ import annotations

import http.client
import json
import re
import socket
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request

from pk_core import Question

# 用 o0/o1/... 做选项标签，比让模型原样回显英文单词更稳
_LABEL = re.compile(r"^o(\d+)$")

# 单次 DoH 查询上限。不能给大：这是备用路径，不该吃掉答题预算。
_DOH_TIMEOUT = 2.0

_INSTRUCTIONS = "选出与题面意思一致的选项"

_SYSTEM = (
    "你是一个只输出结构化决定的判定器。"
    "用户会给你一个题目和一组带编号的候选选项。"
    "你必须只输出一个 JSON 对象，不要任何解释文字，格式严格如下："
    '{"answers":{"answer":{"type":"choice","choice":"o<编号>","confidence":<0到1的小数>}}}'
)

# TypeSafe 官方端点
TYPESAFE_ENDPOINT = "https://api.typesafe.ai/v1/systemone"

# DoH 解析（用于绕过本机 DNS 污染）
_DOH = [
    "https://dns.google/resolve?name={host}&type=A",
    "https://cloudflare-dns.com/dns-query?name={host}&type=A",
]
# DoH 也查不到时的兜底。IP 会变，仅作最后手段。
_IP_FALLBACK = {
    "api.typesafe.ai": ["44.227.31.201", "100.20.85.248"],
}
_ip_cache: dict[str, list[str]] = {}


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


# ------------------------------------------------------------------ 解析

def parse_answer(payload: object, options: list[str]) -> AIResult:
    """从模型返回里取出选择。兼容 Jev 原生结构与模型直出的简化结构。"""
    raw = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
    raw = raw[:400]
    data = payload if not isinstance(payload, str) else _loose_json(payload)
    if not isinstance(data, dict):
        return AIResult(None, 0.0, raw)

    node = data
    answers = data.get("answers")
    if isinstance(answers, dict):
        node = answers.get("answer")
        if node is None and answers:
            node = next(iter(answers.values()))
    if not isinstance(node, dict):
        return AIResult(None, 0.0, raw)

    try:
        conf = float(node.get("confidence"))
    except (TypeError, ValueError):
        conf = 0.0

    choice = node.get("choice")
    if choice is None:
        choice = node.get("noul") if node.get("noul") is not None else node.get("score")

    if isinstance(choice, str):
        m = _LABEL.match(choice.strip())
        if m:
            i = int(m.group(1))
            if 0 <= i < len(options):
                return AIResult(options[i], conf, raw)
        if choice.strip() in options:
            return AIResult(choice.strip(), conf, raw)
    elif isinstance(choice, int) and 0 <= choice < len(options):
        return AIResult(options[choice], conf, raw)

    # 兜底：概率分布里最高的那个
    probs = node.get("probabilities")
    if isinstance(probs, dict) and probs:
        best, best_p = None, -1.0
        for k, v in probs.items():
            try:
                p = float(v)
            except (TypeError, ValueError):
                continue
            if p <= best_p:
                continue
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


# ------------------------------------------------------------------ 传输

def resolve_real_ip(host: str) -> list[str]:
    """用 DoH 查真实 IP，绕开本机被污染的 DNS。

    只对域名有意义。传进来 IP 字面量（127.0.0.1、10.x 等）时直接返回空——
    否则超时后会给本地地址白查一圈 DoH，把整个答题预算拖爆（实测踩过）。
    """
    if not host or _is_ip_literal(host) or host.lower() == "localhost":
        return []
    if host in _ip_cache:
        return _ip_cache[host]
    for tpl in _DOH:
        try:
            url = tpl.format(host=urllib.parse.quote(host))
            req = urllib.request.Request(url, headers={"Accept": "application/dns-json"})
            with urllib.request.urlopen(req, timeout=_DOH_TIMEOUT) as r:
                j = json.loads(r.read().decode("utf-8"))
            ips = [a["data"] for a in (j.get("Answer") or [])
                   if a.get("type") == 1 and a.get("data")]
            if ips:
                _ip_cache[host] = ips
                return ips
        except Exception:  # noqa: BLE001 - 换下一个 DoH
            continue
    ips = _IP_FALLBACK.get(host, [])
    _ip_cache[host] = ips
    return ips


def _is_ip_literal(host: str) -> bool:
    try:
        import ipaddress
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


def post_via_ip(url: str, body: bytes, headers: dict, ip: str, timeout: float) -> tuple[int, str]:
    """把请求打到指定 IP，但 SNI 和 Host 仍用真域名（否则证书/路由都不对）。"""
    u = urllib.parse.urlparse(url)
    ctx = ssl.create_default_context()
    raw = socket.create_connection((ip, u.port or 443), timeout=timeout)
    ssock = ctx.wrap_socket(raw, server_hostname=u.hostname)
    conn = http.client.HTTPSConnection(u.hostname, timeout=timeout)
    conn.sock = ssock          # 塞进去就不让它自己再解析域名
    try:
        hdrs = dict(headers)
        hdrs["Host"] = u.hostname
        path = u.path + (f"?{u.query}" if u.query else "")
        conn.request("POST", path, body=body, headers=hdrs)
        resp = conn.getresponse()
        return resp.status, resp.read().decode("utf-8", "replace")
    finally:
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass


def post_json(url: str, payload: dict, headers: dict, timeout: float) -> object:
    """发 JSON，总耗时不超过 timeout。

    先走正常请求（DNS 正常时最快）；网络层失败就改走 DoH + 真 IP 直连。
    本机 DNS 把 api.typesafe.ai 污染成 28.0.1.x，所以第二条路是必需的。

    硬截止：两条路共用同一个预算。否则第一次超时后再去查 DoH，
    总耗时会翻几倍——而这里的预算来自答题倒计时，超了就是丢分。
    """
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    hdrs = {"Content-Type": "application/json", **headers}
    deadline = time.monotonic() + timeout

    def left() -> float:
        return deadline - time.monotonic()

    try:
        req = urllib.request.Request(url, data=body, method="POST")
        for k, v in hdrs.items():
            req.add_header(k, v)
        with urllib.request.urlopen(req, timeout=max(0.2, left())) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError:
        raise                      # 4xx/5xx 是业务错误，重试无意义
    except (urllib.error.URLError, TimeoutError, OSError):
        pass                       # 网络层问题 → 换 DoH 直连

    if left() <= 0.3:
        raise urllib.error.URLError("预算耗尽")

    host = urllib.parse.urlparse(url).hostname or ""
    ips = resolve_real_ip(host)    # IP 字面量会直接返回空，不会白查 DoH
    last: Exception | None = None
    for ip in ips:
        if left() <= 0.2:
            break
        try:
            status, text = post_via_ip(url, body, hdrs, ip, max(0.2, left()))
            if status >= 400:
                raise urllib.error.HTTPError(url, status, text[:200], None, None)
            return json.loads(text)
        except Exception as e:  # noqa: BLE001 - 换下一个 IP
            last = e
    raise last or urllib.error.URLError(f"无法连接 {host}")


# ------------------------------------------------------------------ 入口

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
    auth = {"Authorization": f"Bearer {key}"}

    try:
        if mode == "jev":
            payload = build_request(q, getattr(cfg, "model", "jev-latest"))
            # TypeSafe 的 state 要的是字符串，不是对象
            payload["state"] = json.dumps(payload["state"], ensure_ascii=False)
            base = str(getattr(cfg, "base_url", "")).rstrip("/")
            url = (base + "/systemone") if base else TYPESAFE_ENDPOINT
            out = post_json(url, payload, auth, t)
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
        out = post_json(url, payload, auth, t)
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
