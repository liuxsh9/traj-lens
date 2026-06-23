"""Tests for the async OpenAI-compatible LLM client."""
import asyncio

import httpx
import pytest

from trajlens.annotate.llm_client import (
    LLMProfile,
    _make_client_kwargs,
    _repair_json,
    chat_completion,
    load_profiles,
)


def _profile(**kw) -> LLMProfile:
    base = dict(
        name="t", base_url="http://api.test/v1", api_key="sk-x",
        model="gpt-test", timeout=5.0)
    base.update(kw)
    return LLMProfile(**base)


# ── load_profiles ──────────────────────────────────────────────────────

def test_load_profiles_expands_env(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_BASE_URL", "http://1.2.3.4/v1")
    monkeypatch.setenv("LLM_API_KEY", "sk-secret")
    monkeypatch.setenv("LLM_MODEL", "gpt-4o-mini")
    monkeypatch.setenv("LLM_PROXY", "none")
    cfg = tmp_path / "p.yaml"
    cfg.write_text(
        "default:\n"
        "  base_url: ${LLM_BASE_URL}\n"
        "  api_key: ${LLM_API_KEY}\n"
        "  model: ${LLM_MODEL}\n"
        "  proxy: ${LLM_PROXY}\n")

    profiles = load_profiles(str(cfg))

    assert set(profiles) == {"default"}
    p = profiles["default"]
    assert p.name == "default"
    assert p.base_url == "http://1.2.3.4/v1"
    assert p.api_key == "sk-secret"
    assert p.model == "gpt-4o-mini"
    assert p.proxy == "none"
    assert p.temperature == 0.0  # default applied


# ── _repair_json ─────────────────────────────────────────────────────────

def test_repair_json_clean():
    assert _repair_json('{"a": 1}') == {"a": 1}


def test_repair_json_markdown_fenced():
    text = '```json\n{"a": 1, "b": [2, 3]}\n```'
    assert _repair_json(text) == {"a": 1, "b": [2, 3]}


def test_repair_json_bare_fence():
    assert _repair_json('```\n{"ok": true}\n```') == {"ok": True}


def test_repair_json_leading_prose():
    assert _repair_json('Sure! Here:\n{"x": 9}') == {"x": 9}


def test_repair_json_malformed_raises():
    with pytest.raises(ValueError):
        _repair_json("no json here at all")


# ── _make_client_kwargs ───────────────────────────────────────────────────

def test_proxy_none():
    kw = _make_client_kwargs("none", 30)
    assert kw["trust_env"] is False


def test_proxy_system():
    kw = _make_client_kwargs("system", 30)
    assert "proxy" not in kw


def test_proxy_explicit():
    kw = _make_client_kwargs("http://proxy:8080", 30)
    assert kw["proxy"] == "http://proxy:8080"


# ── chat_completion (mock transport) ─────────────────────────────────────

def _patch_transport(monkeypatch, handler):
    """Force chat_completion's AsyncClient to use a MockTransport."""
    transport = httpx.MockTransport(handler)
    real = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs.pop("proxy", None)
        kwargs["transport"] = transport
        return real(*args, **kwargs)

    monkeypatch.setattr("trajlens.annotate.llm_client.httpx.AsyncClient", factory)


async def test_chat_completion_basic(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer sk-x"
        return httpx.Response(200, json={
            "choices": [{"message": {"content": "hello"}}],
            "usage": {"prompt_tokens": 7, "completion_tokens": 2},
        })

    _patch_transport(monkeypatch, handler)
    content, usage = await chat_completion(_profile(), [{"role": "user", "content": "hi"}])

    assert content == "hello"
    assert usage["prompt_tokens"] == 7


async def test_chat_completion_json_schema_in_payload(monkeypatch):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json as _json
        captured["body"] = _json.loads(request.content)
        return httpx.Response(200, json={
            "choices": [{"message": {"content": '{"label": "good"}'}}],
            "usage": {},
        })

    _patch_transport(monkeypatch, handler)
    schema = {"type": "object", "properties": {"label": {"type": "string"}}}
    content, _ = await chat_completion(
        _profile(), [{"role": "user", "content": "x"}], json_schema=schema)

    assert content == '{"label": "good"}'
    rf = captured["body"]["response_format"]
    assert rf["type"] == "json_schema"
    assert rf["json_schema"]["strict"] is True
    assert rf["json_schema"]["schema"]["additionalProperties"] is False


async def test_chat_completion_retries_on_429(monkeypatch):
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, json={"error": "rate limited"})
        return httpx.Response(200, json={
            "choices": [{"message": {"content": "ok"}}], "usage": {},
        })

    async def _nosleep(*_):
        return

    _patch_transport(monkeypatch, handler)
    monkeypatch.setattr("trajlens.annotate.llm_client.asyncio.sleep", _nosleep)

    content, _ = await chat_completion(_profile(), [{"role": "user", "content": "hi"}])

    assert content == "ok"
    assert calls["n"] == 2


async def test_chat_completion_4xx_raises_without_retry(monkeypatch):
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(400, json={"error": "bad request"})

    _patch_transport(monkeypatch, handler)

    with pytest.raises(httpx.HTTPStatusError):
        await chat_completion(_profile(), [{"role": "user", "content": "hi"}])
    assert calls["n"] == 1  # no retry on 4xx


async def test_chat_completion_rate_limiter(monkeypatch):
    """Verify internal rate limiter is used (env-configured, no external semaphore)."""
    import trajlens.annotate.llm_client as mod
    monkeypatch.setattr(mod, "_limiter", None)  # force re-init
    monkeypatch.setenv("TRAJLENS_RPS", "20")
    monkeypatch.setenv("TRAJLENS_MAX_CONCURRENCY", "2")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "choices": [{"message": {"content": "y"}}], "usage": {},
        })

    _patch_transport(monkeypatch, handler)
    content, _ = await chat_completion(
        _profile(), [{"role": "user", "content": "hi"}])
    assert content == "y"
    assert mod._limiter is not None
    assert mod._limiter._sem._value == 2  # released back to max
