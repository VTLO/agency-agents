"""WhatsApp Business Cloud API (Meta Graph API) adapter."""

from __future__ import annotations

import hashlib
import hmac
import logging
import mimetypes
from dataclasses import dataclass
from pathlib import Path

import httpx2 as httpx

from .config import Settings

log = logging.getLogger("m3lvin.wa")

MAX_TEXT = 4096
MAX_BUTTON_BODY = 1024


def verify_signature(app_secret: str, body: bytes, header: str | None) -> bool:
    """Check Meta's X-Hub-Signature-256 HMAC over the raw request body."""
    if not app_secret:
        return True  # signature check disabled (local dev only)
    if not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(app_secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header[7:])


@dataclass
class Inbound:
    msg_id: str
    phone: str
    text: str
    name: str = ""


def parse_webhook(payload: dict) -> list[Inbound]:
    """Extract user messages (text and button replies) from a webhook payload."""
    out: list[Inbound] = []
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            names = {c.get("wa_id"): c.get("profile", {}).get("name", "") for c in value.get("contacts", [])}
            for m in value.get("messages", []):
                kind, text = m.get("type"), ""
                if kind == "text":
                    text = m.get("text", {}).get("body", "")
                elif kind == "interactive":
                    it = m.get("interactive", {})
                    text = (it.get("button_reply") or it.get("list_reply") or {}).get("id", "")
                elif kind == "button":
                    text = m.get("button", {}).get("payload") or m.get("button", {}).get("text", "")
                else:
                    text = f"[{kind}]"  # media etc. — acknowledged, not processed
                out.append(Inbound(m.get("id", ""), m.get("from", ""), text, names.get(m.get("from"), "")))
    return out


def chunk_text(text: str, size: int = MAX_TEXT) -> list[str]:
    parts, buf = [], ""
    for para in text.split("\n"):
        while len(para) > size:
            if buf:
                parts.append(buf)
                buf = ""
            parts.append(para[:size])
            para = para[size:]
        if buf and len(buf) + len(para) + 1 > size:
            parts.append(buf)
            buf = para
        else:
            buf = f"{buf}\n{para}" if buf else para
    if buf:
        parts.append(buf)
    return parts


class WhatsAppClient:
    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None):
        self.s = settings
        self.base = f"https://graph.facebook.com/{settings.wa_api_version}/{settings.wa_phone_id}"
        self.http = client or httpx.AsyncClient(timeout=30, headers={"Authorization": f"Bearer {settings.wa_token}"})

    async def _post(self, payload: dict) -> dict:
        r = await self.http.post(f"{self.base}/messages", json={"messaging_product": "whatsapp", **payload})
        if r.status_code >= 400:
            log.error("WhatsApp API %s: %s", r.status_code, r.text[:500])
            r.raise_for_status()
        return r.json()

    async def send_text(self, to: str, text: str) -> None:
        for part in chunk_text(text):
            await self._post({"to": to, "type": "text", "text": {"body": part, "preview_url": False}})

    async def send_buttons(self, to: str, text: str, buttons: list[tuple[str, str]]) -> None:
        """Interactive reply buttons (max 3, title <= 20 chars). Long bodies go as text first."""
        if len(text) > MAX_BUTTON_BODY:
            await self.send_text(to, text)
            text = "Votre décision ?"
        await self._post({
            "to": to,
            "type": "interactive",
            "interactive": {
                "type": "button",
                "body": {"text": text},
                "action": {"buttons": [
                    {"type": "reply", "reply": {"id": bid[:256], "title": title[:20]}} for bid, title in buttons[:3]
                ]},
            },
        })

    async def send_document(self, to: str, path: Path, caption: str = "") -> None:
        mime = mimetypes.guess_type(path.name)[0] or "text/markdown"
        if path.suffix == ".md":
            mime = "text/plain"  # WhatsApp's accepted document types don't include text/markdown
        with path.open("rb") as fh:
            r = await self.http.post(
                f"{self.base}/media",
                data={"messaging_product": "whatsapp", "type": mime},
                files={"file": (path.name, fh, mime)},
            )
        r.raise_for_status()
        media_id = r.json()["id"]
        await self._post({"to": to, "type": "document",
                          "document": {"id": media_id, "filename": path.name, "caption": caption[:1024]}})

    async def mark_read(self, msg_id: str) -> None:
        try:
            await self._post({"status": "read", "message_id": msg_id})
        except Exception:  # noqa: BLE001 - cosmetic only
            pass
