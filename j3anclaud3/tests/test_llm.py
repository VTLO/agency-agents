import asyncio
import json

import anthropic
import httpx2

from j3anclaud3.config import Settings
from j3anclaud3.llm import AnthropicLLM


def _client(seen):
    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append((dict(request.headers), json.loads(request.content)))
        body = seen[-1][1]
        return httpx2.Response(200, json={
            "id": "msg_1", "type": "message", "role": "assistant", "model": body["model"],
            "content": [{"type": "text", "text": "ok"}], "stop_reason": "end_turn", "stop_sequence": None,
            "usage": {"input_tokens": 10, "output_tokens": 5, "cache_read_input_tokens": 900,
                      "cache_creation_input_tokens": 0},
        })

    return anthropic.AsyncAnthropic(api_key="test", http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler)))


def test_request_shape_per_tier():
    seen = []
    llm = AnthropicLLM(Settings(), _client(seen))

    async def go():
        r1 = await llm.complete("S", ["skill prompt", "protocol"], "task", max_tokens=3000, purpose="t")
        await llm.complete("L", ["sys"], "task", max_tokens=500, purpose="t")
        return r1

    r1 = asyncio.run(go())
    (h_std, std), (h_lite, lite) = seen
    assert std["model"] == "claude-sonnet-5-5"
    assert std["thinking"] == {"type": "adaptive"} and std["output_config"] == {"effort": "low"}
    assert std["fallbacks"] == "default" and "server-side-fallback-2026-07-01" in h_std["anthropic-beta"]
    assert "cache_control" not in std["system"][0] and std["system"][-1]["cache_control"] == {"type": "ephemeral"}
    assert std["messages"] == [{"role": "user", "content": "task"}]
    # Haiku: no thinking / effort / fallbacks (unsupported there).
    assert lite["model"] == "claude-haiku-4-5"
    assert not {"thinking", "output_config", "fallbacks"} & lite.keys()
    assert r1.cache_read == 900 and r1.text == "ok" and r1.cost > 0


def test_multi_turn_request_caches_history():
    seen = []
    llm = AnthropicLLM(Settings(), _client(seen))
    hist = [{"role": "user", "content": "Bonjour"}, {"role": "assistant", "content": "Salut !"}]
    asyncio.run(llm.complete("S", ["persona"], "Ça va ?", max_tokens=500, purpose="conversation", history=hist))
    _, body = seen[0]
    assert body["messages"] == [*hist, {"role": "user", "content": "Ça va ?"}]
    assert body["cache_control"] == {"type": "ephemeral"}
