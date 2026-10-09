import json
from pathlib import Path

import pytest

from j3anclaud3.config import Settings
from j3anclaud3.llm import LLMResult
from j3anclaud3.orchestrator import J3anClaud3
from j3anclaud3.skills import SkillRegistry
from j3anclaud3.store import Store

AGENCY_ROOT = Path(__file__).resolve().parents[2]


class FakeLLM:
    """Scripted model: answers by purpose, records every call."""

    def __init__(self):
        self.calls: list[tuple[str, str, list[str], str]] = []
        self.chat_replies: list[dict] = []
        self.plans: list[dict | str] = []
        self.histories: list[list | None] = []

    async def complete(self, tier, system, user, *, max_tokens=None, purpose="", history=None):
        self.calls.append((purpose, tier, system, user))
        self.histories.append(history)
        if purpose == "conversation":
            text = f"Réponse {len(self.histories)}"
        elif purpose == "chat":
            text = json.dumps(self.chat_replies.pop(0))
        elif purpose == "plan":
            p = self.plans.pop(0)
            text = p if isinstance(p, str) else json.dumps(p)
        elif purpose.endswith(":summary"):
            text = "Synthèse : tout est prêt.\n• point clé"
        else:
            task = json.loads(user)
            text = f"# Livrable\n\n{task['do']}\n\n§DIGEST§ {{\"s\":\"did {task['do'][:20]}\",\"k\":[\"fact\"]}}"
        return LLMResult(text=text, model="claude-sonnet-5-5", tier=tier, input_tokens=100, output_tokens=200)

    def purposes(self):
        return [c[0] for c in self.calls]


class MemoryOutbox:
    def __init__(self):
        self.sent: list[tuple[str, str, str]] = []  # (to, kind, content)

    async def send_text(self, to, text):
        self.sent.append((to, "text", text))

    async def send_buttons(self, to, text, buttons):
        self.sent.append((to, "buttons", text + "\n" + "|".join(b[0] for b in buttons)))

    async def send_document(self, to, path, caption=""):
        self.sent.append((to, "doc", str(path)))

    def texts(self, to=None):
        return [c for t, k, c in self.sent if to in (None, t)]


@pytest.fixture(scope="session")
def registry():
    return SkillRegistry.compile(AGENCY_ROOT, 600)


@pytest.fixture
def make_bot(tmp_path, registry):
    def _make(**overrides):
        s = Settings(agency_root=AGENCY_ROOT, data_dir=tmp_path)
        for k, v in overrides.items():
            setattr(s, k, v)
        llm, out = FakeLLM(), MemoryOutbox()
        bot = J3anClaud3(s, Store(":memory:"), registry, llm, out)
        return bot, llm, out

    return _make


PLAN = {
    "g": "SaaS landing page + launch posts",
    "fr": "Créer la landing page et les posts de lancement",
    "h": ["Cible : PME françaises"],
    "s": [
        {"i": "s1", "k": "ux-architect", "t": "Structure de page", "do": "Design landing page structure", "m": "S", "b": 1500},
        {"i": "s2", "k": "content-creator", "t": "Rédaction", "do": "Write landing copy", "in": ["s1"], "m": "S", "b": 2000, "dl": True, "out": "landing-copy"},
        {"i": "s3", "k": "linkedin-content-creator", "t": "Posts LinkedIn", "do": "Write 3 launch posts", "in": ["s1"], "m": "L", "b": 1200, "dl": True, "out": "posts.md"},
    ],
}

BRIEF = {"goal": "launch landing page saas", "dl": ["landing copy", "linkedin posts"], "kw": ["landing", "ux", "content", "linkedin", "copywriting"], "lang": "fr"}
