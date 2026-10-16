"""商品数据采集：Shopify / WooCommerce 公开接口，以及通用 sitemap 计数。"""
from __future__ import annotations

import html as html_lib
import json
import re
import statistics
from datetime import datetime, timedelta, timezone

from .fetcher import Fetcher


def _parse_dt(v: str | None) -> datetime | None:
    if not v:
        return None
    try:
        dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    except ValueError:
        return None


def summarize(products: list[dict]) -> dict:
    """products: [{title, price, type, vendor, tags, created, updated}]"""
    prices = [p["price"] for p in products if p.get("price")]
    types: dict[str, int] = {}
    for p in products:
        t = (p.get("type") or "").strip()
        if t:
            types[t] = types.get(t, 0) + 1
    updated = [d for d in (p.get("updated") or p.get("created") for p in products) if d]
    recent_cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=90)
    return {
        "sample": [{"title": p.get("title"), "price": p.get("price"), "type": p.get("type")}
                   for p in products[:40]],
        "top_types": sorted(types.items(), key=lambda kv: -kv[1])[:15],
        "vendors": sorted({p["vendor"] for p in products if p.get("vendor")})[:15],
        "price_min": min(prices) if prices else None,
        "price_max": max(prices) if prices else None,
        "price_median": statistics.median(prices) if prices else None,
        "last_update": max(updated) if updated else None,
        "new_last_90d": sum(1 for p in products if p.get("created") and p["created"] >= recent_cutoff),
        "sampled": len(products),
    }


def parse_meta(page) -> dict | None:
    if not page.ok:
        return None
    try:
        data = json.loads(page.text)
    except ValueError:
        return None
    return data if isinstance(data, dict) and data.get("name") is not None else None


async def shopify_meta(f: Fetcher, base: str) -> dict | None:
    try:
        page = await f.get(f"{base}/meta.json", check_robots=False, retries=2)
    except Exception:
        return None
    return parse_meta(page)


async def shopify_products(f: Fetcher, base: str, pages: int = 2) -> list[dict]:
    out: list[dict] = []
    for page in range(1, pages + 1):
        data = await f.get_json(f"{base}/products.json?limit=250&page={page}", retries=0)
        items = (data or {}).get("products") if isinstance(data, dict) else None
        if not items:
            break
        for p in items:
            prices = []
            for v in p.get("variants") or []:
                try:
                    prices.append(float(v.get("price")))
                except (TypeError, ValueError):
                    pass
            tags = p.get("tags")
            out.append({
                "title": p.get("title"),
                "type": p.get("product_type"),
                "vendor": p.get("vendor"),
                "tags": tags if isinstance(tags, list) else (tags or "").split(", "),
                "price": min(prices) if prices else None,
                "created": _parse_dt(p.get("published_at") or p.get("created_at")),
                "updated": _parse_dt(p.get("updated_at")),
            })
        if len(items) < 250:
            break
    return out


_ENTRY_RE = re.compile(r"<entry>(.*?)</entry>", re.S)


def _tag(block: str, name: str) -> str | None:
    m = re.search(rf"<{name}[^>]*>(.*?)</{name}>", block, re.S)
    if not m:
        return None
    v = m.group(1).strip()
    if v.startswith("<![CDATA["):
        v = v[9:-3]
    return html_lib.unescape(v).strip() or None


def parse_shopify_atom(xml: str) -> list[dict]:
    out = []
    for block in _ENTRY_RE.findall(xml):
        prices = [float(p) for p in re.findall(r"<s:price[^>]*>\s*([\d.]+)\s*</s:price>", block)]
        if not prices:
            m = re.search(r"Price:\s*</strong>\s*(?:from\s*)?\$?\s*([\d,]+(?:\.\d+)?)", block)
            if m:
                prices = [float(m.group(1).replace(",", ""))]
        out.append({
            "title": _tag(block, "title"),
            "type": _tag(block, "s:type"),
            "vendor": _tag(block, "s:vendor"),
            "price": min(prices) if prices else None,
            "created": _parse_dt(_tag(block, "published")),
            "updated": _parse_dt(_tag(block, "updated")),
        })
    return out


async def shopify_atom(f: Fetcher, base: str, pages: int = 2) -> list[dict]:
    """Shopify 的 /collections/all.atom 公开商品订阅源，比 products.json 更少被限流。"""
    out: list[dict] = []
    for page in range(1, pages + 1):
        try:
            p = await f.get(f"{base}/collections/all.atom?page={page}")
        except Exception:
            break
        if not p.ok or "<feed" not in p.text[:500]:
            break
        items = parse_shopify_atom(p.text)
        out.extend(items)
        if len(items) < 50:
            break
    return out


async def woo_products(f: Fetcher, base: str) -> list[dict]:
    data = await f.get_json(f"{base}/wp-json/wc/store/v1/products?per_page=100")
    if not isinstance(data, list):
        return []
    out = []
    for p in data:
        prices = p.get("prices") or {}
        price = None
        try:
            unit = int(prices.get("currency_minor_unit", 2))
            price = int(prices.get("price")) / (10 ** unit)
        except (TypeError, ValueError):
            pass
        cats = [c.get("name") for c in p.get("categories") or [] if c.get("name")]
        out.append({"title": p.get("name"), "type": cats[0] if cats else None, "price": price})
    return out


_LOC_RE = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>", re.I)
_IMG_TITLE_RE = re.compile(r"<image:title>\s*(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?\s*</image:title>", re.I | re.S)
_LASTMOD_RE = re.compile(r"<lastmod>\s*([^<\s]+)\s*</lastmod>", re.I)


async def _sitemap_text(f: Fetcher, url: str) -> str | None:
    try:
        page = await f.get(url.replace("&amp;", "&"))
    except Exception:
        return None
    if not page.ok:
        return None
    if page.content[:2] == b"\x1f\x8b":
        import gzip
        try:
            return gzip.decompress(page.content).decode("utf-8", "replace")
        except OSError:
            return None
    return page.text


async def sitemap_products(f: Fetcher, base: str) -> dict:
    """通用兜底：从 sitemap 统计商品数量、取商品标题和最近更新时间。"""
    out: dict = {"count": None, "titles": [], "last_update": None, "canonical_host": None}
    text = await _sitemap_text(f, f"{base}/sitemap.xml")
    if not text:
        return out
    locs = _LOC_RE.findall(text)
    if locs:
        from urllib.parse import urlsplit
        out["canonical_host"] = urlsplit(locs[0]).hostname
    product_xml = []
    if "<sitemapindex" in text.lower():
        for sm in [u for u in locs if "product" in u.lower()][:3]:
            sub = await _sitemap_text(f, sm)
            if sub:
                product_xml.append(sub)
    else:
        product_xml.append(text)
    urls: list[str] = []
    titles: list[str] = []
    lastmods: list[datetime] = []
    for xml in product_xml:
        page_urls = [u for u in _LOC_RE.findall(xml) if "/product" in u.lower()]
        urls.extend(page_urls)
        titles.extend(t.strip() for t in _IMG_TITLE_RE.findall(xml)[:60])
        lastmods.extend(d for d in (_parse_dt(x) for x in _LASTMOD_RE.findall(xml)) if d)
    if not titles:
        for u in urls[:40]:
            m = re.search(r"/products?/([^/?#]+)", u)
            if m:
                titles.append(m.group(1).replace("-", " ")[:80])
    out["count"] = len(urls) or None
    out["titles"] = [html_lib.unescape(t) for t in dict.fromkeys(titles)][:40]
    out["sample_urls"] = urls[:3]
    out["last_update"] = max(lastmods) if lastmods else None
    if lastmods:
        cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=90)
        out["updated_last_90d"] = sum(1 for d in lastmods if d >= cutoff)
    return out
