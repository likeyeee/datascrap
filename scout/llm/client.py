"""DeepSeek Chat Completions 客户端（OpenAI 兼容格式）。"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field

import httpx

from ..config import settings
from ..stats import record_usage

log = logging.getLogger(__name__)


class LLMError(Exception):
    pass


@dataclass
class Usage:
    prompt_tokens: int = 0
    cache_hit_tokens: int = 0
    completion_tokens: int = 0
    calls: int = 0

    def add(self, u: dict) -> None:
        self.prompt_tokens += u.get("prompt_tokens", 0)
        self.cache_hit_tokens += u.get("prompt_cache_hit_tokens", 0)
        self.completion_tokens += u.get("completion_tokens", 0)
        self.calls += 1


@dataclass
class DeepSeekClient:
    usage: Usage = field(default_factory=Usage)

    def __post_init__(self) -> None:
        cfg = settings()["llm"]
        if not cfg.get("api_key"):
            raise LLMError("未配置 DEEPSEEK_API_KEY")
        self.cfg = cfg
        self.http = httpx.AsyncClient(
            base_url=cfg["base_url"].rstrip("/"),
            timeout=httpx.Timeout(180),
            headers={"Authorization": f"Bearer {cfg['api_key']}", "Content-Type": "application/json"},
        )

    async def close(self) -> None:
        await self.http.aclose()

    async def chat_json(self, system: str, user: str, *, model: str | None = None,
                        thinking: bool | None = None, max_tokens: int | None = None) -> dict:
        thinking = self.cfg.get("thinking", False) if thinking is None else thinking
        body: dict = {
            "model": model or self.cfg["model"],
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "response_format": {"type": "json_object"},
            "max_tokens": max_tokens or int(self.cfg.get("max_tokens", 2000)),
            "thinking": {"type": "enabled" if thinking else "disabled"},
            "stream": False,
        }
        if thinking:
            body["reasoning_effort"] = self.cfg.get("reasoning_effort", "low")
        else:
            body["temperature"] = float(self.cfg.get("temperature", 0.2))

        last: Exception | None = None
        for attempt in range(4):
            try:
                r = await self.http.post("/chat/completions", json=body)
                if r.status_code in (429, 500, 502, 503, 504):
                    raise LLMError(f"HTTP {r.status_code}: {r.text[:200]}")
                if r.status_code >= 400:
                    # 参数错误、余额不足等，重试无意义
                    raise LLMError(f"HTTP {r.status_code}: {r.text[:500]}")
                data = r.json()
                self.usage.add(data.get("usage") or {})
                record_usage(body["model"], data.get("usage"))
                choice = data["choices"][0]
                content = choice["message"].get("content") or ""
                if choice.get("finish_reason") == "length":
                    raise LLMError("输出被截断（finish_reason=length），请调大 llm.max_tokens")
                return json.loads(content)
            except (httpx.HTTPError, LLMError, ValueError, KeyError) as e:
                last = e
                fatal = isinstance(e, LLMError) and str(e).startswith(("HTTP 4", "输出被截断")) \
                    and not str(e).startswith("HTTP 429")
                record_usage(body["model"], None, error=True)
                if fatal:
                    raise
                log.warning("deepseek 调用失败（第 %s 次）：%s", attempt + 1, e)
                await asyncio.sleep(3 * 2 ** attempt)
        raise LLMError(f"多次重试失败：{last}")
