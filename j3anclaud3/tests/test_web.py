import asyncio
import copy
import time

import pytest
from fastapi.testclient import TestClient

from j3anclaud3.app import build_bot, create_app
from j3anclaud3.conversation import Conversation
from j3anclaud3.store import Store
from j3anclaud3.web import Hub, WebOutbox, load_secret, make_session, read_session

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
    assert client.get("/api/config").json() == {"mode": "orchestre", "admin_name": None}
    r = client.post("/api/login", json={"name": " Guillaume! "})
    assert r.status_code == 200 and r.json()["user"] == "guillaume" and r.json()["mode"] == "orchestre"
    assert client.get("/api/me").json() == {"user": "guillaume", "mode": "orchestre", "admin": False}
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
        assert client.get("/api/config").json()["mode"] == "conversation"
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


# --- admin -------------------------------------------------------------------

@pytest.fixture
def admin_web(make_bot):
    bot, llm, _ = make_bot(shortlist_size=500, admin_password="s3cret-admin")
    bot.out = WebOutbox(bot.store, Hub())
    with TestClient(create_app(bot.s, bot)) as client:
        yield client, bot, llm


def test_admin_name_is_reserved(admin_web):
    client, *_ = admin_web
    assert client.get("/api/config").json()["admin_name"] == "admin"
    assert client.post("/api/login", json={"name": "admin"}).status_code == 401
    assert client.post("/api/login", json={"name": "Admin", "password": "nope"}).status_code == 401
    r = client.post("/api/login", json={"name": "admin", "password": "s3cret-admin"})
    assert r.status_code == 200 and r.json()["admin"] is True
    assert client.get("/api/me").json()["admin"] is True
    # A plain session for the admin name (e.g. issued before the password was set) is refused.
    forged = make_session(load_secret(client.app.state.bot.s), "admin")
    assert client.get("/api/me", headers={"Authorization": f"Bearer {forged}"}).status_code == 401


def test_admin_login_rate_limited(admin_web):
    client, *_ = admin_web
    for _ in range(5):
        client.post("/api/login", json={"name": "admin", "password": "bad"})
    assert client.post("/api/login", json={"name": "admin", "password": "s3cret-admin"}).status_code == 429
    assert client.post("/api/login", json={"name": "bob"}).status_code == 200  # others are never limited


def test_only_admin_launches_production(admin_web):
    client, bot, llm = admin_web
    alice = {"Authorization": f"Bearer {_token(client, 'alice')}"}
    admin_tok = client.post("/api/login", json={"name": "admin", "password": "s3cret-admin"}).json()["token"]
    admin = {"Authorization": f"Bearer {admin_tok}"}
    client.cookies.clear()

    llm.chat_replies.append({"r": "Je prépare le plan.", "a": "plan", "b": BRIEF})
    llm.plans.append(copy.deepcopy(PLAN))
    client.post("/api/send", json={"text": "Une landing page"}, headers=alice)
    _wait(bot)
    alice_plan = next(m for m in client.get("/api/messages", headers=alice).json() if m["kind"] == "buttons")
    assert [b["label"] for b in alice_plan["meta"]["buttons"]] == ["✏️ Modifier", "❌ Annuler"]  # no Valider button
    pid = bot.store.conv("alice")["plan_id"]

    client.post("/api/send", json={"text": f"VALIDER {pid} v1"}, headers=alice)  # typed anyway
    _wait(bot)
    assert bot.store.plan(pid)["status"] == "proposed"
    assert "Seul l'administrateur" in client.get("/api/messages", headers=alice).json()[-1]["body"]

    admin_msgs = client.get("/api/messages", headers=admin).json()
    request = next(m for m in admin_msgs if m["kind"] == "buttons")
    assert "demandée par **alice**" in request["body"]
    client.post("/api/send", json={"text": request["meta"]["buttons"][0]["send"]}, headers=admin)
    _wait(bot)
    assert bot.store.plan(pid)["status"] == "delivered"
    assert any(m["kind"] == "doc" for m in client.get("/api/messages", headers=alice).json())


def test_admin_overview_and_blocking(admin_web):
    client, bot, llm = admin_web
    bob = {"Authorization": f"Bearer {_token(client, 'bob')}"}
    admin_tok = client.post("/api/login", json={"name": "admin", "password": "s3cret-admin"}).json()["token"]
    admin = {"Authorization": f"Bearer {admin_tok}"}
    client.cookies.clear()
    assert client.get("/api/admin/overview", headers=bob).status_code == 403
    assert client.post("/api/admin/block", json={"user": "bob"}, headers=bob).status_code == 403

    llm.chat_replies.append({"r": "Bonjour Bob", "a": "chat", "b": {}})
    client.post("/api/send", json={"text": "salut"}, headers=bob)
    _wait(bot)
    over = client.get("/api/admin/overview", headers=admin).json()
    row = next(p for p in over["people"] if p["user"] == "bob")
    assert row["messages"] == 1 and row["tokens"] == 300 and row["cost"] > 0 and not row["blocked"]
    assert over["admin_approval"] is True and over["mode"] == "orchestre"

    assert client.post("/api/admin/block", json={"user": "bob"}, headers=admin).json() == {"user": "bob", "blocked": True}
    calls = len(llm.calls)
    client.post("/api/send", json={"text": "encore moi"}, headers=bob)
    _wait(bot)
    assert len(llm.calls) == calls  # blocked: zero tokens
    assert "suspendu" in client.get("/api/messages", headers=bob).json()[-1]["body"]
    client.post("/api/admin/block", json={"user": "bob", "blocked": False}, headers=admin)
    assert not bot.store.is_blocked("bob")
    assert client.post("/api/admin/block", json={"user": "admin"}, headers=admin).status_code == 422
