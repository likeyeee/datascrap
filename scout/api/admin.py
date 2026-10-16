"""后台接口：仅管理员可用。"""
from __future__ import annotations

import asyncio
import threading

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select, update

from .. import analytics, auth, stats
from ..auth import CurrentUser, require_admin
from ..config import EDITABLE, clear_cache, company, file_default, scoring, settings
from ..db import AppSetting, SourceState, Store, User, session
from ..domains import add_candidates

router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(require_admin)])

SOURCE_INFO = {
    "commoncrawl": ("Common Crawl", "从公开网页索引批量获取 Shopify / Shoplazza / Shopline 店铺子域名"),
    "crtsh": ("证书透明日志", "发现新签发证书的 Shoplazza / Shopline 店铺，即新开的店"),
    "outlinks": ("外链扩散", "从高分或华人关联站点的外部链接中发现新站点"),
    "search": ("搜索引擎", "抓取 DuckDuckGo / Bing 结果页；违反其使用条款，默认关闭"),
    "extension": ("插件 · 手动加入", "在插件弹窗中把当前站点加入队列"),
    "extension-visit": ("插件 · 浏览识别", "浏览到独立站时自动加入"),
    "extension-page": ("插件 · 页面提取", "在搜索结果、广告库等页面一键提取"),
    "extension-auto": ("插件 · 自动提取", "在搜索结果、广告库页面浏览时自动提取"),
    "extension-link": ("插件 · 右键加入", "右键链接加入队列"),
    "manual": ("手动添加", "后台或命令行手动导入"),
    "csv": ("CSV 导入", "命令行导入 CSV 文件"),
}


# ---------- 监控 ----------
@router.get("/monitor")
def monitor() -> dict:
    data = analytics.monitor()
    data["workers"] = stats.workers()
    data["llm_enabled"] = bool(settings()["llm"].get("api_key"))
    data["llm_today"] = analytics.usage(1)["totals"]
    data["sources"] = sources()
    return data


@router.get("/usage")
def usage(days: int = Query(30, ge=1, le=180)) -> dict:
    return analytics.usage(days)


@router.get("/team")
def team(days: int = Query(30, ge=1, le=365)) -> list[dict]:
    return analytics.team_activity(days)


# ---------- 发现渠道 ----------
@router.get("/sources")
def sources() -> list[dict]:
    from ..sources import REGISTRY
    conf = settings()["scheduler"]["sources"]
    effect = {r["source"]: r for r in analytics.source_effect()}
    out = []
    with session() as s:
        for name, cls in REGISTRY.items():
            st = s.get(SourceState, name)
            enabled = conf.get(name, {}).get("enabled", False)
            if st and st.enabled_override is not None:
                enabled = st.enabled_override
            label, desc = SOURCE_INFO.get(name, (name, ""))
            out.append({"name": name, "label": label, "desc": desc, "scheduled": True, "enabled": enabled, "interval": conf.get(name, {}).get("interval"),
                        "last_run": st.last_run.isoformat(timespec="minutes") if st and st.last_run else None,
                        "last_result": st.last_result if st else None, "effect": effect.get(name)})
    # 插件、手动、CSV 等非调度渠道也展示效果
    for name, row in effect.items():
        if name not in REGISTRY:
            label, desc = SOURCE_INFO.get(name, (name, ""))
            out.append({"name": name, "label": label, "desc": desc, "scheduled": False, "enabled": None,
                        "interval": None, "last_run": None, "last_result": None, "effect": row})
    return out


@router.post("/sources/{name}/toggle")
def toggle_source(name: str, enabled: bool) -> dict:
    from ..sources import REGISTRY
    if name not in REGISTRY:
        raise HTTPException(404)
    with session() as s:
        st = s.get(SourceState, name) or SourceState(name=name)
        st.enabled_override = enabled
        s.add(st)
    return {"ok": True}


@router.post("/sources/{name}/run")
def run_source(name: str) -> dict:
    from ..sources import REGISTRY, get_source
    if name not in REGISTRY:
        raise HTTPException(404)
    # 在独立线程中运行，避免阻塞接口（Common Crawl 一轮可能需要几分钟）
    threading.Thread(target=lambda: asyncio.run(get_source(name).run()), daemon=True).start()
    return {"ok": True, "message": "已在后台开始运行，稍后刷新查看结果"}


# ---------- 站点管理 ----------
class BulkBody(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=5000)
    action: str


@router.post("/stores/bulk")
def bulk(body: BulkBody) -> dict:
    with session() as s:
        cond = Store.id.in_(body.ids)
        if body.action == "recrawl":
            n = s.execute(update(Store).where(cond).values(status="new", priority=20, fail_count=0,
                                                           retry_at=None)).rowcount
        elif body.action == "rescore":
            n = s.execute(update(Store).where(cond, Store.crawl_data.is_not(None))
                          .values(status="crawled", priority=20, fail_count=0, retry_at=None)).rowcount
        elif body.action == "delete":
            n = s.execute(delete(Store).where(cond)).rowcount
        else:
            raise HTTPException(400, "action 只能是 recrawl / rescore / delete")
    return {"ok": True, "affected": n or 0}


class ImportBody(BaseModel):
    domains: list[str] = Field(min_length=1, max_length=20000)
    priority: int = Field(10, ge=-5, le=20)
    note: str | None = None


@router.post("/stores/import")
def import_domains(body: ImportBody, user: CurrentUser = Depends(require_admin)) -> dict:
    added = add_candidates(body.domains, "manual", f"{user.username}: {body.note or '后台导入'}", body.priority)
    return {"received": len(body.domains), "added": added}


# ---------- 用户 ----------
class UserCreate(BaseModel):
    username: str
    password: str
    role: str = "user"
    display_name: str | None = None


class UserPatch(BaseModel):
    display_name: str | None = None
    role: str | None = None
    active: bool | None = None
    password: str | None = None


@router.get("/users")
def list_users() -> list[dict]:
    with session() as s:
        owned = dict(s.execute(select(Store.owner_id, func.count()).where(Store.owner_id.is_not(None))
                               .group_by(Store.owner_id)).all())
        return [{"id": u.id, "username": u.username, "display_name": u.display_name, "role": u.role,
                 "active": u.active, "has_token": bool(u.api_token_hash), "owned": owned.get(u.id, 0),
                 "created_at": u.created_at.isoformat(timespec="minutes"),
                 "last_login": u.last_login.isoformat(timespec="minutes") if u.last_login else None}
                for u in s.scalars(select(User).order_by(User.id))]


@router.post("/users")
def create_user(body: UserCreate) -> dict:
    u = auth.create_user(body.username, body.password, body.role, body.display_name)
    return {"ok": True, "id": u.id}


@router.patch("/users/{user_id}")
def patch_user(user_id: int, body: UserPatch, me: CurrentUser = Depends(require_admin)) -> dict:
    with session() as s:
        u = s.get(User, user_id)
        if not u:
            raise HTTPException(404)
        if u.id == me.id and (body.active is False or (body.role and body.role != "admin")):
            raise HTTPException(400, "不能停用自己或取消自己的管理员权限")
        if body.role:
            if body.role not in ("admin", "user"):
                raise HTTPException(400, "角色只能是 admin 或 user")
            u.role = body.role
        if body.display_name is not None:
            u.display_name = body.display_name.strip() or None
        if body.active is not None:
            u.active = body.active
            if not body.active:
                u.session_version += 1
                u.api_token_hash = None
        if body.password:
            auth.validate_password(body.password)
            u.password_hash = auth.hash_password(body.password)
            u.session_version += 1
    return {"ok": True}


# ---------- 在线配置 ----------
@router.get("/settings")
def get_settings() -> dict:
    out = {}
    with session() as s:
        for key in EDITABLE:
            row = s.get(AppSetting, key)
            out[key] = {"value": row.value if row else file_default(key), "source": "db" if row else "file",
                        "updated_at": row.updated_at.isoformat(timespec="minutes") if row else None,
                        "updated_by": row.updated_by if row else None}
    out["runtime"] = {
        "llm_model": settings()["llm"].get("model"), "review_model": settings()["llm"].get("review_model"),
        "review_threshold": settings()["llm"].get("review_threshold"),
        "target_countries": settings()["crawler"].get("target_countries"),
        "concurrency": settings()["crawler"].get("concurrency"),
        "recrawl_days": settings()["crawler"].get("recrawl_days"),
    }
    return out


def _validate(key: str, value: dict) -> dict:
    if not isinstance(value, dict):
        raise HTTPException(400, "配置必须是对象")
    if key == "company":
        cats = value.get("product_categories")
        if not isinstance(cats, list) or not all(isinstance(c, str) for c in cats):
            raise HTTPException(400, "product_categories 必须是文字列表")
    if key == "scoring":
        dims = value.get("dimensions")
        if not isinstance(dims, dict) or not dims:
            raise HTTPException(400, "至少需要一个打分维度")
        for k, d in dims.items():
            try:
                w = float(d.get("weight"))
            except (TypeError, ValueError, AttributeError):
                raise HTTPException(400, f"维度 {k} 的权重必须是数字")
            if w < 0:
                raise HTTPException(400, f"维度 {k} 的权重不能为负")
            d["weight"] = w
        grades = value.get("grades") or {}
        try:
            value["grades"] = {g: float(v) for g, v in grades.items()}
        except (TypeError, ValueError):
            raise HTTPException(400, "等级阈值必须是数字")
    return value


class SettingBody(BaseModel):
    value: dict


@router.put("/settings/{key}")
def put_setting(key: str, body: SettingBody, me: CurrentUser = Depends(require_admin)) -> dict:
    if key not in EDITABLE:
        raise HTTPException(404)
    value = _validate(key, body.value)
    with session() as s:
        row = s.get(AppSetting, key) or AppSetting(key=key)
        row.value = value
        row.updated_by = me.username
        s.add(row)
    clear_cache()
    return {"ok": True}


@router.delete("/settings/{key}")
def reset_setting(key: str) -> dict:
    """恢复为 config/*.yaml 文件中的默认值。"""
    if key not in EDITABLE:
        raise HTTPException(404)
    with session() as s:
        row = s.get(AppSetting, key)
        if row:
            s.delete(row)
    clear_cache()
    return {"ok": True}


@router.get("/prompt-preview")
def prompt_preview() -> dict:
    from ..llm.scorer import system_prompt
    return {"system_prompt": system_prompt(), "company": company(), "scoring": scoring()}
