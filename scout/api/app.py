"""FastAPI 应用：页面路由 + 三组接口（认证 / 前台 / 后台）。

页面：
  /login   登录（首次使用时为“创建管理员”）
  /app     前台：运营、招商人员查看线索、跟进、安装插件
  /admin   后台：管理员监控采集、管理渠道/站点/用户/配置
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from ..db import init_db
from . import admin, auth_routes, public

WEB_DIR = Path(__file__).resolve().parent.parent / "web"


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(title="Store Scout", docs_url="/api/docs", openapi_url="/api/openapi.json", lifespan=lifespan)
# 浏览器插件从 chrome-extension:// 发起请求，使用个人令牌（请求头），不依赖 Cookie
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.include_router(auth_routes.router)
app.include_router(public.router)
app.include_router(admin.router)
app.mount("/static", StaticFiles(directory=WEB_DIR / "static"), name="static")


@app.middleware("http")
async def static_revalidate(request, call_next):
    """静态资源每次向服务器确认是否有更新（配合 ETag，未变化时返回 304），避免升级后浏览器仍用旧脚本。"""
    resp = await call_next(request)
    if request.url.path.startswith("/static/"):
        resp.headers["Cache-Control"] = "no-cache"
    return resp


def _page(name: str) -> HTMLResponse:
    # 页面本身不含数据，前端脚本加载后调用 /api/auth/me 判断登录状态
    return HTMLResponse((WEB_DIR / name).read_text(encoding="utf-8"), headers={"Cache-Control": "no-cache"})


@app.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    return RedirectResponse("/app")


@app.get("/login", include_in_schema=False)
def login_page() -> HTMLResponse:
    return _page("login.html")


@app.get("/app", include_in_schema=False)
def app_page() -> HTMLResponse:
    return _page("app.html")


@app.get("/admin", include_in_schema=False)
def admin_page() -> HTMLResponse:
    return _page("admin.html")
