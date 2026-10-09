"""What both modes share: message intake, de-duplication, per-user locking, background tasks."""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from pathlib import Path
from typing import Protocol

from .config import Settings
from .llm import LLM
from .store import Store

log = logging.getLogger("j3anclaud3")


class Outbox(Protocol):
    async def send_text(self, to: str, text: str) -> None: ...
    async def send_buttons(self, to: str, text: str, buttons: list[tuple[str, str]]) -> None: ...
    async def send_document(self, to: str, path: Path, caption: str = "") -> None: ...


class BaseBot:
    mode = ""

    def __init__(self, settings: Settings, store: Store, llm: LLM, outbox: Outbox):
        self.s, self.store, self.llm, self.out = settings, store, llm, outbox
        self.locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self.tasks: set[asyncio.Task] = set()

    async def handle(self, user: str, text: str, msg_id: str | None = None) -> None:
        if msg_id and self.store.seen(msg_id):
            return
        text = (text or "").strip()
        if not text:
            return
        record = getattr(self.out, "record_inbound", None)
        if record:  # clients with a message history (web) show the human's own messages too
            await record(user, text)
        if self.store.is_blocked(user):  # decided by the admin; costs zero tokens
            await self.out.send_text(user, "Votre accès à J3anClaud3 a été suspendu par l'administrateur.")
            return
        async with self.locks[user]:
            conv = self.store.conv(user)
            try:
                await self._dispatch(conv, text)
            except Exception:  # noqa: BLE001 - never leave a human without an answer
                log.exception("handling failed for %s", user)
                await self.out.send_text(user, "Oups, un incident technique m'a interrompu. Pouvez-vous reformuler ou réessayer ?")
            finally:
                self.store.save_conv(conv)

    async def _dispatch(self, conv: dict, text: str) -> None:
        raise NotImplementedError

    def _spawn(self, coro) -> None:
        task = asyncio.create_task(coro)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    async def recover(self) -> None:
        """Hook run at startup (resume or suspend interrupted work)."""
