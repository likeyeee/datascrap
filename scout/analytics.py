"""看板统计口径。所有聚合都在这里，前台和后台共用。"""
from __future__ import annotations

from collections import Counter
from datetime import timedelta

from sqlalchemy import case, func, select

from .db import Discovery, FollowUp, Store, UsageDaily, User, session, utcnow

US_STATES = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR", "california": "CA", "colorado": "CO",
    "connecticut": "CT", "delaware": "DE", "florida": "FL", "georgia": "GA", "hawaii": "HI", "idaho": "ID",
    "illinois": "IL", "indiana": "IN", "iowa": "IA", "kansas": "KS", "kentucky": "KY", "louisiana": "LA",
    "maine": "ME", "maryland": "MD", "massachusetts": "MA", "michigan": "MI", "minnesota": "MN",
    "mississippi": "MS", "missouri": "MO", "montana": "MT", "nebraska": "NE", "nevada": "NV",
    "new hampshire": "NH", "new jersey": "NJ", "new mexico": "NM", "new york": "NY", "north carolina": "NC",
    "north dakota": "ND", "ohio": "OH", "oklahoma": "OK", "oregon": "OR", "pennsylvania": "PA",
    "rhode island": "RI", "south carolina": "SC", "south dakota": "SD", "tennessee": "TN", "texas": "TX",
    "utah": "UT", "vermont": "VT", "virginia": "VA", "washington": "WA", "west virginia": "WV",
    "wisconsin": "WI", "wyoming": "WY", "district of columbia": "DC",
}
GRADES = ["A", "B", "C", "D"]
FUNNEL = ["未联系", "已联系", "有回复", "洽谈中", "已合作"]
PENDING = ("new", "crawling")


def _daily(col, since) -> dict[str, int]:
    with session() as s:
        rows = s.execute(select(func.date(col), func.count()).where(col >= since).group_by(func.date(col))).all()
    return {str(d): n for d, n in rows if d}


def _series(days: int, data: dict[str, int]) -> list[dict]:
    today = utcnow().date()
    return [{"day": str(today - timedelta(days=i)), "value": data.get(str(today - timedelta(days=i)), 0)}
            for i in range(days - 1, -1, -1)]


def _top(counter: Counter, n: int) -> list[dict]:
    items = counter.most_common()
    head = [{"label": k, "value": v} for k, v in items[:n]]
    rest = sum(v for _, v in items[n:])
    if rest:
        head.append({"label": "其他", "value": rest, "other": True})
    return head


def overview(days: int = 30) -> dict:
    since = utcnow() - timedelta(days=days)
    with session() as s:
        status = dict(s.execute(select(Store.status, func.count()).group_by(Store.status)).all())
        scored_q = select(Store).where(Store.status == "scored")
        grade = dict(s.execute(select(Store.grade, func.count()).where(Store.status == "scored")
                               .group_by(Store.grade)).all())
        cn = dict(s.execute(select(Store.chinese_type, func.count()).where(Store.status == "scored")
                            .group_by(Store.chinese_type)).all())
        platform = dict(s.execute(select(Store.platform, func.count()).where(Store.status == "scored")
                                  .group_by(Store.platform)).all())
        outreach = dict(s.execute(select(Store.outreach_status, func.count()).where(Store.status == "scored")
                                  .group_by(Store.outreach_status)).all())
        rows = s.execute(select(Store.main_categories, Store.promotion_channels, Store.province, Store.country)
                         .where(Store.status == "scored")).all()
        new_scored_7d = s.scalar(select(func.count()).select_from(scored_q.where(
            Store.scored_at >= utcnow() - timedelta(days=7)).subquery()))
        top = s.scalars(scored_q.where(Store.outreach_status == "未联系", Store.owner_id.is_(None))
                        .order_by(Store.total_score.desc().nulls_last()).limit(8)).all()
        top_leads = [{"id": t.id, "domain": t.domain, "name": t.name, "grade": t.grade, "total_score": t.total_score,
                      "main_products": t.main_products, "chinese_type": t.chinese_type} for t in top]

    cats, chans, states = Counter(), Counter(), Counter()
    for c, p, prov, country in rows:
        cats.update(x for x in (c or []) if x and x != "未知")
        chans.update(x for x in (p or []) if x and x != "未知")
        if prov and (country or "US") == "US":
            code = US_STATES.get(str(prov).lower(), str(prov).upper()[:2])
            states[code] += 1

    scored = status.get("scored", 0)
    contacted = sum(outreach.get(k, 0) for k in FUNNEL[1:])
    return {
        "kpi": {
            "total": sum(status.values()),
            "pending": sum(status.get(k, 0) for k in PENDING),
            "to_score": status.get("crawled", 0) + status.get("scoring", 0),
            "scored": scored,
            "new_scored_7d": new_scored_7d or 0,
            "ab": grade.get("A", 0) + grade.get("B", 0),
            "cn_us": cn.get("在美华人", 0),
            "cn_china": cn.get("国内跨境卖家", 0),
            "contacted": contacted,
            "won": outreach.get("已合作", 0),
        },
        "trend": {
            "discovered": _series(days, _daily(Store.discovered_at, since)),
            "crawled": _series(days, _daily(Store.crawled_at, since)),
            "scored": _series(days, _daily(Store.scored_at, since)),
        },
        "grade": [{"label": g, "value": grade.get(g, 0)} for g in GRADES],
        "chinese_type": _top(Counter({k or "未判断": v for k, v in cn.items()}), 6),
        "platform": _top(Counter({k or "未知": v for k, v in platform.items()}), 7),
        "categories": _top(cats, 12),
        "channels": _top(chans, 10),
        "states": _top(states, 10),
        # 漏斗按“至少到达该阶段”累计：已联系 = 已联系+有回复+洽谈中+已合作
        "funnel": [{"label": "全部线索" if i == 0 else k,
                    "value": scored if i == 0 else sum(outreach.get(x, 0) for x in FUNNEL[i:])}
                   for i, k in enumerate(FUNNEL)] if scored else [],
        "funnel_raw": outreach,
        "top_leads": top_leads,
    }


def source_effect() -> list[dict]:
    """各发现渠道的效果：发现数、目标国店铺、已打分、A/B、华人。"""
    is_ab = case((Store.grade.in_(["A", "B"]), 1), else_=0)
    is_cn = case((Store.chinese_type.in_(["在美华人", "国内跨境卖家"]), 1), else_=0)
    is_scored = case((Store.status == "scored", 1), else_=0)
    is_done = case((Store.status.notin_(["new", "crawling"]), 1), else_=0)
    with session() as s:
        rows = s.execute(select(Store.source, func.count(), func.sum(is_done), func.sum(is_scored),
                                func.sum(is_ab), func.sum(is_cn)).group_by(Store.source)).all()
    out = []
    for src, total, done, scored, ab, cn in rows:
        out.append({"source": src or "-", "total": total, "processed": int(done or 0), "scored": int(scored or 0),
                    "ab": int(ab or 0), "chinese": int(cn or 0),
                    "hit_rate": round(100 * (ab or 0) / done, 1) if done else None})
    return sorted(out, key=lambda r: -r["total"])


def monitor() -> dict:
    now = utcnow()
    hour, day = now - timedelta(hours=1), now - timedelta(days=1)
    with session() as s:
        def count(*cond):
            return s.scalar(select(func.count(Store.id)).where(*cond)) or 0

        queue = {
            "ready": count(Store.status == "new", (Store.retry_at.is_(None)) | (Store.retry_at <= now)),
            "waiting_retry": count(Store.status == "new", Store.retry_at > now),
            "crawling": count(Store.status == "crawling"),
            "to_score": count(Store.status == "crawled"),
            "scoring": count(Store.status == "scoring"),
        }
        throughput = {
            "discovered_1h": count(Store.discovered_at >= hour),
            "crawled_1h": count(Store.crawled_at >= hour),
            "scored_1h": count(Store.scored_at >= hour),
            "discovered_24h": count(Store.discovered_at >= day),
            "crawled_24h": count(Store.crawled_at >= day),
            "scored_24h": count(Store.scored_at >= day),
        }
        status = dict(s.execute(select(Store.status, func.count()).group_by(Store.status)).all())
        errors = s.execute(select(Store.id, Store.domain, Store.status, Store.error, Store.updated_at, Store.fail_count)
                           .where(Store.error.is_not(None), Store.status.in_(["new", "failed", "score_failed", "crawled"]))
                           .order_by(Store.updated_at.desc().nulls_last()).limit(15)).all()
        recent = s.execute(select(Store.id, Store.domain, Store.status, Store.grade, Store.total_score, Store.updated_at)
                           .where(Store.updated_at.is_not(None))
                           .order_by(Store.updated_at.desc()).limit(15)).all()
    return {
        "queue": queue,
        "throughput": throughput,
        "status": status,
        "errors": [{"id": i, "domain": d, "status": st, "error": e, "at": _iso(t), "fail_count": f}
                   for i, d, st, e, t, f in errors],
        "recent": [{"id": i, "domain": d, "status": st, "grade": g, "total_score": sc, "at": _iso(t)}
                   for i, d, st, g, sc, t in recent],
    }


def usage(days: int = 30) -> dict:
    since = (utcnow() - timedelta(days=days - 1)).strftime("%Y-%m-%d")
    with session() as s:
        rows = s.scalars(select(UsageDaily).where(UsageDaily.day >= since).order_by(UsageDaily.day)).all()
        data = [{"day": r.day, "model": r.model, "calls": r.calls, "prompt_tokens": r.prompt_tokens,
                 "cache_hit_tokens": r.cache_hit_tokens, "completion_tokens": r.completion_tokens,
                 "errors": r.errors} for r in rows]
    by_day: dict[str, int] = {}
    for r in data:
        by_day[r["day"]] = by_day.get(r["day"], 0) + r["prompt_tokens"] + r["completion_tokens"]
    totals = {k: sum(r[k] for r in data) for k in ("calls", "prompt_tokens", "cache_hit_tokens",
                                                    "completion_tokens", "errors")}
    return {"rows": data, "totals": totals, "trend": _series(days, by_day)}


def team_activity(days: int = 30) -> list[dict]:
    """每个用户认领与跟进的数量。"""
    since = utcnow() - timedelta(days=days)
    with session() as s:
        users = {u.id: u.display_name or u.username for u in s.scalars(select(User))}
        owned = dict(s.execute(select(Store.owner_id, func.count()).where(Store.owner_id.is_not(None))
                               .group_by(Store.owner_id)).all())
        acts = dict(s.execute(select(FollowUp.user_id, func.count()).where(FollowUp.created_at >= since)
                              .group_by(FollowUp.user_id)).all())
        won = dict(s.execute(select(Store.owner_id, func.count()).where(Store.outreach_status == "已合作",
                                                                       Store.owner_id.is_not(None))
                             .group_by(Store.owner_id)).all())
    return sorted([{"user": name, "owned": owned.get(uid, 0), "followups": acts.get(uid, 0), "won": won.get(uid, 0)}
                   for uid, name in users.items() if owned.get(uid) or acts.get(uid)],
                  key=lambda r: -r["owned"])


def discovery_sources_recent(limit: int = 10) -> list[dict]:
    with session() as s:
        rows = s.execute(select(Discovery.source, func.count()).where(
            Discovery.created_at >= utcnow() - timedelta(days=1)).group_by(Discovery.source)).all()
    return [{"source": a, "count": b} for a, b in rows][:limit]


def _iso(t) -> str | None:
    return t.isoformat(timespec="seconds") if t else None
