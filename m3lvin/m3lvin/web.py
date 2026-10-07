"""Self-hosted web messaging: accounts, persistent history, real-time push (SSE).

Replaces any third-party messaging platform. Works in every browser (desktop,
mobile, installable as a PWA) and through a plain HTTP API (curl, scripts,
other bots) using the user's access code as a Bearer token.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import secrets
import time
from collections import defaultdict
from pathlib import Path

from .config import Settings
from .store import Store

SESSION_COOKIE = "m3s"
SESSION_TTL = 30 * 24 * 3600


class Hub:
    """In-process fan-out of new messages to each user's open connections."""

    def __init__(self) -> None:
        self.subs: dict[str, set[asyncio.Queue]] = defaultdict(set)

    def subscribe(self, user: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=500)
        self.subs[user].add(q)
        return q

    def unsubscribe(self, user: str, q: asyncio.Queue) -> None:
        self.subs[user].discard(q)

    def publish(self, user: str, msg: dict) -> None:
        for q in list(self.subs.get(user, ())):
            try:
                q.put_nowait(msg)
            except asyncio.QueueFull:  # a stalled client resyncs from history on reconnect
                pass


class WebOutbox:
    """Outbox that persists every message, then pushes it to live clients."""

    def __init__(self, store: Store, hub: Hub):
        self.store, self.hub = store, hub

    def _emit(self, user: str, author: str, kind: str, body: str, meta: dict | None = None) -> dict:
        msg = self.store.add_message(user, author, kind, body, meta)
        self.hub.publish(user, msg)
        return msg

    async def record_inbound(self, user: str, text: str) -> None:
        self._emit(user, "u", "text", text)

    async def send_text(self, to: str, text: str) -> None:
        self._emit(to, "m", "text", text)

    async def send_buttons(self, to: str, text: str, buttons: list[tuple[str, str]]) -> None:
        self._emit(to, "m", "buttons", text, {"buttons": [{"send": b, "label": t} for b, t in buttons]})

    async def send_document(self, to: str, path: Path, caption: str = "") -> None:
        size = path.stat().st_size if path.exists() else 0
        self._emit(to, "m", "doc", caption or path.name, {"path": str(path), "name": path.name, "size": size})


# --- authentication ----------------------------------------------------------

def load_secret(settings: Settings) -> bytes:
    if settings.secret:
        return settings.secret.encode()
    path = settings.data_dir / "secret.key"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(secrets.token_hex(32))
        path.chmod(0o600)
    return path.read_text().strip().encode()


def make_session(secret: bytes, user: str, ttl: int = SESSION_TTL) -> str:
    exp = str(int(time.time()) + ttl)
    payload = base64.urlsafe_b64encode(f"{user}|{exp}".encode()).decode().rstrip("=")
    sig = hmac.new(secret, payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{sig}"


def read_session(secret: bytes, token: str | None) -> str | None:
    if not token or "." not in token:
        return None
    payload, sig = token.rsplit(".", 1)
    if not hmac.compare_digest(hmac.new(secret, payload.encode(), hashlib.sha256).hexdigest(), sig):
        return None
    try:
        user, exp = base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)).decode().rsplit("|", 1)
    except (ValueError, UnicodeDecodeError):
        return None
    return user if int(exp) > time.time() else None


def user_for_code(settings: Settings, code: str) -> str | None:
    """Constant-time lookup of the account owning an access code."""
    found = None
    for u in settings.users.values():
        if hmac.compare_digest(u.code.encode(), code.encode()):
            found = u.name
    return found


def normalise_name(name: str) -> str:
    return "".join(ch for ch in name.strip().lower() if ch.isalnum() or ch in "-_.")[:40]


class LoginLimiter:
    """At most `limit` failed logins per client per window (brute-force guard)."""

    def __init__(self, limit: int = 5, window: float = 60.0):
        self.limit, self.window = limit, window
        self.fails: dict[str, list[float]] = defaultdict(list)

    def blocked(self, key: str) -> bool:
        now = time.time()
        self.fails[key] = [t for t in self.fails[key] if now - t < self.window]
        return len(self.fails[key]) >= self.limit

    def fail(self, key: str) -> None:
        self.fails[key].append(time.time())
