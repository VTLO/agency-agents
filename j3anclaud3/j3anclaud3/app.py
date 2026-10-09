"""FastAPI server: web chat UI, JSON API and real-time stream (no third-party messaging)."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from .base import BaseBot, Outbox
from .config import MODES, Settings
from .conversation import Conversation
from .llm import LLM, AnthropicLLM
from .orchestrator import J3anClaud3
from .skills import SkillRegistry
from .store import Store
from .web import SESSION_COOKIE, SESSION_TTL, Hub, WebOutbox, load_secret, make_session, normalise_name, read_session

log = logging.getLogger("j3anclaud3.app")
STATIC = Path(__file__).parent / "static"


def build_bot(settings: Settings, outbox: Outbox | None = None, llm: LLM | None = None, store: Store | None = None) -> BaseBot:
    """Instantiate the bot for `settings.mode` ("orchestre" or "conversation")."""
    if settings.mode not in MODES:
        raise ValueError(f"mode inconnu '{settings.mode}' (attendu : {' ou '.join(MODES)})")
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    store = store or Store(settings.data_dir / "j3anclaud3.db")
    outbox = outbox or WebOutbox(store, Hub())
    llm = llm or AnthropicLLM(settings)
    if settings.mode == "conversation":
        log.info("mode conversation: plain chat, skills not loaded")
        return Conversation(settings, store, llm, outbox)
    skills = SkillRegistry.open(
        settings.agency_root,
        settings.data_dir / f"skills-{settings.skill_prompt_tokens}.json",
        settings.skill_prompt_tokens,
    )
    log.info("mode orchestre: loaded %d lite skills", len(skills))
    return J3anClaud3(settings, store, skills, llm, outbox)


class LoginIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)


class SendIn(BaseModel):
    text: str = Field(min_length=1, max_length=8000)
    id: str | None = Field(default=None, max_length=80)  # client id -> idempotent retries


def create_app(settings: Settings | None = None, bot: BaseBot | None = None) -> FastAPI:
    settings = settings or Settings()
    secret = load_secret(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if app.state.bot is None:
            app.state.bot = build_bot(settings)
        await app.state.bot.recover()
        yield

    app = FastAPI(title="J3anClaud3", lifespan=lifespan, docs_url="/api/docs", redoc_url=None)
    app.state.bot = bot

    def current_user(request: Request) -> str:
        # Everyone may use the bot; the session only remembers who is who.
        auth = request.headers.get("authorization", "")
        token = auth[7:].strip() if auth.lower().startswith("bearer ") else request.cookies.get(SESSION_COOKIE)
        user = read_session(secret, token)
        if not user:
            raise HTTPException(401, "non connecté")
        return user

    def bot_mode() -> str:
        return app.state.bot.mode if app.state.bot else settings.mode

    def outbox() -> WebOutbox:
        out = app.state.bot.out
        if not isinstance(out, WebOutbox):
            raise HTTPException(500, "web outbox not configured")
        return out

    # --- pages ---------------------------------------------------------------
    @app.get("/", include_in_schema=False)
    async def index():
        return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})

    @app.get("/manifest.webmanifest", include_in_schema=False)
    async def manifest():
        return FileResponse(STATIC / "manifest.webmanifest", media_type="application/manifest+json")

    @app.get("/sw.js", include_in_schema=False)
    async def service_worker():
        return FileResponse(STATIC / "sw.js", media_type="text/javascript", headers={"Cache-Control": "no-cache"})

    @app.get("/icon.svg", include_in_schema=False)
    async def icon():
        return FileResponse(STATIC / "icon.svg", media_type="image/svg+xml")

    @app.get("/health")
    async def health():
        return {"ok": True}

    @app.get("/api/config")
    async def public_config():
        return {"mode": bot_mode()}

    # --- auth ----------------------------------------------------------------
    @app.post("/api/login")
    async def login(body: LoginIn, request: Request, response: Response):
        user = normalise_name(body.name)
        if not user:
            raise HTTPException(422, "prénom invalide (lettres, chiffres, - _ .)")
        token = make_session(secret, user)
        secure = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
        response.set_cookie(SESSION_COOKIE, token, max_age=SESSION_TTL, httponly=True, samesite="lax", secure=secure)
        # `token` lets API clients authenticate with "Authorization: Bearer <token>".
        return {"user": user, "mode": bot_mode(), "token": token}

    @app.post("/api/logout")
    async def logout(response: Response):
        response.delete_cookie(SESSION_COOKIE)
        return {"ok": True}

    @app.get("/api/me")
    async def me(user: str = Depends(current_user)):
        return {"user": user, "mode": bot_mode()}

    # --- messaging -----------------------------------------------------------
    @app.get("/api/messages")
    async def messages(after: int = 0, user: str = Depends(current_user)):
        return [_public(m) for m in app.state.bot.store.messages(user, after)]

    @app.post("/api/send", status_code=202)
    async def send(body: SendIn, user: str = Depends(current_user)):
        bot: BaseBot = app.state.bot
        msg_id = f"{user}:{body.id or uuid.uuid4().hex}"
        bot._spawn(bot.handle(user, body.text, msg_id))
        return {"ok": True}

    @app.get("/api/stream")
    async def stream(request: Request, after: int = 0, user: str = Depends(current_user), out: WebOutbox = Depends(outbox)):
        last = int(request.headers.get("last-event-id") or after)
        q = out.hub.subscribe(user)  # subscribe first, then replay: nothing falls in the gap

        async def events():
            nonlocal last
            try:
                yield "retry: 3000\n\n"
                for m in out.store.messages(user, last):
                    last = m["id"]
                    yield _sse(m)
                while not await request.is_disconnected():
                    try:
                        m = await asyncio.wait_for(q.get(), timeout=15)
                    except asyncio.TimeoutError:
                        yield ": keep-alive\n\n"
                        continue
                    if m["id"] > last:
                        last = m["id"]
                        yield _sse(m)
            finally:
                out.hub.unsubscribe(user, q)

        return StreamingResponse(events(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.get("/api/files/{msg_id}")
    async def file(msg_id: int, inline: bool = False, user: str = Depends(current_user)):
        m = app.state.bot.store.message(msg_id)
        if not m or m["user"] != user or m["kind"] != "doc":
            raise HTTPException(404)
        path = Path(m["meta"]["path"]).resolve()
        if not path.is_relative_to(settings.data_dir.resolve()) or not path.is_file():
            raise HTTPException(404)
        return FileResponse(path, media_type="text/markdown; charset=utf-8",
                            headers={"Content-Disposition": f'{"inline" if inline else "attachment"}; filename="{path.name}"'})

    return app


def _public(m: dict) -> dict:
    meta = dict(m.get("meta") or {})
    meta.pop("path", None)  # never expose server paths
    return {"id": m["id"], "author": m["author"], "kind": m["kind"], "body": m["body"], "meta": meta, "ts": m["ts"]}


def _sse(m: dict) -> str:
    return f"id: {m['id']}\nevent: message\ndata: {json.dumps(_public(m), ensure_ascii=False)}\n\n"


def main(mode: str | None = None) -> None:  # pragma: no cover - entry point
    import uvicorn

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    settings = Settings()
    if mode:
        settings.mode = mode
    log.info("J3anClaud3 en mode %s", settings.mode)
    log.warning("No accounts: anyone who can reach this server can chat (and spend API credit).")
    host = os.environ.get("HOST", "0.0.0.0")
    uvicorn.run(create_app(settings, build_bot(settings)), host=host, port=int(os.environ.get("PORT", "8080")))


if __name__ == "__main__":  # pragma: no cover
    main()
