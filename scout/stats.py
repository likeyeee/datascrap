"""运行统计：LLM 每日用量、采集进程心跳与计数。"""
from __future__ import annotations

import os
import socket
from datetime import timedelta

from .db import UsageDaily, WorkerStatus, session, utcnow

WORKER_NAME = f"{socket.gethostname()}:{os.getpid()}"
HEARTBEAT_STALE = timedelta(seconds=120)

# 本进程启动以来的计数，随心跳写入数据库
counters: dict[str, int] = {"crawled": 0, "crawl_failed": 0, "scored": 0, "score_failed": 0}


def bump(key: str, n: int = 1) -> None:
    counters[key] = counters.get(key, 0) + n


def record_usage(model: str, usage: dict | None, error: bool = False) -> None:
    usage = usage or {}
    day = utcnow().strftime("%Y-%m-%d")
    try:
        with session() as s:
            row = s.get(UsageDaily, (day, model))
            if row is None:
                row = UsageDaily(day=day, model=model, calls=0, prompt_tokens=0, cache_hit_tokens=0,
                                 completion_tokens=0, errors=0)
                s.add(row)
            if error:
                row.errors += 1
                return
            row.calls += 1
            row.prompt_tokens += int(usage.get("prompt_tokens", 0))
            row.cache_hit_tokens += int(usage.get("prompt_cache_hit_tokens", 0))
            row.completion_tokens += int(usage.get("completion_tokens", 0))
    except Exception:   # 统计失败不能影响打分
        pass


def heartbeat(extra: dict | None = None) -> None:
    with session() as s:
        row = s.get(WorkerStatus, WORKER_NAME)
        if row is None:
            row = WorkerStatus(name=WORKER_NAME, started_at=utcnow())
            s.add(row)
        row.beat_at = utcnow()
        row.info = {**counters, **(extra or {})}


def workers() -> list[dict]:
    """最近 24 小时有心跳的采集进程。"""
    now = utcnow()
    with session() as s:
        rows = s.query(WorkerStatus).filter(WorkerStatus.beat_at >= now - timedelta(days=1)) \
            .order_by(WorkerStatus.beat_at.desc()).all()
        return [{"name": r.name, "started_at": r.started_at.isoformat(timespec="seconds"),
                 "beat_at": r.beat_at.isoformat(timespec="seconds"),
                 "running": now - r.beat_at < HEARTBEAT_STALE, "info": r.info or {}} for r in rows]
