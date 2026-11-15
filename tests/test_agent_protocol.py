"""Offline protocol tests. These do NOT constitute real provider acceptance."""

import asyncio
import json
import httpx
import pytest
from backend import agent, knowledge, storage
from test_platform import client, run


class Request:
    def __init__(self, disconnected=False):
        self.disconnected = disconnected

    async def is_disconnected(self):
        return self.disconnected


class FakeResponse:
    def __init__(self, chunks, error=None):
        self.chunks = chunks
        self.error = error

    async def __aenter__(self):
        if self.error:
            raise self.error
        return self

    async def __aexit__(self, *args):
        pass

    def raise_for_status(self):
        pass

    async def aiter_lines(self):
        for chunk in self.chunks:
            yield "data: " + json.dumps(chunk)
        yield "data: [DONE]"


class FakeClient:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.requests = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    def stream(self, *args, **kwargs):
        self.requests.append(kwargs["json"])
        return next(self.responses)


def tool(name="detect_anomalies", args="{}"):
    return {
        "choices": [
            {
                "delta": {
                    "tool_calls": [
                        {
                            "index": 0,
                            "id": "call1",
                            "function": {"name": name, "arguments": args},
                        }
                    ]
                }
            }
        ]
    }


def token(text):
    return {"choices": [{"delta": {"content": text}}]}


def collect(a, request=None):
    c = storage.save("conversation", {"analysis_id": a["id"], "turns": []})

    async def go():
        return "".join(
            [
                chunk
                async for chunk in agent.stream_chat(
                    request or Request(), a, c, "请分析异常"
                )
            ]
        )

    output = asyncio.run(go())
    return output, storage.get("conversation", c["id"])


def test_stream_tools_and_usage(client, monkeypatch):
    a = run(client)
    fake = FakeClient(
        [
            FakeResponse([tool()]),
            FakeResponse(
                [
                    token("依据计算结果，"),
                    token("检出 69 条异常。"),
                    {"usage": {"total_tokens": 42}},
                ]
            ),
        ]
    )
    monkeypatch.setenv("AI_API_KEY", "test-only-not-real")
    monkeypatch.setattr(agent.httpx, "AsyncClient", lambda **kw: fake)
    output, c = collect(a)
    assert (
        "event: tool" in output and "event: token" in output and "event: done" in output
    )
    assert c["turns"][0]["status"] == "complete"
    assert c["turns"][0]["usage"]["total_tokens"] == 42
    assert fake.requests[0]["tool_choice"] == agent.OVERVIEW_CHOICE


def test_six_round_limit(client, monkeypatch):
    a = run(client)
    fake = FakeClient([FakeResponse([tool()]) for _ in range(6)])
    monkeypatch.setenv("AI_API_KEY", "test-only-not-real")
    monkeypatch.setattr(agent.httpx, "AsyncClient", lambda **kw: fake)
    output, c = collect(a)
    assert len(fake.requests) == 6 and "六轮" in output
    assert c["turns"][0]["status"] == "limit"


def test_bad_tool_arguments_recover(client, monkeypatch):
    a = run(client)
    fake = FakeClient(
        [
            FakeResponse([tool(args='{"unknown":1}')]),
            FakeResponse([token("参数不匹配，无法完成本次分析。")]),
        ]
    )
    monkeypatch.setenv("AI_API_KEY", "test-only-not-real")
    monkeypatch.setattr(agent.httpx, "AsyncClient", lambda **kw: fake)
    output, c = collect(a)
    assert "工具参数不匹配" in output
    assert c["turns"][0]["tools"][0]["status"] == "error"
    assert "event: token" not in output


@pytest.mark.parametrize(
    "error", [httpx.ReadTimeout("timeout"), httpx.ConnectError("offline")]
)
def test_model_network_failure(client, monkeypatch, error):
    a = run(client)
    fake = FakeClient([FakeResponse([], error)])
    monkeypatch.setenv("AI_API_KEY", "test-only-not-real")
    monkeypatch.setattr(agent.httpx, "AsyncClient", lambda **kw: fake)
    output, c = collect(a)
    assert "event: error" in output and c["turns"][0]["status"] == "error"
    assert not c["turns"][0]["answer"]


def test_cancel_persisted_without_provider_call(client, monkeypatch):
    a = run(client)
    fake = FakeClient([])
    monkeypatch.setattr(agent.httpx, "AsyncClient", lambda **kw: fake)
    output, c = collect(a, Request(True))
    assert not fake.requests and c["turns"][0]["status"] == "cancelled"


def test_embedding_fallback_is_explicit(client, monkeypatch):
    monkeypatch.setenv("AI_API_KEY", "test-only-not-real")

    async def broken(text):
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(knowledge, "embed", broken)
    result = asyncio.run(knowledge.search("温度补偿"))
    assert result["mode"] == "keyword" and "降级" in result["warning"]


def test_vector_cache_prevents_duplicate_calls(client, monkeypatch):
    monkeypatch.setenv("AI_API_KEY", "test-only-not-real")
    calls = []

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"data": [{"index": 0, "embedding": [0.1, 0.2, 0.3]}]}

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def post(self, *args, **kwargs):
            calls.append(kwargs)
            return Response()

    monkeypatch.setattr(knowledge.httpx, "AsyncClient", lambda **kw: Client())
    asyncio.run(knowledge.embed(["温度补偿"]))
    asyncio.run(knowledge.embed(["温度补偿"]))
    assert len(calls) == 1
