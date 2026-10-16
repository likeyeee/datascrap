from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from sqlalchemy import (
    JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, create_engine, event, inspect, text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from .config import ROOT, settings


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


# 站点状态流转：
# new -> crawling -> crawled -> scoring -> scored
#                 -> not_store / not_target（非目标国家）/ failed / blocked（robots 禁止）
class Store(Base):
    __tablename__ = "stores"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    domain: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    url: Mapped[str | None] = mapped_column(String(500))
    name: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(20), default="new", index=True)
    priority: Mapped[int] = mapped_column(Integer, default=0, index=True)
    source: Mapped[str | None] = mapped_column(String(50))          # 首次发现渠道
    alias_of: Mapped[str | None] = mapped_column(String(255))       # 跳转到其他域名时记录主域名

    discovered_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime)
    retry_at: Mapped[datetime | None] = mapped_column(DateTime)       # 失败后的下次重试时间
    crawled_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    scored_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, index=True)
    fail_count: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)

    # 采集结果
    platform: Mapped[str | None] = mapped_column(String(50), index=True)
    country: Mapped[str | None] = mapped_column(String(10), index=True)
    currency: Mapped[str | None] = mapped_column(String(10))
    city: Mapped[str | None] = mapped_column(String(100))
    province: Mapped[str | None] = mapped_column(String(100))
    product_count: Mapped[int | None] = mapped_column(Integer)
    price_min: Mapped[float | None] = mapped_column(Float)
    price_max: Mapped[float | None] = mapped_column(Float)
    price_median: Mapped[float | None] = mapped_column(Float)
    last_product_update: Mapped[datetime | None] = mapped_column(DateTime)
    emails: Mapped[list | None] = mapped_column(JSON)
    phones: Mapped[list | None] = mapped_column(JSON)
    socials: Mapped[dict | None] = mapped_column(JSON)
    marketing: Mapped[dict | None] = mapped_column(JSON)    # 像素/营销工具/联盟/评价应用
    cn_signals: Mapped[list | None] = mapped_column(JSON)   # 华人识别证据
    cn_rule_score: Mapped[int | None] = mapped_column(Integer, index=True)
    cn_location: Mapped[str | None] = mapped_column(String(20))   # us / china / unknown（规则推断）
    crawl_data: Mapped[dict | None] = mapped_column(JSON)   # 页面文本、商品样本等原始数据

    # LLM 结果
    main_products: Mapped[str | None] = mapped_column(Text)
    main_categories: Mapped[list | None] = mapped_column(JSON)
    promotion_channels: Mapped[list | None] = mapped_column(JSON)
    chinese_type: Mapped[str | None] = mapped_column(String(20), index=True)
    chinese_confidence: Mapped[int | None] = mapped_column(Integer)
    scores: Mapped[dict | None] = mapped_column(JSON)
    total_score: Mapped[float | None] = mapped_column(Float, index=True)
    grade: Mapped[str | None] = mapped_column(String(2), index=True)
    llm_result: Mapped[dict | None] = mapped_column(JSON)
    llm_model: Mapped[str | None] = mapped_column(String(50))

    # 人工跟进
    outreach_status: Mapped[str] = mapped_column(String(20), default="未联系", index=True)
    notes: Mapped[str | None] = mapped_column(Text)
    tags: Mapped[list | None] = mapped_column(JSON)
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    starred: Mapped[bool | None] = mapped_column(Boolean, default=False)


class User(Base):
    """登录用户。role: admin（后台管理员）/ user（前台运营、招商）。"""
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    display_name: Mapped[str | None] = mapped_column(String(50))
    password_hash: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(10), default="user")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    session_version: Mapped[int] = mapped_column(Integer, default=1)   # 改密码/禁用时递增，使旧登录失效
    api_token_hash: Mapped[str | None] = mapped_column(String(64), index=True)   # 插件用的个人令牌（只存哈希）
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_login: Mapped[datetime | None] = mapped_column(DateTime)


class FollowUp(Base):
    """线索跟进记录（状态变更、备注、认领）。"""
    __tablename__ = "followups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    action: Mapped[str] = mapped_column(String(20))      # note / status / claim / release
    content: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class AppSetting(Base):
    """在后台修改的配置（覆盖 config/*.yaml 中的同名配置），以及系统密钥等。"""
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(50), primary_key=True)
    value: Mapped[dict | list | str | None] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    updated_by: Mapped[str | None] = mapped_column(String(50))


class Discovery(Base):
    """每一次发现记录（同一站点可被多个渠道多次发现）。"""
    __tablename__ = "discoveries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id", ondelete="CASCADE"), index=True)
    source: Mapped[str] = mapped_column(String(50), index=True)
    detail: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class SourceState(Base):
    """发现渠道的增量游标，用于持续采集时断点续跑。"""
    __tablename__ = "source_state"

    name: Mapped[str] = mapped_column(String(50), primary_key=True)
    cursor: Mapped[dict | None] = mapped_column(JSON)
    last_run: Mapped[datetime | None] = mapped_column(DateTime)
    last_result: Mapped[str | None] = mapped_column(Text)
    enabled_override: Mapped[bool | None] = mapped_column(Boolean)


class UsageDaily(Base):
    """每日 LLM 用量，用于成本监控。"""
    __tablename__ = "llm_usage_daily"

    day: Mapped[str] = mapped_column(String(10), primary_key=True)     # YYYY-MM-DD（UTC）
    model: Mapped[str] = mapped_column(String(50), primary_key=True)
    calls: Mapped[int] = mapped_column(Integer, default=0)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cache_hit_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    errors: Mapped[int] = mapped_column(Integer, default=0)


class WorkerStatus(Base):
    """采集进程心跳，看板据此判断自动采集是否在运行。"""
    __tablename__ = "worker_status"

    name: Mapped[str] = mapped_column(String(100), primary_key=True)   # 主机名:进程号
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    beat_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    info: Mapped[dict | None] = mapped_column(JSON)


_engine = None
_Session: sessionmaker | None = None


def engine():
    global _engine, _Session
    if _engine is None:
        url = settings()["database_url"]
        # 中文按原样存储，便于在数据库中直接查看和按文本搜索 JSON 列
        kwargs: dict[str, Any] = {"pool_pre_ping": True,
                                  "json_serializer": lambda o: json.dumps(o, ensure_ascii=False, default=str)}
        if url.startswith("sqlite"):
            path = url.split("///", 1)[-1]
            if path and not Path(path).is_absolute():
                path = str(ROOT / path)
                url = "sqlite:///" + path
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            kwargs["connect_args"] = {"check_same_thread": False, "timeout": 30}
        _engine = create_engine(url, **kwargs)
        if url.startswith("sqlite"):
            @event.listens_for(_engine, "connect")
            def _pragma(conn, _):
                cur = conn.cursor()
                cur.execute("PRAGMA journal_mode=WAL")
                cur.execute("PRAGMA foreign_keys=ON")
                cur.close()
        _Session = sessionmaker(_engine, expire_on_commit=False)
    return _engine


def init_db() -> None:
    Base.metadata.create_all(engine())
    _add_missing_columns()


def _add_missing_columns() -> None:
    """轻量迁移：给已有表补上新增的列（只处理新增可空列，不改已有列）。"""
    eng = engine()
    insp = inspect(eng)
    with eng.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if not insp.has_table(table.name):
                continue
            existing = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name in existing or col.primary_key:
                    continue
                ddl_type = col.type.compile(dialect=eng.dialect)
                conn.execute(text(f'ALTER TABLE {table.name} ADD COLUMN "{col.name}" {ddl_type}'))
                for idx in table.indexes:
                    if [c.name for c in idx.columns] == [col.name]:
                        idx.create(conn, checkfirst=True)


@contextmanager
def session() -> Iterator[Session]:
    engine()
    assert _Session is not None
    s = _Session()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()
