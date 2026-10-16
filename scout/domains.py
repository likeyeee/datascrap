"""域名标准化与候选入库。"""
from __future__ import annotations

import re
from functools import lru_cache
from urllib.parse import urlsplit

import tldextract
from sqlalchemy import select

from .config import ROOT, keywords
from .db import Discovery, Store, session, utcnow

_extract = tldextract.TLDExtract(cache_dir=str(ROOT / "data" / "tld_cache"), suffix_list_urls=())

# 建站平台的默认子域名：保留完整主机名，访问后会跳转到店铺自有域名
PLATFORM_SUBDOMAIN_SUFFIXES = ("myshopify.com", "myshoplaza.com", "myshopline.com")
# 平台自身的基础设施子域名（图片、CDN、模板演示站等），不是店铺
_PLATFORM_INFRA_RE = re.compile(
    r"^(?:www|img|image|images|cdn|static|assets|files|media|front|api|admin|app|apps|help|support|docs|"
    r"partners?|developers?|status|checkout|accounts?|login|mail|blog)(?:$|[-.])"
    r"|^layout-assets|^cdn-|^img-|.*-(?:theme|demo)(?:-|$)|^theme-|^demo-",
)


def normalize(raw: str) -> str | None:
    """把 URL / 主机名统一成可注册域名（保留平台子域名），无效则返回 None。"""
    if not raw:
        return None
    raw = raw.strip().lower()
    if "://" not in raw:
        raw = "http://" + raw
    try:
        host = urlsplit(raw).hostname or ""
    except ValueError:
        return None
    host = host.strip(".")
    if not host or not re.fullmatch(r"[a-z0-9.-]+", host) or "." not in host:
        return None
    for suffix in PLATFORM_SUBDOMAIN_SUFFIXES:
        if host.endswith("." + suffix):
            sub = host[: -len(suffix) - 1].split(".")[-1]
            if not sub or _PLATFORM_INFRA_RE.match(sub):
                return None
            return f"{sub}.{suffix}"
    ext = _extract(host)
    if not ext.domain or not ext.suffix:
        return None
    return f"{ext.domain}.{ext.suffix}"


@lru_cache
def _blacklist() -> frozenset[str]:
    return frozenset(keywords().get("domain_blacklist", []))


def is_blacklisted(domain: str) -> bool:
    if domain in PLATFORM_SUBDOMAIN_SUFFIXES:
        return True
    if any(domain.endswith("." + s) for s in PLATFORM_SUBDOMAIN_SUFFIXES):
        return False
    return domain in _blacklist()


def add_candidates(items: list[str], source: str, detail: str | None = None, priority: int = 0) -> int:
    """批量登记候选站点，返回新增数量。已存在的站点只记录一次发现日志。"""
    domains = []
    seen = set()
    for raw in items:
        d = normalize(raw)
        if d and d not in seen and not is_blacklisted(d):
            seen.add(d)
            domains.append(d)
    if not domains:
        return 0
    added = 0
    with session() as s:
        existing = {
            st.domain: st
            for st in s.scalars(select(Store).where(Store.domain.in_(domains)))
        }
        for d in domains:
            st = existing.get(d)
            if st is None:
                st = Store(domain=d, source=source, priority=priority, discovered_at=utcnow())
                s.add(st)
                s.flush()
                added += 1
            elif priority > st.priority:
                st.priority = priority
            s.add(Discovery(store_id=st.id, source=source, detail=(detail or "")[:500]))
    return added
