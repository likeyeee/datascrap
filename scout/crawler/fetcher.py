"""带 robots.txt 检查和单域名限速的异步 HTTP 抓取器。"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import httpx

from ..config import settings


@dataclass
class Page:
    url: str
    status: int
    text: str
    headers: dict[str, str]
    content: bytes = b""

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300

    @property
    def host(self) -> str:
        return urlsplit(self.url).hostname or ""


class RobotsBlocked(Exception):
    pass


log = logging.getLogger(__name__)
SHOPIFY_GROUP = "shopify"
API_SUFFIXES = (".json", ".atom", ".xml", ".js", ".gz")


class Fetcher:
    def __init__(self) -> None:
        cfg = settings()["crawler"]
        self.ua = cfg["user_agent"]
        self.delay = float(cfg["per_domain_delay"])
        self.respect_robots = bool(cfg["respect_robots"])
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(cfg["timeout"]),
            follow_redirects=True,
            headers={
                "User-Agent": self.ua,
                "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            },
            limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
        )
        self.shopify_delay = float(cfg.get("shopify_delay", 1.0))
        self._robots: dict[str, RobotFileParser | None] = {}
        self._last_hit: dict[str, float] = {}
        self._pause_until: dict[str, float] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._shopify_hosts: set[str] = set()

    async def close(self) -> None:
        await self.client.aclose()

    async def __aenter__(self) -> "Fetcher":
        return self

    async def __aexit__(self, *exc) -> None:
        await self.close()

    def _group(self, host: str) -> str:
        """限速分组。Shopify 按访问者 IP 对其托管的所有店铺统一限流，因此所有 Shopify 店铺共用一个分组。"""
        if host.endswith(".myshopify.com") or host in self._shopify_hosts:
            return SHOPIFY_GROUP
        return host

    def _learn(self, host: str, headers: httpx.Headers) -> None:
        if "x-shopid" in headers or "x-shopify-stage" in headers or \
                headers.get("powered-by", "").lower() == "shopify":
            self._shopify_hosts.add(host)

    async def _throttle(self, host: str) -> None:
        group = self._group(host)
        delay = self.shopify_delay if group == SHOPIFY_GROUP else self.delay
        lock = self._locks.setdefault(group, asyncio.Lock())
        async with lock:
            ready = max(self._last_hit.get(group, 0) + delay, self._pause_until.get(group, 0))
            wait = ready - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_hit[group] = time.monotonic()

    def _pause(self, host: str, retry_after: str | None) -> float:
        try:
            wait = min(max(float(retry_after or 60), 5.0), 120.0)
        except ValueError:
            wait = 60.0
        group = self._group(host)
        self._pause_until[group] = max(self._pause_until.get(group, 0), time.monotonic() + wait)
        log.info("%s 返回 429，%s 组暂停 %.0f 秒", host, group, wait)
        return wait

    async def _robots_for(self, scheme: str, host: str) -> RobotFileParser | None:
        if host in self._robots:
            return self._robots[host]
        rp: RobotFileParser | None = None
        try:
            await self._throttle(host)
            r = await self.client.get(f"{scheme}://{host}/robots.txt")
            if r.status_code == 200:
                rp = RobotFileParser()
                rp.parse(r.text.splitlines())
        except httpx.HTTPError:
            rp = None
        self._robots[host] = rp
        return rp

    async def allowed(self, url: str) -> bool:
        if not self.respect_robots:
            return True
        parts = urlsplit(url)
        rp = await self._robots_for(parts.scheme or "https", parts.hostname or "")
        return rp is None or rp.can_fetch(self.ua, url)

    async def get(self, url: str, *, check_robots: bool = True, retries: int = 1) -> Page:
        if check_robots and not await self.allowed(url):
            raise RobotsBlocked(url)
        host = urlsplit(url).hostname or ""
        last_exc: Exception | None = None
        for attempt in range(retries + 1):
            await self._throttle(host)
            try:
                r = await self.client.get(url)
                self._learn(host, r.headers)
                self._learn(r.url.host, r.headers)
                page = Page(str(r.url), r.status_code, r.text, {k.lower(): v for k, v in r.headers.items()},
                            r.content)
                # .json/.atom 等接口是单独限流的，不代表整个 IP 被限，直接返回不重试
                if r.status_code == 429 and not urlsplit(url).path.endswith(API_SUFFIXES):
                    self._pause(host, r.headers.get("retry-after"))
                    if attempt < retries:
                        continue   # _throttle 会等到暂停结束
                elif r.status_code == 503 and attempt < retries:
                    await asyncio.sleep(5.0 * (attempt + 1))
                    continue
                return page
            except httpx.HTTPError as e:
                last_exc = e
                await asyncio.sleep(2 * (attempt + 1))
        raise last_exc or RuntimeError(url)

    async def get_json(self, url: str, **kw) -> dict | list | None:
        try:
            page = await self.get(url, **kw)
        except (httpx.HTTPError, RobotsBlocked):
            return None
        if not page.ok:
            return None
        try:
            import json
            return json.loads(page.text)
        except ValueError:
            return None
