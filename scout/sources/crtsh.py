"""crt.sh 证书透明日志：发现新签发证书的平台子域名（新开店铺）。"""
from __future__ import annotations

import httpx

from ..config import settings
from .base import Source, get_with_retry, register

# myshopify.com 数量过大，crt.sh 会超时，这里只查国产 SaaS
QUERIES = ["%.myshoplaza.com", "%.myshopline.com"]


@register
class CrtShSource(Source):
    name = "crtsh"
    priority = 5

    async def run(self) -> str:
        ua = settings()["crawler"]["user_agent"]
        cur = self.load_cursor()
        total = 0
        async with httpx.AsyncClient(timeout=180, headers={"User-Agent": ua}) as c:
            for q in QUERIES:
                last_id = int(cur.get(q, 0))
                try:
                    r = await get_with_retry(c, "https://crt.sh/",
                                             params={"q": q, "output": "json", "exclude": "expired"}, attempts=3)
                    r.raise_for_status()
                    cur.pop(f"{q}_error", None)
                    rows = r.json()
                except (httpx.HTTPError, ValueError) as e:
                    cur[f"{q}_error"] = str(e)[:200]
                    continue
                new_rows = [row for row in rows if int(row.get("id", 0)) > last_id]
                names = set()
                for row in new_rows:
                    for n in str(row.get("name_value", "")).split("\n"):
                        n = n.strip().lstrip("*.")
                        if n and n != q.lstrip("%."):
                            names.add(n)
                total += self.emit(sorted(names), f"crt.sh {q}")
                if rows:
                    cur[q] = max(int(row.get("id", 0)) for row in rows)
        self.save_cursor(cur, f"新增 {total}")
        return f"新增 {total} 个候选"
