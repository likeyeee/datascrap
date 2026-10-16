"""命令行入口：python -m scout <命令>"""
from __future__ import annotations

import asyncio
import csv
import json
import logging
from pathlib import Path

import typer

app = typer.Typer(help="美区独立站采集与合作打分工具", no_args_is_help=True, add_completion=False)


def _logging(verbose: bool = False) -> None:
    logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)


@app.command()
def init() -> None:
    """创建数据库表。"""
    from .db import init_db
    init_db()
    typer.echo("数据库已初始化")


@app.command()
def add(domains: list[str], priority: int = typer.Option(10, help="队列优先级")) -> None:
    """手动添加站点到采集队列。"""
    from .db import init_db
    from .domains import add_candidates
    init_db()
    typer.echo(f"新增 {add_candidates(domains, 'manual', None, priority)} 个")


@app.command("import-csv")
def import_csv(path: Path, column: str = typer.Option("", help="网址所在列名，默认第一列")) -> None:
    """从 CSV 批量导入站点。"""
    from .db import init_db
    from .domains import add_candidates
    init_db()
    with path.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))
    if not rows:
        raise typer.Exit("空文件")
    idx = rows[0].index(column) if column and column in rows[0] else 0
    start = 1 if column else 0
    items = [r[idx] for r in rows[start:] if len(r) > idx]
    typer.echo(f"读取 {len(items)} 行，新增 {add_candidates(items, 'csv', path.name, 5)} 个")


@app.command()
def crawl(domain: str, verbose: bool = False) -> None:
    """采集单个站点并打印结果（不写库，用于调试）。"""
    from .crawler.pipeline import crawl_one
    _logging(verbose)
    res = asyncio.run(crawl_one(domain))
    typer.echo(json.dumps(res, ensure_ascii=False, indent=2, default=str))


@app.command()
def process(domain: str) -> None:
    """对单个站点执行完整流程（采集 + 打分）并写库。"""
    from .crawler.fetcher import Fetcher
    from .crawler.pipeline import crawl
    from .db import Store, init_db, session
    from .domains import add_candidates, normalize
    from .worker import save_crawl
    from sqlalchemy import select

    _logging()
    init_db()
    d = normalize(domain)
    if not d:
        raise typer.Exit("无效域名")
    add_candidates([d], "manual", None, 10)

    async def go():
        with session() as s:
            sid = s.scalar(select(Store.id).where(Store.domain == d))
        async with Fetcher() as f:
            res = await crawl(f, d)
        save_crawl(sid, res)
        typer.echo(f"采集结果：{res.get('status')} {res.get('error') or ''}")
        if res.get("status") == "alias":
            typer.echo(f"跳转到 {res.get('alias_of')}，请对该域名重新执行")
            return
        if res.get("status") != "crawled":
            return
        from .llm.client import DeepSeekClient
        from .llm.scorer import score_store
        client = DeepSeekClient()
        with session() as s:
            st = s.get(Store, sid)
            s.expunge(st)
        fields = await score_store(client, st)
        with session() as s:
            cur = s.get(Store, sid)
            for k, v in fields.items():
                setattr(cur, k, v)
            cur.status = "scored"
            from .db import utcnow
            cur.scored_at = utcnow()
        await client.close()
        typer.echo(json.dumps(fields["llm_result"], ensure_ascii=False, indent=2))
        typer.echo(f"总分 {fields['total_score']}  等级 {fields['grade']}")

    asyncio.run(go())


@app.command()
def discover(source: str) -> None:
    """手动运行一次发现渠道：commoncrawl / crtsh / outlinks / search"""
    from .db import init_db
    from .sources import get_source
    _logging()
    init_db()
    typer.echo(asyncio.run(get_source(source).run()))


@app.command()
def run() -> None:
    """持续运行：发现 + 采集 + 打分 + 定期重爬。"""
    from .scheduler import run_forever
    _logging()
    asyncio.run(run_forever())


@app.command()
def serve(host: str = "0.0.0.0", port: int = 8000) -> None:
    """只启动网站（前台 /app、后台 /admin），不运行采集。"""
    import uvicorn
    from .db import init_db
    _logging()
    init_db()
    uvicorn.run("scout.api:app", host=host, port=port, proxy_headers=True, forwarded_allow_ips="*")


@app.command()
def start(host: str = "0.0.0.0", port: int = 8000) -> None:
    """一键启动：网站 + 自动采集在同一个进程中运行（本地或单机部署推荐）。"""
    import uvicorn
    from .db import init_db
    from .scheduler import run_forever
    _logging()
    init_db()

    async def main() -> None:
        server = uvicorn.Server(uvicorn.Config("scout.api:app", host=host, port=port, proxy_headers=True,
                                               forwarded_allow_ips="*"))
        worker_task = asyncio.create_task(run_forever())
        try:
            await server.serve()
        finally:
            worker_task.cancel()

    typer.echo(f"网站：http://localhost:{port}/app    后台：http://localhost:{port}/admin")
    asyncio.run(main())


@app.command("create-user")
def create_user_cmd(username: str, admin: bool = typer.Option(False, "--admin", help="创建管理员"),
                    display_name: str = typer.Option("", help="显示名称"),
                    password: str = typer.Option(..., prompt=True, hide_input=True, confirmation_prompt=True)) -> None:
    """创建登录账号。"""
    from fastapi import HTTPException

    from .auth import create_user
    from .db import init_db
    init_db()
    try:
        u = create_user(username, password, "admin" if admin else "user", display_name or None)
    except HTTPException as e:
        raise typer.Exit(f"创建失败：{e.detail}")
    typer.echo(f"已创建{'管理员' if admin else '用户'}：{u.username}")


@app.command()
def export(path: Path = Path("stores.xlsx"), min_score: float = 0, grade: str = "",
           chinese_type: str = "") -> None:
    """导出已打分站点到 Excel 或 CSV（按扩展名判断）。"""
    from .exporter import export_rows, query_stores
    rows = query_stores(min_score=min_score, grade=grade or None, chinese_type=chinese_type or None)
    export_rows(rows, path)
    typer.echo(f"已导出 {len(rows)} 条到 {path}")


@app.command()
def stats() -> None:
    """查看各状态数量。"""
    from .api import compute_stats
    from .db import init_db
    init_db()
    typer.echo(json.dumps(compute_stats(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    app()
