"""持续运行入口：发现、采集、打分、维护四条循环并行。"""
from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

from .config import settings
from .crawler.fetcher import Fetcher
from .db import SourceState, init_db, session, utcnow
from . import stats, worker

log = logging.getLogger("scout.scheduler")
RETRY_AFTER_FAILURE = timedelta(minutes=15)


async def crawl_loop() -> None:
    cfg = settings()["scheduler"]
    while True:
        try:
            async with Fetcher() as f:   # 定期重建，释放 robots 缓存
                for _ in range(50):
                    n = await worker.crawl_batch(f, int(cfg["crawl_batch"]))
                    if n == 0:
                        await asyncio.sleep(int(cfg["idle_sleep"]))
        except Exception:
            log.exception("crawl loop 异常")
            await asyncio.sleep(30)


async def score_loop() -> None:
    from .llm.client import DeepSeekClient, LLMError

    cfg = settings()["scheduler"]
    try:
        client = DeepSeekClient()
    except LLMError as e:
        log.warning("LLM 打分未启用：%s", e)
        return
    while True:
        try:
            n = await worker.score_batch(client, int(cfg["score_batch"]))
            if n == 0:
                await asyncio.sleep(int(cfg["idle_sleep"]))
        except Exception:
            log.exception("score loop 异常，10 分钟后重试")
            await asyncio.sleep(600)
        u = client.usage
        if u.calls and u.calls % 50 == 0:
            log.info("LLM 用量：%s 次调用，输入 %s（缓存命中 %s），输出 %s tokens",
                     u.calls, u.prompt_tokens, u.cache_hit_tokens, u.completion_tokens)


async def discovery_loop() -> None:
    from .sources import REGISTRY

    while True:
        conf = settings()["scheduler"]["sources"]
        for name, cls in REGISTRY.items():
            opts = conf.get(name, {})
            with session() as s:
                st = s.get(SourceState, name)
                enabled = opts.get("enabled", False) if not st or st.enabled_override is None else st.enabled_override
                last = st.last_run if st else None
            if not enabled:
                continue
            if last and utcnow() - last < timedelta(minutes=int(opts.get("interval", 60))):
                continue
            try:
                result = await cls(opts).run()
                log.info("discovery %s: %s", name, result)
            except Exception as e:
                log.exception("discovery %s 失败", name)
                with session() as s:
                    st = s.get(SourceState, name) or SourceState(name=name)
                    # 失败后 15 分钟重试，而不是等完整的运行间隔
                    st.last_run = utcnow() - timedelta(minutes=int(opts.get("interval", 60))) + RETRY_AFTER_FAILURE
                    st.last_result = f"失败：{type(e).__name__}: {e}"[:1000]
                    s.add(st)
        await asyncio.sleep(60)


async def maintenance_loop() -> None:
    while True:
        try:
            n1 = worker.release_stale_locks()
            n2 = worker.requeue_stale()
            if n1 or n2:
                log.info("维护：释放超时任务 %s 个，到期重爬 %s 个", n1, n2)
        except Exception:
            log.exception("maintenance 异常")
        await asyncio.sleep(3600)


async def heartbeat_loop() -> None:
    llm_on = bool(settings()["llm"].get("api_key"))
    while True:
        try:
            stats.heartbeat({"llm_enabled": llm_on})
        except Exception:
            log.exception("heartbeat 异常")
        await asyncio.sleep(30)


async def run_forever() -> None:
    init_db()
    log.info("worker 启动（%s），数据库：%s", stats.WORKER_NAME, settings()["database_url"].split("@")[-1])
    await asyncio.gather(heartbeat_loop(), crawl_loop(), score_loop(), discovery_loop(), maintenance_loop())
