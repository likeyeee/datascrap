"""DNS NS 记录与 RDAP 域名注册信息（均为免费公开数据）。"""
from __future__ import annotations

import asyncio
import time
from urllib.parse import urlsplit

import dns.asyncresolver
import dns.exception
import httpx

from .fetcher import Fetcher


async def nameservers(domain: str) -> list[str]:
    try:
        ans = await asyncio.wait_for(dns.asyncresolver.resolve(domain, "NS"), timeout=8)
        return sorted(str(r.target).rstrip(".").lower() for r in ans)
    except (dns.exception.DNSException, asyncio.TimeoutError, OSError):
        return []


def _vcard(entity: dict) -> dict:
    out: dict = {}
    arr = entity.get("vcardArray")
    if not (isinstance(arr, list) and len(arr) == 2):
        return out
    for item in arr[1]:
        if not isinstance(item, list) or len(item) < 4:
            continue
        key, params, _, value = item[:4]
        if key == "fn":
            out["name"] = value
        elif key == "org":
            out["org"] = value if isinstance(value, str) else " ".join(map(str, value))
        elif key == "adr":
            if isinstance(params, dict) and params.get("cc"):
                out["country"] = params["cc"]
            if isinstance(value, list) and len(value) >= 7:
                out.setdefault("state", value[4])
                out.setdefault("country", value[6])
    return out


def _parse_rdap(data: dict, result: dict) -> None:
    for ev in data.get("events") or []:
        if ev.get("eventAction") == "registration" and not result.get("created"):
            result["created"] = (ev.get("eventDate") or "")[:10]
    for ent in data.get("entities") or []:
        roles = ent.get("roles") or []
        card = _vcard(ent)
        if "registrar" in roles and card.get("name"):
            result.setdefault("registrar", card["name"])
        if "registrant" in roles:
            for k in ("country", "state", "org"):
                if card.get(k) and "redacted" not in str(card[k]).lower():
                    result.setdefault(f"registrant_{k}", card[k])


_cooldown: dict[str, float] = {}   # RDAP 服务被限流后的冷却截止时间
COOLDOWN_SECONDS = 600


async def _rdap_json(f: Fetcher, url: str) -> dict | None:
    """RDAP 只是辅助信息：直接请求，不参与站点限速；被限流就跳过并冷却该服务。"""
    host = urlsplit(url).hostname or ""
    if _cooldown.get(host, 0) > time.monotonic():
        return None
    try:
        r = await f.client.get(url, timeout=15)
    except httpx.HTTPError:
        return None
    final_host = r.url.host
    if r.status_code == 429:
        _cooldown[final_host] = time.monotonic() + COOLDOWN_SECONDS
        return None
    if r.status_code != 200:
        return None
    try:
        data = r.json()
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


async def rdap(f: Fetcher, domain: str) -> dict:
    result: dict = {}
    data = await _rdap_json(f, f"https://rdap.org/domain/{domain}")
    if data is None:
        return result
    _parse_rdap(data, result)
    # .com/.net 注册局只有精简信息，注册人信息在注册商的 RDAP 里
    related = [l.get("href") for l in data.get("links") or []
               if l.get("rel") == "related" and "rdap" in (l.get("href") or "")]
    if related and "registrant_country" not in result:
        sub = await _rdap_json(f, related[0])
        if sub is not None:
            _parse_rdap(sub, result)
    return result
