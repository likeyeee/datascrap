"""从 HTML 中提取平台、推广渠道、联系方式等信号。全部是纯函数，便于测试。"""
from __future__ import annotations

import json
import re
from urllib.parse import urljoin, urlsplit

from selectolax.lexbor import LexborHTMLParser as HTMLParser

# ---------- 建站平台 ----------
# 顺序有意义：国产 SaaS 放在前面，避免被通用特征误判
PLATFORM_FINGERPRINTS: list[tuple[str, list[str]]] = [
    ("shoplazza", ["cdn.shoplazza.com", "shoplazza", "myshoplaza.com"]),
    ("shopline", ["myshopline.com", "shopline.com", "shopline-"]),
    ("shopyy", ["shopyy"]),
    ("ueeshop", ["ueeshop"]),
    ("xshoppy", ["xshoppy"]),
    ("funpinpin", ["funpinpin"]),
    ("shopbase", ["onshopbase.com", "shopbase"]),
    ("shopify", ["cdn.shopify.com", "shopify.theme", "myshopify.com", "shopify-section"]),
    ("woocommerce", ["wp-content/plugins/woocommerce", "woocommerce-"]),
    ("bigcommerce", ["cdn11.bigcommerce.com", "bigcommerce.com/s-"]),
    ("magento", ["mage/cookies", "magento_", "/static/version"]),
    ("wix", ["static.wixstatic.com", "wix-ecommerce", "x-wix-"]),
    ("squarespace", ["static1.squarespace.com", "squarespace-commerce"]),
    ("prestashop", ["prestashop"]),
    ("ecwid", ["app.ecwid.com", "ecwid"]),
    ("opencart", ["catalog/view/theme", "route=product"]),
    ("weebly", ["editmysite.com"]),
]

STORE_HINTS = ["add to cart", "add-to-cart", "addtocart", '"@type":"product"', '"@type": "product"',
               "/cart", "checkout", "shopping bag", "buy now"]


def detect_platform(html: str, headers: dict[str, str]) -> str | None:
    h = html.lower()
    hdr = " ".join(f"{k}:{v}" for k, v in headers.items()).lower()
    if "x-shopid" in hdr or "x-shopify-stage" in hdr or "powered-by:shopify" in hdr.replace(" ", ""):
        return "shopify"
    for name, marks in PLATFORM_FINGERPRINTS:
        if any(m in h or m in hdr for m in marks):
            return name
    return None


def looks_like_store(html: str) -> bool:
    h = html.lower()
    return sum(1 for m in STORE_HINTS if m in h) >= 2


# ---------- 推广/营销工具 ----------
MARKETING_PATTERNS: dict[str, dict[str, str]] = {
    "ads": {
        "Meta 广告像素": r"connect\.facebook\.net|fbq\(",
        "TikTok 广告像素": r"analytics\.tiktok\.com|ttq\.(?:load|page)",
        "Google Ads": r"googleadservices\.com|\bAW-\d{8,}",
        "Pinterest 广告": r"s\.pinimg\.com/ct|pintrk\(",
        "Snapchat 广告": r"sc-static\.net/scevent|snaptr\(",
        "Bing 广告": r"bat\.bing\.com",
        "Reddit 广告": r"redditstatic\.com/ads|rdt\('init",
        "X/Twitter 广告": r"static\.ads-twitter\.com|twq\(",
    },
    "analytics": {
        "Google Analytics": r"google-analytics\.com|gtag/js\?id=G-",
        "Google Tag Manager": r"googletagmanager\.com/gtm\.js",
        "Microsoft Clarity": r"clarity\.ms",
        "Hotjar": r"static\.hotjar\.com",
    },
    "email_sms": {
        "Klaviyo": r"klaviyo",
        "Omnisend": r"omnisend",
        "Mailchimp": r"chimpstatic|mailchimp",
        "Attentive": r"attn\.tv|attentivemobile",
        "Postscript": r"postscript\.io",
        "Privy": r"privy\.com|widget\.privy",
        "Sendlane": r"sendlane",
    },
    "affiliate_influencer": {
        "Shopify Collabs": r"collabs\.shopify|shopify-collabs",
        "Refersion": r"refersion",
        "Impact": r"impactcdn|impact\.com",
        "UpPromote": r"uppromote|secomapp",
        "GoAffPro": r"goaffpro",
        "Social Snowball": r"socialsnowball",
        "ShareASale": r"shareasale",
        "Awin": r"awin1\.com|dwin1\.com",
        "Aspire": r"aspireiq|aspire\.io",
        "GRIN": r"grin\.co\b",
    },
    "reviews": {
        "Judge.me": r"judge\.me",
        "Yotpo": r"yotpo",
        "Loox": r"loox\.io",
        "Stamped": r"stamped\.io",
        "Okendo": r"okendo",
        "Reviews.io": r"reviews\.io",
        "Trustpilot": r"trustpilot",
    },
    "payments": {
        "PayPal": r"paypal",
        "Shop Pay": r"shop-pay|shopify-payment-button",
        "Klarna": r"klarna",
        "Afterpay": r"afterpay",
        "Affirm": r"affirm\.com",
        "Sezzle": r"sezzle",
    },
    "dropship": {
        "DSers": r"dsers",
        "CJ Dropshipping": r"cjdropshipping",
        "Zendrop": r"zendrop",
        "AutoDS": r"autods",
        "Spocket": r"spocket",
    },
}
_MARKETING_RE = {cat: {name: re.compile(p, re.I) for name, p in pats.items()}
                 for cat, pats in MARKETING_PATTERNS.items()}


def detect_marketing(html: str) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for cat, pats in _MARKETING_RE.items():
        hits = [name for name, rx in pats.items() if rx.search(html)]
        if hits:
            out[cat] = hits
    return out


# ---------- 社媒 ----------
SOCIAL_RE = {
    "instagram": re.compile(r"https?://(?:www\.)?instagram\.com/([A-Za-z0-9_.]{2,30})/?(?=[\"'?#\s<]|$)", re.I),
    "tiktok": re.compile(r"https?://(?:www\.)?tiktok\.com/@([A-Za-z0-9_.]{2,30})", re.I),
    "facebook": re.compile(r"https?://(?:www\.|m\.)?facebook\.com/(?!sharer|share|tr\b|tr\?|plugins|dialog)([A-Za-z0-9_.-]{2,60})/?(?=[\"'?#\s<]|$)", re.I),
    "youtube": re.compile(r"https?://(?:www\.)?youtube\.com/((?:@|c/|channel/|user/)[A-Za-z0-9_.-]{2,60})", re.I),
    "pinterest": re.compile(r"https?://(?:www\.)?pinterest\.com/(?!pin/)([A-Za-z0-9_]{2,30})/?(?=[\"'?#\s<]|$)", re.I),
    "x": re.compile(r"https?://(?:www\.)?(?:twitter|x)\.com/(?!intent|share|home)([A-Za-z0-9_]{2,15})/?(?=[\"'?#\s<]|$)", re.I),
    "linkedin": re.compile(r"https?://(?:www\.)?linkedin\.com/(company/[A-Za-z0-9_-]{2,60})", re.I),
}
_SOCIAL_SKIP = {"p", "reel", "explore", "accounts", "watch", "embed", "share", "sharer", "plugins",
                "shopify", "wix", "pages", "groups", "events", "hashtag"}


def extract_socials(html: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for net, rx in SOCIAL_RE.items():
        for m in rx.finditer(html):
            handle = m.group(1).strip("/")
            if handle.lower() in _SOCIAL_SKIP:
                continue
            out[net] = m.group(0).rstrip("/\"'")
            break
    return out


# ---------- 联系方式 ----------
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,10}")
_EMAIL_BAD = re.compile(r"\.(?:png|jpe?g|gif|webp|svg|css|js)$|sentry|wixpress|example\.|domain\.com|"
                        r"email\.com|yourstore|shopify\.com|@2x|u003e|godaddy|cloudflare", re.I)
US_PHONE_RE = re.compile(r"(?<!\d)(?:\+?1[\s.-]?)?\(?([2-9]\d{2})\)?[\s.-](\d{3})[\s.-](\d{4})(?!\d)")
CN_PHONE_RE = re.compile(r"(?:\+|00)86[\s-]?1[3-9]\d[\s-]?\d{4}[\s-]?\d{4}|(?:\+|00)852[\s-]?\d{4}[\s-]?\d{4}")
US_STATES = ("AL|AK|AZ|AR|CA|CO|CT|DE|FL|GA|HI|ID|IL|IN|IA|KS|KY|LA|ME|MD|MA|MI|MN|MS|MO|MT|NE|NV|NH|NJ|NM|"
             "NY|NC|ND|OH|OK|OR|PA|RI|SC|SD|TN|TX|UT|VT|VA|WA|WV|WI|WY|DC")
US_ADDR_RE = re.compile(rf"([A-Z][A-Za-z .'-]{{2,40}}),\s*({US_STATES}|California|New York|New Jersey|Texas|Florida|Washington)\.?,?\s+(\d{{5}})(?:-\d{{4}})?")


def extract_emails(html: str) -> list[str]:
    from urllib.parse import unquote

    from ..domains import _extract as tld

    found: dict[str, None] = {}
    for m in EMAIL_RE.finditer(unquote(html)):
        e = m.group(0).lower().strip(".")
        if _EMAIL_BAD.search(e) or len(e) >= 80:
            continue
        ext = tld(e.split("@", 1)[1])
        if not ext.suffix or not ext.domain or ext.domain in ("exaple", "example", "test", "email", "yourdomain"):
            continue
        found[e] = None
    return list(found)[:10]


def extract_phones(text: str) -> list[str]:
    found: dict[str, None] = {}
    for m in CN_PHONE_RE.finditer(text):
        found[re.sub(r"\s+", " ", m.group(0))] = None
    for m in US_PHONE_RE.finditer(text):
        found[f"+1 ({m.group(1)}) {m.group(2)}-{m.group(3)}"] = None
    return list(found)[:6]


def extract_us_addresses(text: str) -> list[dict[str, str]]:
    out = []
    for m in US_ADDR_RE.finditer(text):
        city = m.group(1).split("\n")[-1].strip()
        # 只取逗号前最后几个词作为城市名
        city = " ".join(city.split()[-3:])
        out.append({"city": city, "state": m.group(2), "zip": m.group(3)})
    return out[:5]


# ---------- 文本与链接 ----------
def visible_text(html: str, limit: int = 20000) -> str:
    tree = HTMLParser(html)
    for tag in tree.css("script, style, noscript, svg, iframe, template"):
        tag.decompose()
    body = tree.body or tree.root
    if body is None:
        return ""
    text = body.text(separator="\n")
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text)
    return text.strip()[:limit]


def title_of(html: str) -> str | None:
    tree = HTMLParser(html)
    for sel in ('meta[property="og:site_name"]', 'meta[property="og:title"]'):
        node = tree.css_first(sel)
        if node and node.attributes.get("content"):
            return node.attributes["content"].strip()[:200]
    node = tree.css_first("title")
    return node.text().strip()[:200] if node else None


_SHOPIFY_CURRENCY_RE = re.compile(r'Shopify\.currency\s*=\s*\{\s*"active"\s*:\s*"([A-Z]{3})"\s*,\s*"rate"\s*:\s*"([\d.]+)"')


def shopify_base_currency(html: str) -> str | None:
    """Shopify 页面中的 Shopify.currency；rate 为 1 时 active 即店铺本币（不受访问者地区换算影响）。"""
    m = _SHOPIFY_CURRENCY_RE.search(html)
    if m and float(m.group(2)) == 1.0:
        return m.group(1)
    return None


def canonical_host(html: str) -> str | None:
    tree = HTMLParser(html)
    for sel, attr in (('link[rel="canonical"]', "href"), ('meta[property="og:url"]', "content")):
        node = tree.css_first(sel)
        if node and node.attributes.get(attr):
            host = urlsplit(node.attributes[attr]).hostname
            if host:
                return host
    return None


def attr_text(html: str) -> str:
    """图片 alt/title、图片文件名等页面上不可见但由运营人员填写的文本。"""
    tree = HTMLParser(html)
    parts = []
    for node in tree.css("img"):
        for a in ("alt", "title"):
            if node.attributes.get(a):
                parts.append(node.attributes[a])
        src = node.attributes.get("src") or ""
        parts.append(src.rsplit("/", 1)[-1].split("?")[0])
    return "\n".join(parts)


def meta_description(html: str) -> str | None:
    node = HTMLParser(html).css_first('meta[name="description"]')
    return (node.attributes.get("content") or "").strip()[:500] if node else None


def links(html: str, base_url: str) -> list[tuple[str, str]]:
    """返回 (绝对 URL, 锚文本)。"""
    out = []
    for a in HTMLParser(html).css("a[href]"):
        href = (a.attributes.get("href") or "").strip()
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue
        out.append((urljoin(base_url, href), a.text(strip=True)[:80]))
    return out


PAGE_KINDS = {
    "about": re.compile(r"about|our-story|our_story|who-we-are|story|founder", re.I),
    "contact": re.compile(r"contact", re.I),
    "shipping": re.compile(r"shipping|delivery", re.I),
    "terms": re.compile(r"terms|tos\b", re.I),
    "refund": re.compile(r"refund|return", re.I),
    "privacy": re.compile(r"privacy", re.I),
}
SHOPIFY_DEFAULT_PAGES = {
    "about": "/pages/about-us",
    "contact": "/pages/contact",
    "shipping": "/policies/shipping-policy",
    "terms": "/policies/terms-of-service",
    "refund": "/policies/refund-policy",
    "privacy": "/policies/privacy-policy",
}


def pick_pages(link_list: list[tuple[str, str]], host: str, platform: str | None) -> dict[str, str]:
    chosen: dict[str, str] = {}
    for url, text in link_list:
        parts = urlsplit(url)
        if parts.hostname != host:
            continue
        path = parts.path.lower()
        if "/products/" in path or "/collections/" in path or "/blogs/" in path:
            continue
        for kind, rx in PAGE_KINDS.items():
            if kind not in chosen and (rx.search(path) or rx.search(text)):
                chosen[kind] = url.split("#")[0]
                break
    if platform == "shopify":
        for kind, path in SHOPIFY_DEFAULT_PAGES.items():
            chosen.setdefault(kind, f"https://{host}{path}")
    return chosen


def external_domains(link_list: list[tuple[str, str]], host: str) -> list[str]:
    out: dict[str, None] = {}
    for url, _ in link_list:
        h = urlsplit(url).hostname
        if h and h != host and not h.endswith("." + host):
            out[h] = None
    return list(out)[:100]


# ---------- 结构化商品数据 ----------
def jsonld_products(html: str, limit: int = 20) -> list[dict]:
    out = []
    for node in HTMLParser(html).css('script[type="application/ld+json"]'):
        try:
            data = json.loads(node.text())
        except ValueError:
            continue
        stack = data if isinstance(data, list) else [data]
        while stack and len(out) < limit:
            item = stack.pop()
            if isinstance(item, dict):
                if "@graph" in item:
                    stack.extend(item["@graph"] if isinstance(item["@graph"], list) else [])
                if item.get("@type") == "ItemList":
                    stack.extend(e.get("item", e) for e in item.get("itemListElement", []) if isinstance(e, dict))
                if item.get("@type") == "Product":
                    offers = item.get("offers") or {}
                    if isinstance(offers, list):
                        offers = offers[0] if offers else {}
                    price = offers.get("price") or offers.get("lowPrice")
                    out.append({"title": item.get("name"), "price": _to_float(price),
                                "category": item.get("category")})
    return out


def _to_float(v) -> float | None:
    try:
        return float(str(v).replace(",", ""))
    except (TypeError, ValueError):
        return None


CN_CHAR_RE = re.compile(r"[一-鿿]")
_LANG_SWITCH = re.compile(r"简体中文|繁體中文|繁体中文|中文|汉语|漢語|普通话")


def count_chinese_chars(html: str) -> tuple[int, str]:
    cleaned = _LANG_SWITCH.sub("", html)
    chars = CN_CHAR_RE.findall(cleaned)
    sample = ""
    if chars:
        m = re.search(r"[一-鿿][^<>\"]{0,30}", cleaned)
        sample = m.group(0)[:30] if m else ""
    return len(chars), sample
