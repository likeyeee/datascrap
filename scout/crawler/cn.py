"""华人/中国卖家识别：规则打分 + 证据清单，结果再交给 LLM 综合判断。"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache

from ..config import cn_signals

# 这些姓氏在英文里也是常见单词或名字，降为弱信号
_ENGLISH_LIKE = {"he", "long", "fan", "wan", "ye", "du", "su", "lu", "shi", "ding", "bai", "jin", "tan",
                 "hong", "song", "king", "young", "lee", "mo", "so", "to", "gee", "toy", "park", "ko", "ku",
                 "lim", "ng", "ho", "hui", "ma", "yu", "li", "wei", "ren", "fu", "gu", "hu", "xu"}

# 关键词不区分大小写，姓名部分必须首字母大写
NAME_CONTEXT_RE = re.compile(
    r"\b(?i:co-founder|founder|owner|ceo|president|founded by|created by|started by|run by|"
    r"my name is|i am|i'm|meet)\b\s*(?:&\s*\w+\s*)?[:,\-–]?\s*"
    r"([A-Z][a-z]{1,12}(?:[ \t]+[A-Z][a-z]{1,12}){0,2})"
)
# 姓名紧跟在后面的写法："Tim Brown, Co-Founder"
NAME_BEFORE_TITLE_RE = re.compile(
    r"([A-Z][a-z]{1,12}(?:[ \t]+[A-Z][a-z]{1,12}){1,2}),?[ \t]+(?:[A-Z][\w&.' ]{0,30}[ \t])?(?i:co-founder|founder|ceo|owner)\b"
)


@dataclass
class CnResult:
    score: int = 0
    location: str = "unknown"      # us / china / unknown
    signals: list[dict] = field(default_factory=list)
    names: list[str] = field(default_factory=list)

    def add(self, key: str, detail: str, weight: int) -> None:
        self.signals.append({"signal": key, "detail": detail[:200], "weight": weight})


@lru_cache
def _cfg():
    c = cn_signals()
    s = c.get("surnames", {})
    return {
        **c,
        "_strong": {x.lower() for x in s.get("strong", [])},
        "_ambiguous": {x.lower() for x in s.get("ambiguous", [])},
        "_company_re": [re.compile(p, re.I) for p in c.get("company_patterns", [])],
        "_ships_re": [re.compile(p, re.I) for p in c.get("ships_from_china_patterns", [])],
        "_places_re": re.compile(r"\b(?:" + "|".join(re.escape(p) for p in c.get("china_places", [])) + r")\b", re.I)
        if c.get("china_places") else None,
    }


def classify_surname(token: str) -> str | None:
    t = token.lower()
    cfg = _cfg()
    if t in cfg["_strong"]:
        return "weak" if t in _ENGLISH_LIKE else "strong"
    if t in cfg["_ambiguous"]:
        return "weak"
    return None


def find_names(text: str) -> list[str]:
    names: dict[str, None] = {}
    matches = list(NAME_CONTEXT_RE.finditer(text)) + list(NAME_BEFORE_TITLE_RE.finditer(text))
    for m in matches:
        name = m.group(1).strip()
        # 过滤 "I'm Here"、"Meet Our Team" 一类
        if name.lower().split()[0] in {"our", "the", "a", "an", "here", "so", "very", "happy", "glad", "excited",
                                         "your", "us", "we", "proud", "passionate", "not", "just", "always",
                                         "still", "back", "in", "on", "from", "with", "all", "now", "only"}:
            continue
        names[name] = None
    return list(names)[:8]


def analyze(data: dict) -> CnResult:
    """data 键：platform, html, text, pages_text, emails, phones, us_addresses, meta, ns, rdap, cn_chars"""
    cfg = _cfg()
    w = cfg.get("weights", {})
    r = CnResult()
    html_l = (data.get("html") or "").lower()
    text = data.get("text") or ""
    china_pts = 0
    us_pts = 0

    platform = data.get("platform") or ""
    if platform in cfg.get("cn_platforms", []):
        r.add("cn_platform", f"建站平台：{platform}", w.get("cn_platform", 0))

    ns = " ".join(data.get("ns") or []).lower()
    hits = [k for k in cfg.get("cn_dns_keywords", []) if k in ns]
    if hits:
        r.add("cn_dns", f"DNS：{', '.join(data.get('ns') or [])[:120]}", w.get("cn_dns", 0))

    rd = data.get("rdap") or {}
    registrar = (rd.get("registrar") or "").lower()
    if registrar and any(k in registrar for k in cfg.get("cn_registrar_keywords", [])):
        r.add("cn_registrar", f"注册商：{rd.get('registrar')}", w.get("cn_registrar", 0))
    rc = (rd.get("registrant_country") or "").upper()
    if rc in ("CN", "HK", "TW", "CHINA", "HONG KONG", "TAIWAN"):
        r.add("registrant_cn", f"域名注册人国家：{rc} {rd.get('registrant_state') or ''}", w.get("registrant_cn", 0))
        china_pts += 1
    elif rc in ("US", "UNITED STATES"):
        us_pts += 1

    n_cn, sample = data.get("cn_chars") or (0, "")
    n_src, src_sample = data.get("cn_source_chars") or (0, "")
    if n_cn >= 4:
        r.add("cn_chars", f"页面文字/图片描述含 {n_cn} 个中文字符，例：{sample}", w.get("cn_chars", 0))
    elif n_src >= 10 and platform not in cfg.get("cn_platforms", []):
        # 国产 SaaS 模板自带中文注释，不计；其他平台的源码注释含中文说明主题由中文开发者定制
        r.add("cn_source_chars", f"源码注释含 {n_src} 个中文字符，例：{src_sample}", w.get("cn_chars", 0) // 2)

    # 联系方式
    contact_hits = []
    for e in data.get("emails") or []:
        if e.split("@")[-1] in cfg.get("cn_email_domains", []):
            contact_hits.append(e)
    cn_phones = [p for p in data.get("phones") or [] if p.startswith(("+86", "0086", "+852", "00852"))]
    contact_hits += cn_phones
    if re.search(r"\bwe-?chat\b|\bweixin\b|微信|\bqq\s*[:：]\s*\d{5,}", text, re.I):
        contact_hits.append("微信/QQ")
    if contact_hits:
        r.add("cn_contact", f"国内联系方式：{', '.join(contact_hits[:4])}", w.get("cn_contact", 0))
        if cn_phones:
            china_pts += 2

    # 公司主体与地址（只在条款/隐私/联系/关于页文本中查找，减少误判）
    legal_text = " ".join((data.get("pages_text") or {}).get(k, "") for k in ("terms", "privacy", "contact", "about", "refund"))
    company_hit = None
    if cfg["_places_re"] is not None:
        for m in cfg["_places_re"].finditer(legal_text):
            window = legal_text[max(0, m.start() - 150): m.end() + 150]
            if any(rx.search(window) for rx in cfg["_company_re"]) or re.search(r"address|room|floor|district|road|street", window, re.I):
                company_hit = re.sub(r"\s+", " ", window).strip()
                break
    if company_hit:
        r.add("cn_company", f"中国公司主体/地址：…{company_hit[:160]}…", w.get("cn_company", 0))
        china_pts += 3

    # 国内生态应用
    apps = [name for name, key in (cfg.get("cn_apps") or {}).items() if str(key).lower() in html_l]
    if apps:
        r.add("cn_apps", f"国内生态应用/物流/支付：{', '.join(apps[:5])}", w.get("cn_apps", 0) * min(len(apps), 2))

    # 发货地
    ship_text = (data.get("pages_text") or {}).get("shipping", "") + " " + text[:5000]
    ship_hits = [m.group(0) for rx in cfg["_ships_re"] if (m := rx.search(ship_text))]
    if ship_hits:
        r.add("ships_from_china", f"发货/时效：{'; '.join(ship_hits[:3])}", w.get("ships_from_china", 0))
        china_pts += 1
    if re.search(r"(?:ship|dispatch)\w* from (?:our )?(?:local |us |u\.s\. |usa |american )?warehouse(?:s)? in (?:the )?(?:us|usa|u\.s\.|united states|california|new jersey|texas)", ship_text, re.I):
        us_pts += 2

    # 美国地址
    meta = data.get("meta") or {}
    cities = [a["city"].lower() for a in data.get("us_addresses") or []]
    if meta.get("city"):
        cities.append(str(meta["city"]).lower())
    hubs = set(cfg.get("us_cn_hubs", []))
    hub_hit = next((c for c in cities if c in hubs or any(c.endswith(h) for h in hubs)), None)
    if hub_hit:
        r.add("us_cn_hub", f"美国地址位于华人聚居/仓储区：{hub_hit.title()}", w.get("us_cn_hub", 0))
    if data.get("us_addresses") or str(meta.get("country") or "").upper() == "US":
        us_pts += 2
    if str(meta.get("country") or "").upper() in ("CN", "HK"):
        china_pts += 3
    if any(p.startswith("+1") for p in data.get("phones") or []):
        us_pts += 1

    # 创始人/联系人姓名
    # 只在关于/联系页找姓名，首页多是商品标题，误判率高
    about_text = " ".join((data.get("pages_text") or {}).get(k, "") for k in ("about", "contact"))
    r.names = find_names(about_text)
    strong, weak = [], []
    for name in r.names:
        kinds = [classify_surname(t) for t in name.split()]
        if "strong" in kinds:
            strong.append(name)
        elif "weak" in kinds:
            weak.append(name)
    for e in data.get("emails") or []:
        local = e.split("@")[0]
        tokens = [t for t in re.split(r"[._\-\d]+", local) if len(t) >= 3]
        if any(classify_surname(t) == "strong" for t in tokens):
            strong.append(e)
    if strong:
        r.add("surname", f"华人姓氏：{', '.join(strong[:3])}", w.get("surname", 0))
    elif weak:
        r.add("surname_weak", f"可能为华人姓氏：{', '.join(weak[:3])}", w.get("surname_weak", 0))

    r.score = min(100, sum(s["weight"] for s in r.signals))
    if china_pts > us_pts and china_pts >= 2:
        r.location = "china"
    elif us_pts > china_pts and us_pts >= 2:
        r.location = "us"
    return r
