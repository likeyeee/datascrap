"""前台接口：所有登录用户可用（运营、招商、浏览器插件）。"""
from __future__ import annotations

import io
import json
import tempfile
import zipfile
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from .. import analytics, auth
from ..auth import CurrentUser, current_user
from ..config import ROOT, scoring
from ..db import Discovery, FollowUp, Store, User, session
from ..domains import add_candidates, normalize
from ..exporter import build_query, export_rows, query_stores, store_row, user_names
from ..llm.scorer import CHINESE_TYPES

router = APIRouter(prefix="/api", tags=["public"])
OUTREACH_STATUSES = ["未联系", "已联系", "有回复", "洽谈中", "已合作", "不合适"]
EXTENSION_DIR = ROOT / "extension"


def compute_stats() -> dict:
    with session() as s:
        by_status = dict(s.execute(select(Store.status, func.count()).group_by(Store.status)).all())
    return {"status": by_status, "total": sum(by_status.values())}


@router.get("/meta")
def meta(user: CurrentUser = Depends(current_user)) -> dict:
    dims = {k: v.get("label", k) for k, v in scoring().get("dimensions", {}).items()}
    with session() as s:
        cats = s.scalars(select(Store.platform).where(Store.status == "scored").distinct()).all()
    return {"outreach_statuses": OUTREACH_STATUSES, "chinese_types": CHINESE_TYPES, "dimensions": dims,
            "platforms": sorted(c for c in cats if c), "user": user.public()}


@router.get("/stats")
def stats(_: CurrentUser = Depends(current_user)) -> dict:
    return compute_stats()


@router.get("/overview")
def overview(days: int = Query(30, ge=7, le=180), user: CurrentUser = Depends(current_user)) -> dict:
    data = analytics.overview(days)
    if user.id:
        with session() as s:
            mine = dict(s.execute(select(Store.outreach_status, func.count())
                                  .where(Store.owner_id == user.id).group_by(Store.outreach_status)).all())
        data["mine"] = {"total": sum(mine.values()), "by_status": mine}
    return data


def _filters(q, status, grade, chinese_type, platform, min_score, outreach_status, sort, scope, category,
             user: CurrentUser) -> dict:
    f = dict(q=q, status=status, grade=grade, chinese_type=chinese_type, platform=platform, min_score=min_score,
             outreach_status=outreach_status, sort=sort, category=category)
    if status and status != "scored" and not user.is_admin:
        raise HTTPException(403, "只有管理员可以查看未打分的站点")
    if scope == "mine":
        f["owner_id"] = user.id or -1
    elif scope == "unowned":
        f["unowned"] = True
    elif scope == "starred":
        f["starred"] = True
    return f


@router.get("/stores")
def list_stores(q: str | None = None, status: str | None = None, grade: str | None = None,
                chinese_type: str | None = None, platform: str | None = None, min_score: float | None = None,
                outreach_status: str | None = None, sort: str = "score", scope: str | None = None,
                category: str | None = None, page: int = Query(1, ge=1), size: int = Query(30, ge=1, le=200),
                user: CurrentUser = Depends(current_user)) -> dict:
    stmt = build_query(**_filters(q, status, grade, chinese_type, platform, min_score, outreach_status, sort,
                                  scope, category, user))
    users = user_names()
    with session() as s:
        total = s.scalar(select(func.count()).select_from(stmt.order_by(None).subquery()))
        rows = [store_row(st, users) for st in s.scalars(stmt.offset((page - 1) * size).limit(size))]
    return {"total": total, "page": page, "size": size, "items": rows}


@router.get("/stores/{store_id}")
def get_store(store_id: int, user: CurrentUser = Depends(current_user)) -> dict:
    users = user_names()
    with session() as s:
        st = s.get(Store, store_id)
        if not st or (st.status != "scored" and not user.is_admin):
            raise HTTPException(404, "线索不存在")
        disc = s.execute(select(Discovery.source, Discovery.detail, Discovery.created_at)
                         .where(Discovery.store_id == store_id).order_by(Discovery.id.desc()).limit(20)).all()
        cd = st.crawl_data or {}
        return {
            **store_row(st, users),
            "error": st.error, "currency": st.currency, "marketing": st.marketing, "socials_map": st.socials,
            "cn_signals": st.cn_signals, "cn_location": st.cn_location, "llm_result": st.llm_result,
            "llm_model": st.llm_model, "tags": st.tags, "scores_map": st.scores or {},
            "products": (cd.get("products") or [])[:24] or [{"title": t} for t in (cd.get("product_slugs") or [])[:24]],
            "product_types": cd.get("product_types"),
            "description": cd.get("description"),
            "pages": cd.get("pages"),
            "domain_registration": cd.get("rdap"),
            "can_edit": user.is_admin or st.owner_id in (None, user.id),
            "discoveries": [{"source": a, "detail": b, "at": c.isoformat(timespec="minutes")} for a, b, c in disc],
        }


class StorePatch(BaseModel):
    outreach_status: str | None = None
    notes: str | None = None
    tags: list[str] | None = None
    starred: bool | None = None


def _log(s, store_id: int, user: CurrentUser, action: str, content: str | None) -> None:
    s.add(FollowUp(store_id=store_id, user_id=user.id, action=action, content=content))


def _editable(st: Store | None, user: CurrentUser) -> Store:
    if not st:
        raise HTTPException(404, "线索不存在")
    if st.owner_id and st.owner_id != user.id and not user.is_admin:
        raise HTTPException(403, "该线索已被其他同事认领")
    return st


@router.patch("/stores/{store_id}")
def patch_store(store_id: int, body: StorePatch, user: CurrentUser = Depends(current_user)) -> dict:
    if body.outreach_status and body.outreach_status not in OUTREACH_STATUSES:
        raise HTTPException(400, f"跟进状态只能是：{'、'.join(OUTREACH_STATUSES)}")
    with session() as s:
        st = s.get(Store, store_id)
        if body.starred is not None and set(body.model_dump(exclude_none=True)) == {"starred"}:
            if not st:
                raise HTTPException(404)
            st.starred = body.starred       # 星标任何人都可以设置
            return {"ok": True}
        st = _editable(st, user)
        if body.outreach_status and body.outreach_status != st.outreach_status:
            _log(s, st.id, user, "status", f"{st.outreach_status} → {body.outreach_status}")
            st.outreach_status = body.outreach_status
            if st.owner_id is None and user.id:
                st.owner_id = user.id       # 推进状态即自动认领
                _log(s, st.id, user, "claim", None)
        if body.notes is not None and body.notes != (st.notes or ""):
            st.notes = body.notes
        if body.tags is not None:
            st.tags = body.tags
        if body.starred is not None:
            st.starred = body.starred
    return {"ok": True}


@router.post("/stores/{store_id}/claim")
def claim(store_id: int, user: CurrentUser = Depends(current_user)) -> dict:
    with session() as s:
        st = _editable(s.get(Store, store_id), user)
        if user.id is None:
            raise HTTPException(400, "系统令牌不能认领线索")
        st.owner_id = user.id
        _log(s, st.id, user, "claim", None)
    return {"ok": True}


@router.post("/stores/{store_id}/release")
def release(store_id: int, user: CurrentUser = Depends(current_user)) -> dict:
    with session() as s:
        st = _editable(s.get(Store, store_id), user)
        st.owner_id = None
        _log(s, st.id, user, "release", None)
    return {"ok": True}


class NoteBody(BaseModel):
    content: str = Field(min_length=1, max_length=5000)


@router.get("/stores/{store_id}/followups")
def followups(store_id: int, _: CurrentUser = Depends(current_user)) -> list[dict]:
    users = user_names()
    with session() as s:
        rows = s.scalars(select(FollowUp).where(FollowUp.store_id == store_id)
                         .order_by(FollowUp.created_at.desc()).limit(100)).all()
        return [{"id": r.id, "user": users.get(r.user_id, "系统"), "action": r.action, "content": r.content,
                 "at": r.created_at.isoformat(timespec="minutes")} for r in rows]


@router.post("/stores/{store_id}/followups")
def add_followup(store_id: int, body: NoteBody, user: CurrentUser = Depends(current_user)) -> dict:
    with session() as s:
        if not s.get(Store, store_id):
            raise HTTPException(404)
        _log(s, store_id, user, "note", body.content.strip())
    return {"ok": True}


@router.get("/export")
def export(fmt: str = "xlsx", q: str | None = None, grade: str | None = None, chinese_type: str | None = None,
           platform: str | None = None, min_score: float | None = None, outreach_status: str | None = None,
           sort: str = "score", scope: str | None = None, category: str | None = None, status: str | None = None,
           user: CurrentUser = Depends(current_user)) -> FileResponse:
    rows = query_stores(**_filters(q, status, grade, chinese_type, platform, min_score, outreach_status, sort,
                                   scope, category, user))
    suffix = ".csv" if fmt == "csv" else ".xlsx"
    tmp = Path(tempfile.mkstemp(suffix=suffix)[1])
    export_rows(rows, tmp)
    return FileResponse(tmp, filename=f"leads{suffix}")


# ---------- 浏览器插件 ----------
class IngestBody(BaseModel):
    domains: list[str] = Field(default_factory=list, max_length=2000)
    source: str = "extension"
    context: str | None = None
    priority: int = Field(8, ge=-5, le=20)


@router.post("/ingest")
def ingest(body: IngestBody, user: CurrentUser = Depends(current_user)) -> dict:
    source = (body.source or "extension")[:50]
    detail = f"{user.username}: {body.context or ''}"
    return {"received": len(body.domains), "added": add_candidates(body.domains, source, detail, body.priority)}


def _brief(st: Store) -> dict:
    return {"exists": True, "id": st.id, "domain": st.domain, "status": st.status, "grade": st.grade,
            "total_score": st.total_score, "chinese_type": st.chinese_type, "main_products": st.main_products,
            "promotion_channels": "、".join(st.promotion_channels or []), "outreach_status": st.outreach_status}


@router.get("/lookup")
def lookup(domain: str, _: CurrentUser = Depends(current_user)) -> dict:
    d = normalize(domain)
    with session() as s:
        st = s.scalar(select(Store).where(Store.domain == d)) if d else None
        return _brief(st) if st else {"exists": False, "domain": d}


class BatchBody(BaseModel):
    domains: list[str] = Field(default_factory=list, max_length=300)


@router.post("/lookup_batch")
def lookup_batch(body: BatchBody, _: CurrentUser = Depends(current_user)) -> dict:
    """插件在搜索结果页标注评级用：返回 {原始域名: 简要信息}，只包含已入库的站点。"""
    mapping = {raw: normalize(raw) for raw in body.domains}
    wanted = {d for d in mapping.values() if d}
    if not wanted:
        return {}
    with session() as s:
        found = {st.domain: _brief(st) for st in s.scalars(select(Store).where(Store.domain.in_(wanted)))}
    return {raw: found[d] for raw, d in mapping.items() if d in found}


@router.get("/extension.zip")
def extension_zip(request: Request, user: CurrentUser = Depends(current_user)) -> StreamingResponse:
    """下载已预置服务器地址和个人令牌的插件包。会生成新的个人令牌，旧令牌失效。"""
    if user.id is None:
        raise HTTPException(400, "请用个人账号登录后下载")
    if not EXTENSION_DIR.exists():
        raise HTTPException(500, "服务器上缺少 extension 目录")
    token = auth.new_api_token(user.id)
    server = str(request.base_url).rstrip("/")
    if request.headers.get("x-forwarded-proto") == "https":
        server = server.replace("http://", "https://", 1)
    preset = {"server": server, "token": token, "user": user.display_name or user.username}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for f in EXTENSION_DIR.rglob("*"):
            if f.is_file() and f.name != "config.js" and f.suffix != ".py":
                z.write(f, f"store-scout-extension/{f.relative_to(EXTENSION_DIR).as_posix()}")
        z.writestr("store-scout-extension/config.js",
                   "// 由服务器生成：预置的服务器地址与个人令牌，请勿外传\n"
                   f"self.SCOUT_PRESET = {json.dumps(preset, ensure_ascii=False)};\n")
    buf.seek(0)
    return StreamingResponse(buf, media_type="application/zip",
                             headers={"Content-Disposition": 'attachment; filename="store-scout-extension.zip"'})


@router.get("/me/summary")
def my_summary(user: CurrentUser = Depends(current_user)) -> dict:
    with session() as s:
        u = s.get(User, user.id) if user.id else None
        return {**user.public(), "has_token": bool(u and u.api_token_hash),
                "last_login": u.last_login.isoformat(timespec="minutes") if u and u.last_login else None}
