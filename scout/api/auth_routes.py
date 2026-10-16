"""登录、登出、首次初始化、修改密码、个人令牌。"""
from __future__ import annotations

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from .. import auth
from ..db import User, session

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginBody(BaseModel):
    username: str
    password: str


class SetupBody(BaseModel):
    system_token: str
    username: str
    password: str
    display_name: str | None = None


class PasswordBody(BaseModel):
    old_password: str
    new_password: str


def _set_cookie(resp: Response, request: Request, user: User) -> None:
    secure = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
    resp.set_cookie(auth.COOKIE_NAME, auth.make_session(user), max_age=auth.SESSION_DAYS * 86400,
                    httponly=True, samesite="lax", secure=secure, path="/")


def _optional_user(scout_session: str | None = Cookie(None)) -> auth.CurrentUser | None:
    if not scout_session:
        return None
    try:
        return auth.current_user(scout_session=scout_session, x_token=None, token=None)
    except HTTPException:
        return None


@router.get("/state")
def state(user: auth.CurrentUser | None = Depends(_optional_user)) -> dict:
    """登录页用：是否需要初始化管理员、当前是否已登录。"""
    return {"needs_setup": auth.user_count() == 0, "user": user.public() if user else None}


@router.post("/setup")
def setup(body: SetupBody, request: Request, response: Response) -> dict:
    """首次使用：凭 .env 中的 API_TOKEN 创建第一个管理员。已有用户后不可用。"""
    if auth.user_count() > 0:
        raise HTTPException(400, "系统已初始化，请直接登录")
    if not auth.system_token_ok(body.system_token):
        raise HTTPException(403, "系统令牌不正确（见服务器 .env 中的 API_TOKEN，且长度需不少于 16 位）")
    u = auth.create_user(body.username, body.password, "admin", body.display_name)
    _set_cookie(response, request, u)
    return {"ok": True, "user": auth.CurrentUser(u.id, u.username, u.role, u.display_name).public()}


@router.post("/login")
def login(body: LoginBody, request: Request, response: Response) -> dict:
    u = auth.login(body.username, body.password)
    _set_cookie(response, request, u)
    return {"ok": True, "user": auth.CurrentUser(u.id, u.username, u.role, u.display_name).public()}


@router.post("/logout")
def logout(response: Response) -> dict:
    response.delete_cookie(auth.COOKIE_NAME, path="/")
    return {"ok": True}


@router.get("/me")
def me(user: auth.CurrentUser = Depends(auth.current_user)) -> dict:
    return user.public()


@router.post("/password")
def change_password(body: PasswordBody, request: Request, response: Response,
                    user: auth.CurrentUser = Depends(auth.current_user)) -> dict:
    if user.id is None:
        raise HTTPException(400, "系统令牌不能修改密码")
    auth.validate_password(body.new_password)
    with session() as s:
        u = s.get(User, user.id)
        if not auth.verify_password(body.old_password, u.password_hash):
            raise HTTPException(400, "原密码不正确")
        u.password_hash = auth.hash_password(body.new_password)
        u.session_version += 1      # 其他设备上的登录随之失效
        s.flush()
        s.expunge(u)
    _set_cookie(response, request, u)
    return {"ok": True}


@router.post("/token")
def regenerate_token(user: auth.CurrentUser = Depends(auth.current_user)) -> dict:
    """生成新的插件个人令牌（旧令牌立即失效）。令牌只在此时返回一次。"""
    if user.id is None:
        raise HTTPException(400, "系统令牌不需要个人令牌")
    return {"token": auth.new_api_token(user.id)}
