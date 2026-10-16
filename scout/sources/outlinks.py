"""外链扩散：从已打分站点的外部链接中发现新站点（只扩散高分或华人关联站点的外链）。"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import or_, select

from ..db import Store, session
from .base import Source, register


@register
class OutlinksSource(Source):
    name = "outlinks"
    priority = 1

    async def run(self) -> str:
        cur = self.load_cursor()
        last_ts = datetime.fromisoformat(cur.get("last_scored_at", "2000-01-01T00:00:00"))
        batch = int(self.options.get("batch", 200))
        with session() as s:
            rows = s.execute(
                select(Store.domain, Store.crawl_data, Store.scored_at)
                .where(Store.scored_at > last_ts,
                       or_(Store.cn_rule_score >= 20, Store.total_score >= 60))
                .order_by(Store.scored_at).limit(batch)
            ).all()
        total = 0
        for domain, data, scored_at in rows:
            total += self.emit((data or {}).get("outlinks") or [], f"from {domain}")
            last_ts = scored_at
        self.save_cursor({"last_scored_at": last_ts.isoformat()}, f"处理 {len(rows)} 个站点，新增 {total}")
        return f"处理 {len(rows)} 个站点，新增 {total} 个候选"
