import asyncio

from j3anclaud3.config import Settings
from j3anclaud3.conversation import Conversation
from j3anclaud3.prompts import CONVERSATION_SYSTEM
from j3anclaud3.store import Store

from .conftest import AGENCY_ROOT, FakeLLM, MemoryOutbox


def _bot(tmp_path, **overrides):
    s = Settings(agency_root=AGENCY_ROOT, data_dir=tmp_path, mode="conversation")
    for k, v in overrides.items():
        setattr(s, k, v)
    llm, out = FakeLLM(), MemoryOutbox()
    return Conversation(s, Store(":memory:"), llm, out), llm, out


def test_plain_chat_keeps_context_without_skills(tmp_path):
    bot, llm, out = _bot(tmp_path)

    async def go():
        await bot.handle("lea", "Bonjour, je m'appelle Léa", "1")
        await bot.handle("lea", "Comment je m'appelle ?", "2")

    asyncio.run(go())
    assert out.texts("lea") == ["Réponse 1", "Réponse 2"]
    (p1, tier, system, user), (p2, *_rest) = llm.calls
    assert p1 == p2 == "conversation" and system == [CONVERSATION_SYSTEM]
    assert llm.histories[0] == []
    assert llm.histories[1] == [
        {"role": "user", "content": "Bonjour, je m'appelle Léa"},
        {"role": "assistant", "content": "Réponse 1"},
    ]


def test_plan_commands_are_plain_text_in_conversation_mode(tmp_path):
    bot, llm, out = _bot(tmp_path)
    asyncio.run(bot.handle("lea", "VALIDER P-ABCD v1", "1"))
    assert llm.calls[0][3] == "VALIDER P-ABCD v1"  # sent to the model, nothing is executed
    assert not hasattr(bot, "executor")


def test_new_and_help_cost_zero_tokens(tmp_path):
    bot, llm, out = _bot(tmp_path)

    async def go():
        await bot.handle("lea", "Salut", "1")
        await bot.handle("lea", "AIDE", "2")
        await bot.handle("lea", "NOUVEAU", "3")
        await bot.handle("lea", "Re-bonjour", "4")

    asyncio.run(go())
    assert [c[0] for c in llm.calls] == ["conversation", "conversation"]
    assert llm.histories[-1] == []  # NOUVEAU cleared the thread
    assert "NOUVEAU" in out.texts("lea")[1]


def test_history_trimmed_in_blocks(tmp_path):
    bot, llm, out = _bot(tmp_path, chat_history=6)

    async def go():
        for i in range(5):
            await bot.handle("lea", f"message {i}", str(i))

    asyncio.run(go())
    sizes = [len(h) for h in llm.histories]
    # grows 0, 2, 4, 6, then drops to half (3 -> first must be a user turn -> 2) instead of sliding
    assert sizes == [0, 2, 4, 6, 2]
    assert all(h[0]["role"] == "user" for h in llm.histories if h)
