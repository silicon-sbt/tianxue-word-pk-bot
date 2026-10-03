"""配置加载：读根目录 config.toml，缺项用内置默认值补齐。

用标准库 tomllib（Python 3.11+），不引入任何依赖。
配置写错不该让脚本崩掉——所有取值都兜底到默认值。
"""
from __future__ import annotations

import os
import pathlib
import tomllib
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.toml"

# 与 config.toml 一一对应。config.toml 缺失或写坏时用这套。
DEFAULTS: dict[str, dict[str, Any]] = {
    "bot": {
        "question_seconds": 6.0,
    },
    "ai": {
        "enabled": False,
        "mode": "chat",
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-chat",
        "api_key": "",
        "timeout": 1.5,
        "remember": True,
    },
    "score": {
        "enabled": False,
        "target_accuracy": 0.70,
    },
}


class Config:
    """点号取值：cfg.ai.enabled / cfg.get("score", "target_accuracy")"""

    def __init__(self, data: dict[str, Any] | None = None) -> None:
        self._d = {**{k: dict(v) for k, v in DEFAULTS.items()}}
        if data:
            for section, values in data.items():
                if isinstance(values, dict):
                    self._d.setdefault(section, {}).update(values)

        # api_key 允许用环境变量，避免把密钥写进文件
        ai = self._d["ai"]
        if not ai.get("api_key"):
            ai["api_key"] = os.environ.get("PK_API_KEY", "")

        self._coerce()

    def _coerce(self) -> None:
        """把类型掰正。TOML 写错类型（比如 timeout = "1.5"）时仍然能用。"""
        def num(section: str, key: str, cast):
            try:
                self._d[section][key] = cast(self._d[section][key])
            except (KeyError, TypeError, ValueError):
                self._d[section][key] = DEFAULTS[section][key]

        def flag(section: str, key: str):
            v = self._d[section].get(key)
            if not isinstance(v, bool):
                self._d[section][key] = bool(v) if v is not None else DEFAULTS[section][key]

        num("bot", "question_seconds", float)
        flag("ai", "enabled")
        flag("ai", "remember")
        num("ai", "timeout", float)
        flag("score", "enabled")
        num("score", "target_accuracy", float)

        # 目标正确率夹到合理区间，避免配置写 70（当成 70 倍）之类
        t = self._d["score"]["target_accuracy"]
        if t > 1:
            t = t / 100.0
        self._d["score"]["target_accuracy"] = min(max(t, 0.0), 1.0)

    def get(self, section: str, key: str, default: Any = None) -> Any:
        return self._d.get(section, {}).get(key, default)

    def __getattr__(self, section: str) -> Any:
        d = self.__dict__.get("_d", {})
        if section in d:
            return _Section(d[section])
        raise AttributeError(section)

    def as_dict(self) -> dict[str, Any]:
        return self._d


class _Section:
    def __init__(self, values: dict[str, Any]) -> None:
        self._v = values

    def __getattr__(self, key: str) -> Any:
        if key in self._v:
            return self._v[key]
        raise AttributeError(key)

    def __repr__(self) -> str:
        return f"<config {self._v}>"


def load(path: pathlib.Path | None = None) -> Config:
    """读配置。文件不存在或语法错误时退回默认值，并打印一行提示。"""
    p = path or CONFIG_PATH
    if not p.exists():
        return Config()
    try:
        with p.open("rb") as f:
            return Config(tomllib.load(f))
    except (tomllib.TOMLDecodeError, OSError) as e:
        print(f"[警告] {p.name} 读取失败，使用默认配置：{e}")
        return Config()
