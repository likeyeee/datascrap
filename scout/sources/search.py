"""搜索引擎结果抓取（DuckDuckGo HTML 版 / Bing）。

注意：自动抓取搜索结果页违反搜索引擎的使用条款，默认关闭。
低频运行，遇到验证码立即停止本轮，不做任何绕过。
推荐改用浏览器插件在人工搜索时一键提取结果。
"""
from __future__ import annotations

import asyncio
import base64
import itertools
import logging
from urllib.parse import parse_qs, unquote, urlsplit

import httpx
from selectolax.lexbor import LexborHTMLParser

from ..config import keywords
from .base import Source, register

log = logging.getLogger(__name__)
BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36")


class CaptchaError(Exception):
    pass


def build_queries() -> list[str]:
    kw = keywords()
    out = []
    for tpl, cat, fp in itertools.product(kw.get("templates", []), kw.get("categories", []),
                                          kw.get("footprints", [])):
        out.append(tpl.format(category=cat, footprint=fp))
    return out


def _decode_bing(href: str) -> str:
    if "bing.com/ck/a" not in href:
        return href
    u = parse_qs(urlsplit(href).query).get("u", [""])[0]
    if u.startswith("a1"):
        raw = u[2:]
        try:
            return base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)).decode()
        except ValueError:
            return href
    return href


async def ddg(c: httpx.AsyncClient, q: str) -> list[str]:
    r = await c.post("https://html.duckduckgo.com/html/", data={"q": q, "kl": "us-en"})
    if r.status_code != 200 or "anomaly" in r.text.lower() or "captcha" in r.text.lower():
        raise CaptchaError("duckduckgo")
    out = []
    for a in LexborHTMLParser(r.text).css("a.result__a"):
        href = a.attributes.get("href") or ""
        if "uddg=" in href:
            href = unquote(parse_qs(urlsplit(href).query).get("uddg", [""])[0])
        out.append(href)
    return out


async def bing(c: httpx.AsyncClient, q: str) -> list[str]:
    r = await c.get("https://www.bing.com/search", params={"q": q, "setlang": "en-US", "cc": "US", "count": 30})
    if r.status_code != 200 or "captcha" in r.text.lower()[:20000]:
        raise CaptchaError("bing")
    return [_decode_bing(a.attributes.get("href") or "") for a in LexborHTMLParser(r.text).css("li.b_algo h2 a")]


@register
class SearchSource(Source):
    name = "search"
    priority = 3

    async def run(self) -> str:
        queries = build_queries()
        if not queries:
            return "keywords.yaml 中没有可用的关键词组合"
        cur = self.load_cursor()
        idx = int(cur.get("index", 0)) % len(queries)
        n = int(self.options.get("queries_per_run", 5))
        delay = float(self.options.get("delay", 30))
        engines = [("ddg", ddg), ("bing", bing)]
        total = 0
        async with httpx.AsyncClient(timeout=30, follow_redirects=True,
                                     headers={"User-Agent": BROWSER_UA, "Accept-Language": "en-US,en;q=0.9"}) as c:
            for i in range(n):
                q = queries[(idx + i) % len(queries)]
                name, fn = engines[(idx + i) % len(engines)]
                try:
                    urls = await fn(c, q)
                except CaptchaError as e:
                    msg = f"{e} 返回验证码/拦截，本轮停止"
                    self.save_cursor({"index": idx + i}, msg)
                    return msg
                except httpx.HTTPError as e:
                    log.warning("search %s %s: %s", name, q, e)
                    continue
                total += self.emit(urls, f"{name}: {q}")
                await asyncio.sleep(delay)
        self.save_cursor({"index": idx + n}, f"新增 {total}")
        return f"执行 {n} 次搜索，新增 {total} 个候选"
