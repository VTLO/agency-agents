import hashlib
import hmac
import json

from fastapi.testclient import TestClient

from m3lvin.app import create_app
from m3lvin.whatsapp import chunk_text, parse_webhook, verify_signature

PAYLOAD = {
    "entry": [{"changes": [{"value": {
        "contacts": [{"wa_id": "33611111111", "profile": {"name": "Alice"}}],
        "messages": [
            {"id": "wamid.1", "from": "33611111111", "type": "text", "text": {"body": "Bonjour"}},
            {"id": "wamid.2", "from": "33611111111", "type": "interactive",
             "interactive": {"type": "button_reply", "button_reply": {"id": "VALIDER P-ABCD v1", "title": "✅ Valider"}}},
        ],
    }}]}],
}


def test_parse_webhook_text_and_buttons():
    msgs = parse_webhook(PAYLOAD)
    assert [(m.msg_id, m.text, m.name) for m in msgs] == [
        ("wamid.1", "Bonjour", "Alice"), ("wamid.2", "VALIDER P-ABCD v1", "Alice"),
    ]


def test_signature():
    body = b'{"x":1}'
    sig = "sha256=" + hmac.new(b"secret", body, hashlib.sha256).hexdigest()
    assert verify_signature("secret", body, sig)
    assert not verify_signature("secret", body, "sha256=deadbeef")
    assert not verify_signature("secret", body, None)


def test_chunk_text():
    text = "\n".join(["x" * 3000] * 3)
    parts = chunk_text(text)
    assert len(parts) == 3 and all(len(p) <= 4096 for p in parts) and "" not in parts
    assert chunk_text("y" * 9000) == ["y" * 4096, "y" * 4096, "y" * 808]


def test_webhook_endpoints(make_bot):
    bot, llm, out = make_bot(wa_app_secret="s3cret", wa_verify_token="tok")
    handled = []

    async def fake_handle(phone, text, msg_id=None):
        handled.append((phone, text, msg_id))

    bot.handle = fake_handle
    with TestClient(create_app(bot.s, bot)) as client:
        r = client.get("/webhook", params={"hub.mode": "subscribe", "hub.verify_token": "tok", "hub.challenge": "42"})
        assert r.status_code == 200 and r.text == "42"
        assert client.get("/webhook", params={"hub.mode": "subscribe", "hub.verify_token": "bad"}).status_code == 403

        body = json.dumps(PAYLOAD).encode()
        assert client.post("/webhook", content=body, headers={"x-hub-signature-256": "sha256=0"}).status_code == 401
        sig = "sha256=" + hmac.new(b"s3cret", body, hashlib.sha256).hexdigest()
        assert client.post("/webhook", content=body, headers={"x-hub-signature-256": sig}).status_code == 200
    assert [h[2] for h in handled] == ["wamid.1", "wamid.2"]
