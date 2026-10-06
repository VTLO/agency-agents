"""FastAPI webhook server for the WhatsApp Cloud API."""

from __future__ import annotations

import json
import os
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, Response

from .config import Settings
from .llm import LLM, AnthropicLLM
from .orchestrator import M3LVin, Outbox
from .skills import SkillRegistry
from .store import Store
from .whatsapp import WhatsAppClient, parse_webhook, verify_signature

log = logging.getLogger("m3lvin.app")


def build_bot(settings: Settings, outbox: Outbox, llm: LLM | None = None, store: Store | None = None) -> M3LVin:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    skills = SkillRegistry.open(
        settings.agency_root,
        settings.data_dir / f"skills-{settings.skill_prompt_tokens}.json",
        settings.skill_prompt_tokens,
    )
    log.info("loaded %d lite skills", len(skills))
    return M3LVin(settings, store or Store(settings.data_dir / "m3lvin.db"), skills, llm or AnthropicLLM(settings), outbox)


def create_app(settings: Settings | None = None, bot: M3LVin | None = None) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if app.state.bot is None:
            app.state.bot = build_bot(settings, WhatsAppClient(settings))
        await app.state.bot.recover()
        yield

    app = FastAPI(title="M3LVin", lifespan=lifespan)
    app.state.bot = bot

    @app.get("/health")
    async def health():
        return {"ok": True}

    @app.get("/webhook")
    async def verify(request: Request):
        q = request.query_params
        if q.get("hub.mode") == "subscribe" and settings.wa_verify_token and q.get("hub.verify_token") == settings.wa_verify_token:
            return Response(q.get("hub.challenge", ""), media_type="text/plain")
        raise HTTPException(403)

    @app.post("/webhook")
    async def receive(request: Request):
        body = await request.body()
        if not verify_signature(settings.wa_app_secret, body, request.headers.get("x-hub-signature-256")):
            raise HTTPException(401, "bad signature")
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            raise HTTPException(400)
        bot: M3LVin = app.state.bot
        for msg in parse_webhook(payload):
            # Ack Meta immediately (it retries slow webhooks); work happens in background.
            bot._spawn(bot.handle(msg.phone, msg.text, msg.msg_id))
            if isinstance(bot.out, WhatsAppClient):
                bot._spawn(bot.out.mark_read(msg.msg_id))
        return {"ok": True}

    return app


def main() -> None:  # pragma: no cover - entry point
    import uvicorn

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    uvicorn.run(create_app(), host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))


if __name__ == "__main__":  # pragma: no cover
    main()
