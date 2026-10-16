"""采集队列与打分队列的处理逻辑。"""
from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

from sqlalchemy import or_, select, update

from . import stats
from .config import settings
from .crawler import pipeline
from .crawler.fetcher import Fetcher
from .db import Store, session, utcnow
from .domains import add_candidates

log = logging.getLogger(__name__)
LOCK_TIMEOUT = timedelta(minutes=30)
RETRY_BASE = timedelta(hours=1)

STORE_FIELDS = ["url", "name", "platform", "country", "currency", "city", "province", "product_count",
                "price_min", "price_max", "price_median", "last_product_update", "emails", "phones", "socials",
                "marketing", "cn_signals", "cn_rule_score", "cn_location", "crawl_data"]


def _claim(from_status: str, to_status: str, n: int) -> list[int]:
    """原子地领取一批任务。Postgres 下使用 SKIP LOCKED，支持多个 worker 并行。"""
    with session() as s:
        q = (select(Store.id)
             .where(Store.status == from_status, or_(Store.retry_at.is_(None), Store.retry_at <= utcnow()))
             .order_by(Store.priority.desc(), Store.discovered_at).limit(n))
        if s.bind.dialect.name == "postgresql":
            q = q.with_for_update(skip_locked=True)
        ids = list(s.scalars(q))
        if ids:
            s.execute(update(Store).where(Store.id.in_(ids)).values(status=to_status, locked_at=utcnow()))
        return ids


def release_stale_locks() -> int:
    cutoff = utcnow() - LOCK_TIMEOUT
    with session() as s:
        n1 = s.execute(update(Store).where(Store.status == "crawling", Store.locked_at < cutoff)
                       .values(status="new")).rowcount
        n2 = s.execute(update(Store).where(Store.status == "scoring", Store.locked_at < cutoff)
                       .values(status="crawled")).rowcount
    return (n1 or 0) + (n2 or 0)


def requeue_stale(days: int | None = None) -> int:
    """到期重爬：已完成的站点超过 recrawl_days 后重新进入队列。"""
    days = days or int(settings()["crawler"]["recrawl_days"])
    cutoff = utcnow() - timedelta(days=days)
    with session() as s:
        return s.execute(
            update(Store).where(Store.status.in_(["scored", "not_target", "not_store"]), Store.crawled_at < cutoff)
            .values(status="new", priority=-1)
        ).rowcount or 0


def save_crawl(store_id: int, res: dict) -> None:
    cfg = settings()["crawler"]
    status = res.get("status", pipeline.FAILED)
    alias = None
    with session() as s:
        st = s.get(Store, store_id)
        if st is None:
            return
        st.locked_at = None
        st.error = res.get("error")
        if status == "alias":
            st.status = "alias"
            st.alias_of = res.get("alias_of")
            st.crawled_at = utcnow()
            alias = (st.alias_of, st.source or "alias", st.priority)
        elif status == pipeline.FAILED:
            st.fail_count += 1
            st.status = "failed" if st.fail_count >= int(cfg["max_fail_count"]) else "new"
            if st.status == "new":
                # 退避重试：1 小时、4 小时、9 小时…
                st.retry_at = utcnow() + RETRY_BASE * st.fail_count ** 2
        else:
            for k in STORE_FIELDS:
                if k in res:
                    setattr(st, k, res[k])
            st.status = status
            st.fail_count = 0
            st.retry_at = None
            st.crawled_at = utcnow()
    if alias and alias[0]:
        add_candidates([alias[0]], alias[1], f"alias of {res.get('domain')}", alias[2])


async def crawl_batch(f: Fetcher, n: int) -> int:
    ids = _claim("new", "crawling", n)
    if not ids:
        return 0
    with session() as s:
        domains = {i: d for i, d in s.execute(select(Store.id, Store.domain).where(Store.id.in_(ids)))}
    sem = asyncio.Semaphore(int(settings()["crawler"]["concurrency"]))

    async def one(sid: int, domain: str) -> None:
        async with sem:
            try:
                res = await asyncio.wait_for(pipeline.crawl(f, domain), timeout=300)
            except Exception as e:  # 单站点异常不影响整批
                log.exception("crawl %s 失败", domain)
                res = {"status": pipeline.FAILED, "error": f"{type(e).__name__}: {e}"[:300]}
            save_crawl(sid, res)
            stats.bump("crawl_failed" if res.get("status") == pipeline.FAILED else "crawled")
            log.info("crawl %-35s -> %s %s", domain, res.get("status"), res.get("error") or "")

    await asyncio.gather(*(one(i, d) for i, d in domains.items()))
    return len(ids)


async def score_batch(client, n: int) -> int:
    from .llm.scorer import score_store

    ids = _claim("crawled", "scoring", n)
    if not ids:
        return 0
    sem = asyncio.Semaphore(int(settings()["llm"].get("concurrency", 4)))

    async def one(sid: int) -> None:
        async with sem:
            with session() as s:
                st = s.get(Store, sid)
                s.expunge(st)
            try:
                fields = await score_store(client, st)
                status, error = "scored", None
            except Exception as e:
                log.exception("score %s 失败", st.domain)
                fields, status, error = {}, "crawled", f"LLM: {type(e).__name__}: {e}"[:300]
            with session() as s:
                cur = s.get(Store, sid)
                for k, v in fields.items():
                    setattr(cur, k, v)
                cur.status = status
                cur.error = error
                cur.locked_at = None
                if status == "scored":
                    cur.scored_at = utcnow()
                    cur.fail_count = 0
                    cur.retry_at = None
                    ok.append(sid)
                else:
                    cur.fail_count += 1
                    cur.retry_at = utcnow() + timedelta(minutes=30) * cur.fail_count
                    if cur.fail_count >= int(settings()["crawler"]["max_fail_count"]):
                        cur.status = "score_failed"
            stats.bump("scored" if status == "scored" else "score_failed")
            log.info("score %-35s -> %s %s", st.domain, fields.get("grade"), fields.get("total_score"))

    ok: list[int] = []
    await asyncio.gather(*(one(i) for i in ids))
    if not ok:
        raise RuntimeError("本批次打分全部失败，请检查 DeepSeek API Key/余额/网络")
    return len(ids)
