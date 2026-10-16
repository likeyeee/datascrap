"""加载 config/*.yaml，并允许环境变量覆盖（SECTION__KEY=value）。"""
from __future__ import annotations

import os
import time
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = Path(os.environ.get("SCOUT_CONFIG_DIR", ROOT / "config"))

load_dotenv(ROOT / ".env")


def _load(name: str) -> dict[str, Any]:
    path = CONFIG_DIR / name
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _coerce(value: str, current: Any) -> Any:
    if isinstance(current, bool):
        return value.lower() in ("1", "true", "yes", "on")
    if isinstance(current, int):
        return int(value)
    if isinstance(current, float):
        return float(value)
    if isinstance(current, list):
        return [v.strip() for v in value.split(",") if v.strip()]
    return value


def _apply_env(settings: dict[str, Any]) -> None:
    for key, value in os.environ.items():
        if "__" not in key:
            continue
        section, _, field = key.lower().partition("__")
        if section in settings and isinstance(settings[section], dict) and field in settings[section]:
            settings[section][field] = _coerce(value, settings[section][field])


@lru_cache
def settings() -> dict[str, Any]:
    s = _load("settings.yaml")
    _apply_env(s)
    if os.environ.get("DATABASE_URL"):
        s["database_url"] = os.environ["DATABASE_URL"]
    s.setdefault("api", {})
    if os.environ.get("API_TOKEN"):
        s["api"]["token"] = os.environ["API_TOKEN"]
    s.setdefault("llm", {})["api_key"] = os.environ.get("DEEPSEEK_API_KEY", "")
    s["secret_key"] = os.environ.get("SECRET_KEY", "")
    return s


# 管理后台可在线修改的配置：数据库中的值优先于 yaml 文件，缓存 30 秒，worker 无需重启即可生效
EDITABLE = {"company": "company.yaml", "scoring": "scoring.yaml"}
_TTL = 30.0
_ttl_cache: dict[str, tuple[float, dict[str, Any]]] = {}


def _editable(key: str) -> dict[str, Any]:
    hit = _ttl_cache.get(key)
    if hit and time.monotonic() - hit[0] < _TTL:
        return hit[1]
    value = None
    try:
        from .db import AppSetting, session
        with session() as s:
            row = s.get(AppSetting, key)
            value = row.value if row and isinstance(row.value, dict) else None
    except Exception:   # 数据库未初始化等情况，回退到文件
        value = None
    value = value or _load(EDITABLE[key])
    _ttl_cache[key] = (time.monotonic(), value)
    return value


def file_default(key: str) -> dict[str, Any]:
    return _load(EDITABLE[key])


def clear_cache() -> None:
    _ttl_cache.clear()


def company() -> dict[str, Any]:
    return _editable("company")


def scoring() -> dict[str, Any]:
    return _editable("scoring")


@lru_cache
def cn_signals() -> dict[str, Any]:
    return _load("cn_signals.yaml")


@lru_cache
def keywords() -> dict[str, Any]:
    return _load("keywords.yaml")
