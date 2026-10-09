"""Single gateway for every model call: tier routing, caching, fallbacks, ledger.

Economy rules applied here, so callers cannot forget them:
  * callers name a tier (L/S/M), never a model id;
  * stable system blocks carry cache_control (skill prompts, protocol rules),
    volatile content goes last in the user turn; multi-turn chats also cache
    their history prefix;
  * effort is set explicitly per tier; Haiku gets no thinking at all;
  * every response's usage (incl. cache reads) is returned for the ledger.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol

import anthropic

from .config import EFFORT_MODELS, Settings, cost_usd

log = logging.getLogger("j3anclaud3.llm")


@dataclass
class LLMResult:
    text: str
    model: str
    tier: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read: int = 0
    cache_write: int = 0
    stop_reason: str = "end_turn"

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens + self.cache_read + self.cache_write

    @property
    def cost(self) -> float:
        return cost_usd(self.model, self.input_tokens, self.output_tokens, self.cache_read, self.cache_write)


class LLM(Protocol):
    async def complete(
        self, tier: str, system: list[str], user: str, *, max_tokens: int | None = None, purpose: str = "",
        history: list[dict] | None = None,
    ) -> LLMResult: ...


class LLMRefusal(RuntimeError):
    pass


class AnthropicLLM:
    """Claude through the official SDK (async)."""

    FALLBACK_BETA = "server-side-fallback-2026-07-01"

    def __init__(self, settings: Settings, client: anthropic.AsyncAnthropic | None = None):
        self.s = settings
        self.client = client or anthropic.AsyncAnthropic(max_retries=3)

    async def complete(self, tier, system, user, *, max_tokens=None, purpose="", history=None):
        t = self.s.tier(tier)
        # system: list of stable blocks; the last one closes the cached prefix.
        sys_blocks = [{"type": "text", "text": s} for s in system if s]
        if sys_blocks:
            sys_blocks[-1]["cache_control"] = {"type": "ephemeral"}
        params = dict(
            model=t.model,
            max_tokens=max_tokens or t.max_tokens,
            system=sys_blocks,
            messages=[*(history or []), {"role": "user", "content": user}],
        )
        if history:
            # Multi-turn chat: also cache the conversation prefix (stable between turns).
            params["cache_control"] = {"type": "ephemeral"}
        betas: list[str] = []
        if t.model in EFFORT_MODELS:
            params["thinking"] = {"type": "adaptive"}
            if t.effort:
                params["output_config"] = {"effort": t.effort}
            if self.s.server_fallbacks:
                params["fallbacks"] = "default"
                betas.append(self.FALLBACK_BETA)

        try:
            if params["max_tokens"] > 16000:
                async with self.client.beta.messages.stream(betas=betas, **params) as stream:
                    resp = await stream.get_final_message()
            else:
                resp = await self.client.beta.messages.create(betas=betas, **params)
        except anthropic.RateLimitError:
            log.warning("rate limited (%s)", purpose)
            raise
        except anthropic.APIStatusError as e:
            log.error("API error %s on %s: %s", e.status_code, purpose, e.message)
            raise

        if resp.stop_reason == "refusal":
            raise LLMRefusal(f"refusal on {purpose}")
        text = "".join(b.text for b in resp.content if b.type == "text")
        u = resp.usage
        res = LLMResult(
            text=text,
            model=resp.model,
            tier=tier,
            input_tokens=u.input_tokens or 0,
            output_tokens=u.output_tokens or 0,
            cache_read=getattr(u, "cache_read_input_tokens", 0) or 0,
            cache_write=getattr(u, "cache_creation_input_tokens", 0) or 0,
            stop_reason=resp.stop_reason or "",
        )
        log.info(
            "%s tier=%s model=%s in=%d out=%d cache_r=%d cost=$%.4f",
            purpose, tier, res.model, res.input_tokens, res.output_tokens, res.cache_read, res.cost,
        )
        return res
