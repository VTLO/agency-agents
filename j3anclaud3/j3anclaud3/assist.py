"""Companion endpoints for the Android app: draft replies and digests of message notifications.

Messages captured from other people's notifications are untrusted data: they are
sent as JSON fields to a prompt that forbids following them, they are trimmed
before leaving the server, and the model can decline with NO_REPLY (codes, banking,
sensitive or automated messages). The cheapest tier is used by default (J3_ASSIST_TIER).
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from .base import BaseBot
from .prompts import ASSIST_DIGEST_SYSTEM, ASSIST_REPLY_SYSTEM
from .protocol import dumps

NO_REPLY = "NO_REPLY"
MAX_MESSAGES = 12
MAX_CHARS = 500


class ChatLine(BaseModel):
    sender: str = Field(default="", max_length=120, alias="from")
    me: bool = False
    text: str = Field(max_length=4000)


class ReplyIn(BaseModel):
    app: str = Field(default="", max_length=80)
    chat: str = Field(default="", max_length=200)
    group: bool = False
    style: str = Field(default="", max_length=500)  # owner's standing instructions (tone, tutoiement…)
    messages: list[ChatLine] = Field(min_length=1, max_length=50)


class DigestItem(BaseModel):
    app: str = Field(default="", max_length=80)
    chat: str = Field(default="", max_length=200)
    sender: str = Field(default="", max_length=120, alias="from")
    text: str = Field(max_length=4000)
    at: str = Field(default="", max_length=40)


class DigestIn(BaseModel):
    items: list[DigestItem] = Field(min_length=1, max_length=200)


async def draft_reply(bot: BaseBot, user: str, body: ReplyIn) -> str:
    lines = [{"from": m.sender, "me": m.me, "text": m.text[:MAX_CHARS]} for m in body.messages[-MAX_MESSAGES:]]
    payload = dumps({"app": body.app, "chat": body.chat, "group": body.group, "style": body.style, "messages": lines})
    res = await bot.llm.complete(bot.s.assist_tier, [ASSIST_REPLY_SYSTEM], payload, max_tokens=400, purpose="assist")
    bot.store.log_usage(None, f"assist:{user}", res)
    text = res.text.strip().strip('"').strip()
    return "" if not text or NO_REPLY in text else text


async def digest(bot: BaseBot, user: str, body: DigestIn) -> str:
    items = [{"app": i.app, "chat": i.chat, "from": i.sender, "text": i.text[:MAX_CHARS], "at": i.at} for i in body.items[-80:]]
    res = await bot.llm.complete(bot.s.assist_tier, [ASSIST_DIGEST_SYSTEM], dumps({"items": items}), max_tokens=900, purpose="digest")
    bot.store.log_usage(None, f"digest:{user}", res)
    return res.text.strip()
