"""单个站点的完整采集流程。"""
from __future__ import annotations

import asyncio
import logging
from urllib.parse import urlsplit

import httpx

from ..config import settings
from ..domains import PLATFORM_SUBDOMAIN_SUFFIXES, normalize
from . import cn, dnsinfo, extract, products
from .fetcher import Fetcher, RobotsBlocked

log = logging.getLogger(__name__)

# 访问过程中可能出现的终态
NOT_STORE = "not_store"
NOT_TARGET = "not_target"
BLOCKED = "blocked"
DEAD = "dead"
# 这些状态码视为临时故障，稍后重试；其余 4xx/5xx 视为终态
RETRYABLE_STATUS = {408, 425, 429, 500, 502, 503, 504, 520, 521, 522, 523, 524}
FAILED = "failed"
CRAWLED = "crawled"


async def crawl(f: Fetcher, domain: str) -> dict:
    """返回 {status, domain, final_domain, ...字段}。不写数据库。"""
    cfg = settings()["crawler"]
    targets = [c.upper() for c in cfg.get("target_countries") or []]
    out: dict = {"domain": domain, "status": FAILED}
    is_platform_sub = domain.endswith(PLATFORM_SUBDOMAIN_SUFFIXES)

    # 1. 首页（已关店返回 404；平台子域名通常跳转到店铺自有域名）
    home = None
    for scheme in ("https", "http"):
        try:
            home = await f.get(f"{scheme}://{domain}/")
            if home.ok:
                break
        except RobotsBlocked:
            out.update(status=BLOCKED, error="robots.txt 禁止抓取首页")
            return out
        except (httpx.HTTPError, OSError) as e:
            out["error"] = f"{type(e).__name__}: {e}"[:300]
            home = None
    if home is not None and not home.ok and home.status not in RETRYABLE_STATUS:
        if home.status in (401, 403):
            out.update(status=BLOCKED, error=f"站点拒绝访问（HTTP {home.status}）")
        else:
            out.update(status=DEAD, error=f"站点不存在或已关闭（HTTP {home.status}）")
        return out
    if home is None or not home.ok:
        out["error"] = out.get("error") or f"HTTP {home.status if home else '无响应'}"
        return out

    host = home.host
    final = normalize(host) or domain
    out["final_domain"] = final
    out["url"] = f"https://{host}/"
    if final != domain:
        out.update(status="alias", alias_of=final)
        return out
    html = home.text
    if is_platform_sub:
        # 平台子域名可能不跳转，但 canonical 指向店铺自有域名
        canon = normalize(extract.canonical_host(html) or "")
        if canon and canon != domain and not canon.endswith(PLATFORM_SUBDOMAIN_SUFFIXES):
            out.update(status="alias", alias_of=canon)
            return out

    platform = extract.detect_platform(html, home.headers)
    if platform is None and not extract.looks_like_store(html):
        out.update(status=NOT_STORE, error="未识别到电商特征")
        return out
    out["platform"] = platform or "custom"
    out["name"] = extract.title_of(html)
    base = f"https://{host}"

    # 2. 店铺元信息（国家/币种）。meta.json 有单独限流，失败时用页面中的店铺本币判断
    meta: dict = {}
    if platform == "shopify":
        meta = await products.shopify_meta(f, base) or {}
        out["name"] = meta.get("name") or out["name"]
        out["country"] = meta.get("country")
        out["currency"] = meta.get("currency") or extract.shopify_base_currency(html)
        out["city"] = meta.get("city")
        out["province"] = meta.get("province")
        real = normalize(meta.get("domain") or "")
        if is_platform_sub and real and real != domain and not real.endswith(PLATFORM_SUBDOMAIN_SUFFIXES):
            out.update(status="alias", alias_of=real)
            return out
    # 尽早排除非目标国家，避免继续抓取
    if targets and out.get("country") and out["country"].upper() not in targets:
        out["status"] = NOT_TARGET
        return out
    if targets == ["US"] and not out.get("country") and out.get("currency") not in (None, "USD") \
            and not extract.extract_us_addresses(extract.visible_text(html)):
        out["status"] = NOT_TARGET
        return out

    # 4. 关键页面
    link_list = extract.links(html, home.url)
    page_urls = extract.pick_pages(link_list, host, platform)
    pages_html: dict[str, str] = {"home": html}
    max_pages = int(cfg["max_pages_per_store"])
    for kind, url in list(page_urls.items())[:max_pages]:
        try:
            p = await f.get(url)
            if p.ok and len(p.text) > 200:
                pages_html[kind] = p.text
        except (httpx.HTTPError, RobotsBlocked, OSError):
            continue

    all_html = "\n".join(pages_html.values())
    pages_text = {k: extract.visible_text(v, 30000) for k, v in pages_html.items()}
    all_text = "\n".join(pages_text.values())
    pages_text = _strip_boilerplate(pages_text)

    # 5. 商品
    plist: list[dict] = []
    if platform == "shopify":
        plist = await products.shopify_atom(f, base) or await products.shopify_products(f, base, pages=1)
    elif platform == "woocommerce":
        plist = await products.woo_products(f, base)
    if not plist:
        plist = [{"title": p["title"], "price": p["price"], "type": p.get("category")}
                 for p in extract.jsonld_products(html)]
    summary = products.summarize(plist)
    count = meta.get("published_products_count")
    sitemap: dict = {}
    if not count or not plist:
        sitemap = await products.sitemap_products(f, base)
        count = count or sitemap.get("count") or (len(plist) if plist else None)
        canon = normalize(sitemap.get("canonical_host") or "")
        if is_platform_sub and canon and canon != domain and not canon.endswith(PLATFORM_SUBDOMAIN_SUFFIXES):
            out.update(status="alias", alias_of=canon)
            return out
    if not plist and sitemap.get("sample_urls"):
        # 没有商品接口的平台：抓 2 个商品页，从结构化数据中取价格
        for url in sitemap["sample_urls"][:2]:
            try:
                p = await f.get(url)
            except (httpx.HTTPError, RobotsBlocked, OSError):
                continue
            if p.ok:
                plist += [{"title": x["title"], "price": x["price"], "type": x.get("category")}
                          for x in extract.jsonld_products(p.text)]
        summary = products.summarize(plist)
    out.update(
        product_count=count,
        price_min=summary["price_min"], price_max=summary["price_max"], price_median=summary["price_median"],
        last_product_update=summary["last_update"] or sitemap.get("last_update"),
    )

    # 6. 联系方式、推广渠道
    emails = extract.extract_emails(all_html)
    phones = extract.extract_phones(all_text)
    us_addrs = extract.extract_us_addresses(all_text)
    socials = extract.extract_socials(all_html)
    marketing = extract.detect_marketing(all_html)
    out.update(emails=emails, phones=phones, socials=socials, marketing=marketing)

    # 7. 美区判定（非 Shopify 店铺没有 meta.json，用币种和地址推断）
    if not out.get("currency"):
        out["currency"] = _guess_currency(all_text)
    if not out.get("country") and us_addrs:
        out["country"] = "US"
    if us_addrs and not out.get("province"):
        out["city"], out["province"] = us_addrs[0]["city"], us_addrs[0]["state"]
    if targets == ["US"] and not out.get("country") and out.get("currency") not in (None, "USD"):
        out["status"] = NOT_TARGET
        return out
    if targets and out.get("country") and out["country"].upper() not in targets:
        out["status"] = NOT_TARGET
        return out

    # 8. DNS / RDAP
    ns, rd = [], {}
    if cfg.get("dns_lookup", True) and not is_platform_sub:
        ns = await dnsinfo.nameservers(final)
    if cfg.get("rdap_lookup", True) and not is_platform_sub:
        try:
            rd = await dnsinfo.rdap(f, final)
        except Exception as e:  # RDAP 失败不影响主流程
            log.debug("rdap %s: %s", final, e)

    # 9. 华人识别
    cn_res = cn.analyze({
        "platform": platform, "html": all_html, "text": all_text, "pages_text": pages_text,
        "emails": emails, "phones": phones, "us_addresses": us_addrs, "meta": meta,
        "ns": ns, "rdap": rd,
        "cn_chars": extract.count_chinese_chars(all_text + "\n" + extract.attr_text(all_html)),
        "cn_source_chars": extract.count_chinese_chars(all_html),
    })
    out.update(cn_rule_score=cn_res.score, cn_signals=cn_res.signals, cn_location=cn_res.location)

    out["crawl_data"] = {
        "description": extract.meta_description(html),
        "pages": {k: page_urls.get(k, out["url"]) for k in pages_html},
        "pages_text": pages_text,
        "products": summary["sample"],
        "product_types": summary["top_types"],
        "vendors": summary["vendors"],
        "new_last_90d": summary["new_last_90d"],
        "updated_last_90d": sitemap.get("updated_last_90d"),
        "product_slugs": sitemap.get("titles") or [],
        "us_addresses": us_addrs,
        "names": cn_res.names,
        "ns": ns,
        "rdap": rd,
        "outlinks": extract.external_domains(link_list, host),
    }
    out["status"] = CRAWLED
    return out


def _strip_boilerplate(pages_text: dict[str, str], limit: int = 5000) -> dict[str, str]:
    """去掉各页面共有的导航/页脚行，只保留每页独有的内容。"""
    seen: dict[str, int] = {}
    for text in pages_text.values():
        for line in {l.strip() for l in text.splitlines() if l.strip()}:
            seen[line] = seen.get(line, 0) + 1
    n = len(pages_text)
    out = {}
    for kind, text in pages_text.items():
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        if n > 1:
            lines = [l for l in lines if seen[l] == 1 or (kind == "home" and len(l) > 40)]
        out[kind] = "\n".join(lines)[:limit]
    return out


def _guess_currency(text: str) -> str | None:
    counts = {
        "CAD": text.count("CA$") + text.count("C$"),
        "AUD": text.count("AU$") + text.count("A$"),
        "GBP": text.count("£"),
        "EUR": text.count("€"),
    }
    counts["USD"] = text.count("$") - counts["CAD"] - counts["AUD"]
    best = max(counts, key=counts.get)
    return best if counts[best] > 0 else None


async def crawl_one(domain: str) -> dict:
    """命令行调试用：独立创建抓取器采集一个站点。"""
    async with Fetcher() as f:
        return await crawl(f, domain)


if __name__ == "__main__":  # python -m scout.crawler.pipeline example.com
    import json
    import sys

    res = asyncio.run(crawl_one(sys.argv[1]))
    print(json.dumps(res, ensure_ascii=False, indent=2, default=str))
