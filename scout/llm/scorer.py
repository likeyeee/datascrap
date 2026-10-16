"""把采集结果交给 DeepSeek，生成结构化分析与合作打分。"""
from __future__ import annotations

import json

import yaml

from ..config import company, scoring, settings
from .client import DeepSeekClient

CHINESE_TYPES = ["在美华人", "国内跨境卖家", "港澳台", "非华人", "无法判断"]

OUTPUT_SCHEMA = {
    "store_name": "店铺名",
    "main_products": "一句话概括主营产品（中文，30 字以内）",
    "main_categories": ["主营品类（中文），1-4 个"],
    "price_positioning": "低价|中等|中高端|高端",
    "business_model": "品牌自营|铺货杂货|Dropshipping|定制手工|批发|其他",
    "us_market": {"is_us_target": True, "confidence": "0-100", "evidence": "判断依据"},
    "promotion_channels": ["推广/获客渠道（中文），如 Meta广告、TikTok广告、Google广告、网红营销、联盟营销、"
                           "Instagram运营、TikTok运营、邮件短信营销、SEO内容、Pinterest"],
    "chinese": {"type": "|".join(CHINESE_TYPES), "confidence": "0-100", "evidence": ["证据"]},
    "fulfillment": {"ships_from": "美国|中国|其他|未知", "delivery_time": "配送时效", "pain_points": "物流痛点"},
    "scale": "微型|小型|中型|大型",
    "scores": "{维度: 0-100 整数}",
    "reasoning": "打分理由（中文，150 字以内）",
    "outreach": {
        "angle": "建联切入点（中文）",
        "recommended_channel": "邮箱|电话|Instagram私信|TikTok私信|Facebook私信|联系表单",
        "contact": "最佳联系方式（来自给定数据，不要编造）",
        "opening_line": "一句英文开场白",
    },
    "red_flags": ["风险点，如疑似空壳站、仿牌、站点不可用"],
}


def system_prompt() -> str:
    # 内容只随后台配置变化；保持字节级稳定以命中 DeepSeek 前缀缓存
    dims = scoring().get("dimensions", {})
    dim_text = "\n".join(f"- {k}：{v.get('desc', '')}" for k, v in dims.items())
    schema = json.loads(json.dumps(OUTPUT_SCHEMA, ensure_ascii=False))
    schema["scores"] = {k: "0-100" for k in dims}
    return f"""你是跨境电商 BD 分析师，负责评估美国市场独立站与我方的合作可行性。

## 我方公司
{yaml.safe_dump(company(), allow_unicode=True, sort_keys=False)}

## 打分维度（每项 0-100 分）
{dim_text}

## 华人身份判断
在 chinese.type 中给出一个：{'、'.join(CHINESE_TYPES)}。
- 在美华人：经营者为华人且主体/仓库/地址在美国。
- 国内跨境卖家：经营主体在中国大陆（中国公司主体、中国地址、+86 电话、从中国发货等）。
- 规则引擎给出的 cn_signals 是线索而非结论，需要综合判断；单一弱信号（如歧义姓氏）不足以下结论。
- 证据不足时选“无法判断”，不要猜测。

## 要求
- 只依据给定数据判断，不得编造联系方式、销量或公司信息。
- 数据缺失时在相应字段写“未知”，并相应降低置信度。
- 只输出一个 JSON 对象，结构如下：
{json.dumps(schema, ensure_ascii=False, indent=1)}
"""


def build_input(store) -> str:
    """从 Store 记录组装喂给模型的数据，控制在 max_input_chars 以内。"""
    max_chars = int(settings()["llm"].get("max_input_chars", 9000))
    cd = store.crawl_data or {}
    data = {
        "domain": store.domain,
        "name": store.name,
        "platform": store.platform,
        "country": store.country, "province": store.province, "city": store.city, "currency": store.currency,
        "description": cd.get("description"),
        "product_count": store.product_count,
        "price": {"min": store.price_min, "median": store.price_median, "max": store.price_max},
        "new_products_last_90d": cd.get("new_last_90d"),
        "last_product_update": str(store.last_product_update) if store.last_product_update else None,
        "product_types": cd.get("product_types"),
        "vendors": cd.get("vendors"),
        "sample_products": list(dict.fromkeys(
            [p.get("title") for p in (cd.get("products") or []) if p.get("title")] + (cd.get("product_slugs") or [])
        ))[:30],
        "products_updated_last_90d": cd.get("updated_last_90d"),
        "marketing_tools": store.marketing,
        "socials": store.socials,
        "emails": store.emails,
        "phones": store.phones,
        "us_addresses": cd.get("us_addresses"),
        "domain_registration": cd.get("rdap"),
        "nameservers": cd.get("ns"),
        "people_names": cd.get("names"),
        "cn_rule_score": store.cn_rule_score,
        "cn_signals": [s.get("detail") for s in store.cn_signals or []],
        "cn_location_guess": store.cn_location,
    }
    head = json.dumps(data, ensure_ascii=False, default=str)
    budget = max(1000, max_chars - len(head))
    pages = cd.get("pages_text") or {}
    texts = {}
    order = ["about", "shipping", "contact", "home", "terms", "refund", "privacy"]
    per = budget // max(1, len([k for k in order if pages.get(k)]))
    for k in order:
        if pages.get(k):
            texts[k] = pages[k][:per]
    return f"## 站点结构化数据\n{head}\n\n## 页面文本摘录\n{json.dumps(texts, ensure_ascii=False)}"


def compute_total(scores: dict) -> tuple[float, str]:
    dims = scoring().get("dimensions", {})
    total_w = sum(float(v.get("weight", 0)) for v in dims.values()) or 1.0
    total = 0.0
    for k, v in dims.items():
        try:
            s = max(0.0, min(100.0, float(scores.get(k, 0))))
        except (TypeError, ValueError):
            s = 0.0
        total += s * float(v.get("weight", 0)) / total_w
    total = round(total, 1)
    grades = scoring().get("grades", {"A": 75, "B": 60, "C": 40, "D": 0})
    grade = next((g for g, th in sorted(grades.items(), key=lambda kv: -kv[1]) if total >= th), "D")
    return total, grade


async def score_store(client: DeepSeekClient, store) -> dict:
    """返回需要写回 Store 的字段。"""
    cfg = settings()["llm"]
    user = build_input(store)
    result = await client.chat_json(system_prompt(), user)
    model = cfg["model"]
    total, grade = compute_total(result.get("scores") or {})
    if cfg.get("review_model") and total >= float(cfg.get("review_threshold", 70)):
        reviewed = await client.chat_json(system_prompt(), user, model=cfg["review_model"],
                                          thinking=True, max_tokens=max(8000, int(cfg.get("max_tokens", 2000))))
        if reviewed.get("scores"):
            result, model = reviewed, cfg["review_model"]
            total, grade = compute_total(result["scores"])
    chinese = result.get("chinese") or {}
    ctype = chinese.get("type") if chinese.get("type") in CHINESE_TYPES else "无法判断"
    try:
        conf = int(float(chinese.get("confidence") or 0))
    except (TypeError, ValueError):
        conf = 0
    return {
        "main_products": result.get("main_products"),
        "main_categories": result.get("main_categories") or [],
        "promotion_channels": result.get("promotion_channels") or [],
        "chinese_type": ctype,
        "chinese_confidence": conf,
        "scores": result.get("scores") or {},
        "total_score": total,
        "grade": grade,
        "llm_result": result,
        "llm_model": model,
    }
