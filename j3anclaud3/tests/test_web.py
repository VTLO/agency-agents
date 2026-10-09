import asyncio
import copy
import time

import pytest
from fastapi.testclient import TestClient

from j3anclaud3.app import build_bot, create_app
from j3anclaud3.conversation import Conversation
from j3anclaud3.store import Store
from j3anclaud3.web import Hub, WebOutbox, make_session, read_session

from .conftest import BRIEF, PLAN, FakeLLM


@pytest.fixture
def web(make_bot):
    bot, llm, _ = make_bot(shortlist_size=500)
    bot.out = WebOutbox(bot.store, Hub())
    with TestClient(create_app(bot.s, bot)) as client:
        yield client, bot, llm


def _token(client, name="alice"):
    return client.post("/api/login", json={"name": name}).json()["token"]


def _wait(bot, timeout=10):
    """Background tasks run on the TestClient's event loop thread: poll until idle."""
    deadline = time.time() + timeout
    time.sleep(0.05)
    while bot.tasks and time.time() < deadline:
        time.sleep(0.02)
    assert not bot.tasks, "background work did not finish"


def test_session_tokens():
    tok = make_session(b"k", "alice")
    assert read_session(b"k", tok) == "alice"
    assert read_session(b"other", tok) is None
    assert read_session(b"k", tok[:-1] + ("0" if tok[-1] != "0" else "1")) is None
    assert read_session(b"k", make_session(b"k", "alice", ttl=-1)) is None


def test_anyone_can_log_in_with_a_first_name(web):
    client, *_ = web
    assert client.get("/api/me").status_code == 401
    assert client.get("/api/config").json() == {"mode": "orchestre"}
    r = client.post("/api/login", json={"name": " Guillaume! "})
    assert r.status_code == 200 and r.json()["user"] == "guillaume" and r.json()["mode"] == "orchestre"
    assert client.get("/api/me").json() == {"user": "guillaume", "mode": "orchestre"}
    client.post("/api/logout")
    assert client.get("/api/me").status_code == 401
    assert client.post("/api/login", json={"name": "!!!"}).status_code == 422


def test_bearer_api_full_flow(web):
    client, bot, llm = web
    h = {"Authorization": f"Bearer {_token(client, 'alice')}"}
    client.cookies.clear()  # the API must work with the Bearer token alone
    llm.chat_replies.append({"r": "Je prépare le **plan**.", "a": "plan", "b": BRIEF})
    llm.plans.append(copy.deepcopy(PLAN))
    assert client.post("/api/send", json={"text": "Une landing page", "id": "c1"}, headers=h).status_code == 202
    _wait(bot)
    msgs = client.get("/api/messages", headers=h).json()
    assert [m["author"] for m in msgs[:2]] == ["u", "m"]
    plan_msg = next(m for m in msgs if m["kind"] == "buttons")
    approve = plan_msg["meta"]["buttons"][0]["send"]
    assert approve.startswith("VALIDER P-")

    # Same client id twice -> processed once (safe retries).
    client.post("/api/send", json={"text": "Une landing page", "id": "c1"}, headers=h)
    _wait(bot)
    assert len(client.get("/api/messages", headers=h).json()) == len(msgs)

    client.post("/api/send", json={"text": approve, "id": "c2"}, headers=h)
    _wait(bot)
    msgs = client.get("/api/messages", headers=h).json()
    docs = [m for m in msgs if m["kind"] == "doc"]
    assert [d["meta"]["name"] for d in docs] == ["landing-copy.md", "posts.md"]
    assert "path" not in docs[0]["meta"]  # server paths never leak
    r = client.get(f"/api/files/{docs[0]['id']}?inline=1", headers=h)
    assert r.status_code == 200 and "Write landing copy" in r.text
    assert "attachment" in client.get(f"/api/files/{docs[0]['id']}", headers=h).headers["content-disposition"]

    # Another person can neither read Alice's history nor her files.
    hb = {"Authorization": f"Bearer {_token(client, 'bob')}"}
    assert client.get("/api/messages", headers=hb).json() == []
    assert client.get(f"/api/files/{docs[0]['id']}", headers=hb).status_code == 404
    assert client.get("/api/messages", headers={"Authorization": "Bearer forged.token"}).status_code == 401
    after = msgs[-1]["id"]
    assert client.get(f"/api/messages?after={after}", headers=h).json() == []


def test_conversation_mode_over_http(make_bot, tmp_path):
    bot, *_ = make_bot()
    llm = FakeLLM()
    conv_bot = build_bot(bot.s.__class__(agency_root=bot.s.agency_root, data_dir=tmp_path, mode="conversation"),
                         llm=llm, store=Store(":memory:"))
    assert isinstance(conv_bot, Conversation)
    with TestClient(create_app(conv_bot.s, conv_bot)) as client:
        assert client.get("/api/config").json() == {"mode": "conversation"}
        assert client.post("/api/login", json={"name": "léa"}).json()["mode"] == "conversation"
        client.post("/api/send", json={"text": "Bonjour !"})
        _wait(conv_bot)
        msgs = client.get("/api/messages").json()
        assert [(m["author"], m["body"]) for m in msgs] == [("u", "Bonjour !"), ("m", "Réponse 1")]


def test_unknown_mode_rejected(make_bot, tmp_path):
    bot, *_ = make_bot()
    with pytest.raises(ValueError, match="mode inconnu"):
        build_bot(bot.s.__class__(agency_root=bot.s.agency_root, data_dir=tmp_path, mode="turbo"), llm=FakeLLM())


def test_static_pages(web):
    client, *_ = web
    assert "J3anClaud3" in client.get("/").text
    assert client.get("/manifest.webmanifest").json()["start_url"] == "/"
    assert client.get("/sw.js").status_code == 200 and client.get("/icon.svg").status_code == 200


def test_hub_fanout():
    async def go():
        hub = Hub()
        q = hub.subscribe("alice")
        hub.publish("alice", {"id": 1})
        hub.publish("bob", {"id": 2})
        got = await asyncio.wait_for(q.get(), 1)
        hub.unsubscribe("alice", q)
        hub.publish("alice", {"id": 3})
        return got, q.empty()
    assert asyncio.run(go()) == ({"id": 1}, True)
