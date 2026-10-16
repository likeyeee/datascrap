"""Common Crawl 索引：批量获取建站平台默认子域名（xxx.myshopify.com 等）。

每次运行处理若干索引页，游标记录到数据库，持续运行时会逐页推进；
当前抓取批次处理完后，等待 Common Crawl 发布新批次再继续。
"""
from __future__ import annotations

import json
import logging
from urllib.parse import urlsplit

import httpx

from ..config import settings
from ..domains import add_candidates
from .base import Source, get_with_retry, register

log = logging.getLogger(__name__)

# (匹配模式, 优先级)：国产 SaaS 子域名优先级更高
PATTERNS = [
    ("*.myshoplaza.com", 5),
    ("*.myshopline.com", 5),
    ("*.myshopify.com", 0),
]
COLLINFO = "https://index.commoncrawl.org/collinfo.json"


@register
class CommonCrawlSource(Source):
    name = "commoncrawl"

    async def run(self) -> str:
        pages_per_run = int(self.options.get("pages_per_run", 3))
        cur = self.load_cursor()
        ua = settings()["crawler"]["user_agent"]
        async with httpx.AsyncClient(timeout=120, headers={"User-Agent": ua}, follow_redirects=True) as c:
            r = await get_with_retry(c, COLLINFO)
            r.raise_for_status()
            latest = r.json()[0]
            if cur.get("crawl") != latest["id"]:
                cur = {"crawl": latest["id"], "api": latest["cdx-api"], "pattern": 0, "page": 0, "pages": None}
            if cur["pattern"] >= len(PATTERNS):
                self.save_cursor(cur, f"{cur['crawl']} 已处理完，等待新批次")
                return "无新批次"

            added_total = 0
            done = 0
            while done < pages_per_run and cur["pattern"] < len(PATTERNS):
                pattern, prio = PATTERNS[cur["pattern"]]
                if cur["pages"] is None:
                    r = await get_with_retry(c, cur["api"], params={"url": pattern, "output": "json", "showNumPages": "true"})
                    r.raise_for_status()
                    cur["pages"] = int(r.json().get("pages", 0))
                if cur["page"] >= cur["pages"]:
                    cur.update(pattern=cur["pattern"] + 1, page=0, pages=None)
                    continue
                r = await get_with_retry(c, cur["api"], params={"url": pattern, "output": "json", "fl": "url",
                                                    "page": cur["page"]})
                if r.status_code == 404:  # 该模式无数据
                    cur.update(pattern=cur["pattern"] + 1, page=0, pages=None)
                    continue
                r.raise_for_status()
                hosts = set()
                for line in r.text.splitlines():
                    try:
                        hosts.add(urlsplit(json.loads(line)["url"]).hostname or "")
                    except (ValueError, KeyError):
                        continue
                added = add_candidates(sorted(hosts), self.name, f"{cur['crawl']} {pattern} p{cur['page']}", prio)
                added_total += added
                log.info("commoncrawl %s page %s/%s: %s hosts, %s new", pattern, cur["page"], cur["pages"],
                         len(hosts), added)
                cur["page"] += 1
                done += 1
                self.save_cursor(cur, f"{pattern} 第 {cur['page']}/{cur['pages']} 页")
        return f"新增 {added_total} 个候选"
