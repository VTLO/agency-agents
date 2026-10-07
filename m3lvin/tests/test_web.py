import asyncio
import copy
import time

import pytest
from fastapi.testclient import TestClient

from m3lvin.app import create_app
from m3lvin.config import parse_users
from m3lvin.web import Hub, WebOutbox, make_session, read_session, user_for_code

from .conftest import BRIEF, PLAN

USERS = "alice:approver:code-alice,bob:member:code-bob"


@pytest.fixture
def web(make_bot):
    bot, llm, _ = make_bot(shortlist_size=500, users=parse_users(USERS))
    bot.out = WebOutbox(bot.store, Hub())
    with TestClient(create_app(bot.s, bot)) as client:
        yield client, bot, llm


def _login(client, name="alice", code="code-alice"):
    return client.post("/api/login", json={"name": name, "code": code})


def _wait(bot, timeout=10):
    """Background tasks run on the TestClient's event loop thread: poll until idle."""
    deadline = time.time() + timeout
    time.sleep(0.05)
    while bot.tasks and time.time() < deadline:
        time.sleep(0.02)
    assert not bot.tasks, "background work did not finish"


def test_parse_users():
    users = parse_users(" Alice:approver:x , bob:member:y, broken, :member:z")
    assert set(users) == {"alice", "bob"}
    assert users["alice"].role == "approver" and users["bob"].role == "member"


def test_session_tokens():
    tok = make_session(b"k", "alice")
    assert read_session(b"k", tok) == "alice"
    assert read_session(b"other", tok) is None
    assert read_session(b"k", tok[:-1] + ("0" if tok[-1] != "0" else "1")) is None
    assert read_session(b"k", make_session(b"k", "alice", ttl=-1)) is None
    s = type("S", (), {"users": parse_users(USERS)})()
    assert user_for_code(s, "code-bob") == "bob" and user_for_code(s, "nope") is None


def test_login_and_auth(web):
    client, bot, _ = web
    assert client.get("/api/me").status_code == 401
    assert client.get("/api/config").json() == {"open": False}
    assert _login(client, "alice", "code-bob").status_code == 401  # someone else's code
    assert _login(client, "alice", "code-alice").json()["approver"] is True
    assert client.get("/api/me").json()["user"] == "alice"
    client.post("/api/logout")
    assert client.get("/api/me").status_code == 401


def test_login_rate_limited(web):
    client, *_ = web
    for _ in range(5):
        _login(client, "alice", "bad")
    assert _login(client, "alice", "code-alice").status_code == 429


def test_bearer_api_full_flow(web):
    client, bot, llm = web
    h = {"Authorization": "Bearer code-alice"}
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

    # Another user can neither read Alice's history nor her files.
    hb = {"Authorization": "Bearer code-bob"}
    assert client.get("/api/messages", headers=hb).json() == []
    assert client.get(f"/api/files/{docs[0]['id']}", headers=hb).status_code == 404
    after = msgs[-1]["id"]
    assert client.get(f"/api/messages?after={after}", headers=h).json() == []


def test_static_pages(web):
    client, *_ = web
    assert "M3LVin" in client.get("/").text
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


def test_open_mode(make_bot):
    bot, *_ = make_bot()
    bot.out = WebOutbox(bot.store, Hub())
    with TestClient(create_app(bot.s, bot)) as client:
        assert client.get("/api/config").json() == {"open": True}
        r = client.post("/api/login", json={"name": " Guillaume! "})
        assert r.status_code == 200 and r.json()["user"] == "guillaume"
        assert client.get("/api/me").json()["approver"] is True
