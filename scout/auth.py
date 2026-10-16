"""账号与权限：密码哈希、登录会话（签名 Cookie）、插件个人令牌。

- 管理员（admin）：后台全部功能
- 普通用户（user）：前台查看数据、跟进线索、使用浏览器插件
- 系统令牌（.env 的 API_TOKEN）：等同管理员，用于脚本调用和首次创建管理员
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time

from fastapi import Cookie, Depends, Header, HTTPException, Query
from sqlalchemy import func, select

from .config import settings
from .db import AppSetting, User, session, utcnow

COOKIE_NAME = "scout_session"
SESSION_DAYS = 14
PBKDF2_ROUNDS = 200_000


# ---------- 密码 ----------
def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ROUNDS)
    return f"pbkdf2${PBKDF2_ROUNDS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, rounds, salt, digest = stored.split("$")
        calc = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(rounds))
        return hmac.compare_digest(calc.hex(), digest)
    except (ValueError, TypeError):
        return False


def validate_password(password: str) -> None:
    if len(password) < 8:
        raise HTTPException(400, "密码至少 8 位")


# ---------- 会话 ----------
_secret_cache: bytes | None = None


def _secret() -> bytes:
    """签名密钥：优先用环境变量 SECRET_KEY，否则首次生成后保存在数据库（多进程共用）。"""
    global _secret_cache
    if _secret_cache:
        return _secret_cache
    env = settings().get("secret_key")
    if env:
        _secret_cache = env.encode()
        return _secret_cache
    with session() as s:
        row = s.get(AppSetting, "_secret_key")
        if row is None:
            row = AppSetting(key="_secret_key", value=secrets.token_hex(32))
            s.add(row)
        _secret_cache = str(row.value).encode()
    return _secret_cache


def make_session(user: User) -> str:
    exp = int(time.time()) + SESSION_DAYS * 86400
    payload = f"{user.id}:{user.session_version}:{exp}"
    sig = hmac.new(_secret(), payload.encode(), hashlib.sha256).hexdigest()
    return base64.urlsafe_b64encode(f"{payload}:{sig}".encode()).decode()


def _parse_session(token: str) -> tuple[int, int] | None:
    try:
        raw = base64.urlsafe_b64decode(token.encode()).decode()
        uid, ver, exp, sig = raw.split(":")
    except (ValueError, UnicodeDecodeError):
        return None
    expected = hmac.new(_secret(), f"{uid}:{ver}:{exp}".encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected) or int(exp) < time.time():
        return None
    return int(uid), int(ver)


# ---------- 个人令牌（浏览器插件） ----------
def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_api_token(user_id: int) -> str:
    token = "sk_" + secrets.token_urlsafe(24)
    with session() as s:
        u = s.get(User, user_id)
        u.api_token_hash = token_hash(token)
    return token


def system_token_ok(token: str) -> bool:
    expected = settings()["api"].get("token") or ""
    # 默认值或过短的系统令牌一律不认，避免未修改配置时被任意访问
    if len(expected) < 16 or expected == "change-me":
        return False
    return hmac.compare_digest(token, expected)


# ---------- 依赖项 ----------
class CurrentUser:
    def __init__(self, id: int | None, username: str, role: str, display_name: str | None = None):
        self.id, self.username, self.role, self.display_name = id, username, role, display_name

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    def public(self) -> dict:
        return {"id": self.id, "username": self.username, "role": self.role,
                "display_name": self.display_name or self.username}


SYSTEM_USER = CurrentUser(None, "system", "admin", "系统令牌")


def current_user(scout_session: str | None = Cookie(None), x_token: str | None = Header(None),
                 token: str | None = Query(None)) -> CurrentUser:
    bearer = x_token or token
    with session() as s:
        if scout_session:
            parsed = _parse_session(scout_session)
            if parsed:
                u = s.get(User, parsed[0])
                if u and u.active and u.session_version == parsed[1]:
                    return CurrentUser(u.id, u.username, u.role, u.display_name)
        if bearer:
            if system_token_ok(bearer):
                return SYSTEM_USER
            u = s.scalar(select(User).where(User.api_token_hash == token_hash(bearer)))
            if u and u.active:
                return CurrentUser(u.id, u.username, u.role, u.display_name)
    raise HTTPException(401, "请先登录")


def require_admin(user: CurrentUser = Depends(current_user)) -> CurrentUser:
    if not user.is_admin:
        raise HTTPException(403, "需要管理员权限")
    return user


def login(username: str, password: str) -> User:
    with session() as s:
        u = s.scalar(select(User).where(User.username == username.strip().lower()))
        if not u or not verify_password(password, u.password_hash):
            raise HTTPException(400, "用户名或密码错误")
        if not u.active:
            raise HTTPException(403, "账号已停用，请联系管理员")
        u.last_login = utcnow()
        s.expunge(u)
        return u


def user_count() -> int:
    with session() as s:
        return s.scalar(select(func.count(User.id))) or 0


def create_user(username: str, password: str, role: str = "user", display_name: str | None = None) -> User:
    username = username.strip().lower()
    if not username or not username.replace("_", "").replace(".", "").replace("-", "").isalnum():
        raise HTTPException(400, "用户名只能包含字母、数字、下划线、点和横线")
    if role not in ("admin", "user"):
        raise HTTPException(400, "角色只能是 admin 或 user")
    validate_password(password)
    with session() as s:
        if s.scalar(select(User).where(User.username == username)):
            raise HTTPException(400, "用户名已存在")
        u = User(username=username, password_hash=hash_password(password), role=role,
                 display_name=(display_name or "").strip() or None, active=True, session_version=1)
        s.add(u)
        s.flush()
        s.expunge(u)
        return u
