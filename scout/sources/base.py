"""发现渠道插件基类。新增渠道：继承 Source，实现 run()，用 @register 注册。"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from ..db import SourceState, session, utcnow
from ..domains import add_candidates

log = logging.getLogger(__name__)
REGISTRY: dict[str, type["Source"]] = {}


async def get_with_retry(c: httpx.AsyncClient, url: str, params: dict | None = None,
                         attempts: int = 4) -> httpx.Response:
    """Common Crawl、crt.sh 等公共服务经常返回 502/503，退避重试。"""
    r = None
    for attempt in range(attempts):
        try:
            r = await c.get(url, params=params)
            if r.status_code < 500 and r.status_code != 429:
                return r
        except httpx.TransportError:
            if attempt == attempts - 1:
                raise
        await asyncio.sleep(10 * 2 ** attempt)
    assert r is not None
    return r


def register(cls: type["Source"]) -> type["Source"]:
    REGISTRY[cls.name] = cls
    return cls


def get_source(name: str) -> "Source":
    if name not in REGISTRY:
        raise KeyError(f"未知渠道：{name}，可选：{', '.join(REGISTRY)}")
    return REGISTRY[name]()


class Source:
    name = "base"
    priority = 0   # 该渠道发现的站点在采集队列中的优先级

    def __init__(self, options: dict[str, Any] | None = None) -> None:
        from ..config import settings
        self.options = options or settings()["scheduler"]["sources"].get(self.name, {})

    # ---- 游标（断点续跑） ----
    def load_cursor(self) -> dict:
        with session() as s:
            st = s.get(SourceState, self.name)
            return dict(st.cursor or {}) if st else {}

    def save_cursor(self, cursor: dict, result: str = "") -> None:
        with session() as s:
            st = s.get(SourceState, self.name) or SourceState(name=self.name)
            st.cursor = cursor
            st.last_run = utcnow()
            st.last_result = result[:1000]
            s.add(st)

    def emit(self, domains: list[str], detail: str | None = None) -> int:
        return add_candidates(domains, self.name, detail, self.priority)

    async def run(self) -> str:
        """执行一次发现，返回结果描述。"""
        raise NotImplementedError
