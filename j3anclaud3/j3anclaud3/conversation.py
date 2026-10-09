"""Mode "conversation": plain natural-language chat, no skills, no plans, no production.

Token economy still applies: a frozen, cached system prompt; a bounded history
trimmed in blocks (so the cached conversation prefix stays stable for several
turns instead of shifting every message); zero-token commands.
"""

from __future__ import annotations

import logging

from .base import BaseBot
from .prompts import CONVERSATION_SYSTEM
from .protocol import parse_command

log = logging.getLogger("j3anclaud3")

HELP = """👋 Je suis **J3anClaud3**. Posez-moi vos questions ou discutons librement, en langage naturel.
• **NOUVEAU** – effacer le fil et repartir de zéro
• **AIDE** – afficher ce message"""

MAX_MESSAGE_CHARS = 6000  # per stored turn


class Conversation(BaseBot):
    mode = "conversation"

    async def _dispatch(self, conv: dict, text: str) -> None:
        user = conv["user"]
        cmd = parse_command(text)
        if cmd and cmd.name == "help":
            await self.out.send_text(user, HELP)
            return
        if cmd and cmd.name == "new":
            conv.update(history=[], brief={}, plan_id=None)
            await self.out.send_text(user, "🆕 C'est noté, on repart de zéro. De quoi voulez-vous parler ?")
            return

        history = [
            {"role": "user" if who == "u" else "assistant", "content": msg} for who, msg in conv["history"]
        ]
        res = await self.llm.complete(
            self.s.chat_tier, [CONVERSATION_SYSTEM], text, max_tokens=4000, purpose="conversation", history=history,
        )
        self.store.log_usage(None, f"conversation:{user}", res)
        reply = res.text.strip() or "Je n'ai pas de réponse à proposer, pouvez-vous reformuler ?"
        conv["history"] = self._trim(conv["history"] + [["u", text[:MAX_MESSAGE_CHARS]], ["m", reply[:MAX_MESSAGE_CHARS]]])
        await self.out.send_text(user, reply)

    def _trim(self, hist: list) -> list:
        """Keep at most `chat_history` messages; when over, drop down to half at once."""
        limit = max(2, self.s.chat_history)
        if len(hist) > limit:
            hist = hist[-max(2, limit // 2):]
        while hist and hist[0][0] != "u":  # the API expects the first turn to be the user's
            hist = hist[1:]
        return hist
