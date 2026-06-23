"""Async OpenAI-compatible chat completion client for LLM annotators."""
import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass

import httpx
import yaml

logger = logging.getLogger("trajlens.llm")


def _load_dotenv(path: str = ".env") -> None:
    """Load KEY=VALUE from .env into os.environ (no dep, no overwrite)."""
    try:
        for line in open(path):
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())
    except FileNotFoundError:
        pass


# Retry on rate limits, server errors, and timeouts. 4xx (except 429) is fatal.
_BACKOFF = (0.5, 1.0, 2.0, 4.0)


@dataclass
class LLMProfile:
    name: str
    base_url: str
    api_key: str
    model: str
    temperature: float = 0.0
    max_tokens: int = 1024
    timeout: float = 30.0
    proxy: str = "system"  # "none" | "system" | "http://..."


def load_profiles(path: str = "config/llm_profiles.yaml") -> dict[str, LLMProfile]:
    """Load profiles from YAML, expanding ${ENV} references."""
    # ponytail: load .env if present, no extra dep
    _load_dotenv()
    with open(path) as f:
        raw = os.path.expandvars(f.read())
    data = yaml.safe_load(raw) or {}
    profiles: dict[str, LLMProfile] = {}
    for name, cfg in data.items():
        profiles[name] = LLMProfile(name=name, **cfg)
    return profiles


def _make_client_kwargs(proxy: str, timeout: float) -> dict:
    """Build httpx.AsyncClient kwargs for the proxy mode."""
    kwargs: dict = {"timeout": timeout}
    if proxy == "none":
        # bypass system proxy env vars entirely
        kwargs["proxy"] = None
        kwargs["trust_env"] = False
    elif proxy == "system":
        pass  # httpx reads HTTP_PROXY/HTTPS_PROXY from env
    else:
        kwargs["proxy"] = proxy
    return kwargs


def _repair_json(text: str) -> dict:
    """Recover a JSON object from a model response that may be fenced or noisy."""
    s = text.strip()
    if s.startswith("```"):
        # drop opening fence (``` or ```json) and trailing fence
        s = s.split("\n", 1)[1] if "\n" in s else s
        if s.rstrip().endswith("```"):
            s = s.rstrip()[:-3]
        s = s.strip()
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        pass
    start = s.find("{")
    if start == -1:
        raise ValueError(f"no JSON object in response: {text[:200]!r}")
    try:
        return json.loads(s[start:])
    except json.JSONDecodeError as e:
        raise ValueError(f"could not repair JSON: {text[:200]!r}") from e


async def chat_completion(
    profile: LLMProfile,
    messages: list[dict],
    *,
    json_schema: dict | None = None,
    semaphore: asyncio.Semaphore | None = None,
) -> tuple[str, dict]:
    """Call an OpenAI-compatible /chat/completions endpoint. Returns (content, usage)."""
    payload: dict = {
        "model": profile.model,
        "messages": messages,
        "temperature": profile.temperature,
        "max_tokens": profile.max_tokens,
    }
    if json_schema is not None:
        schema = {**json_schema, "additionalProperties": False}
        payload["response_format"] = {
            "type": "json_schema",
            "json_schema": {"name": "output", "strict": True, "schema": schema},
        }

    url = profile.base_url.rstrip("/") + "/chat/completions"
    headers = {"Authorization": f"Bearer {profile.api_key}"}
    client_kwargs = _make_client_kwargs(profile.proxy, profile.timeout)

    last_exc: Exception | None = None
    for attempt in range(len(_BACKOFF)):
        try:
            t0 = time.monotonic()
            async with httpx.AsyncClient(**client_kwargs) as client:
                if semaphore is not None:
                    async with semaphore:
                        resp = await client.post(url, json=payload, headers=headers)
                else:
                    resp = await client.post(url, json=payload, headers=headers)
            latency_ms = int((time.monotonic() - t0) * 1000)
        except httpx.TimeoutException as e:
            last_exc = e
            if not await _backoff(attempt, e):
                break
            continue

        # 4xx other than 429 is fatal — raise immediately, never retry.
        if 400 <= resp.status_code < 500 and resp.status_code != 429:
            resp.raise_for_status()

        # 429 / 5xx are retryable.
        if resp.status_code >= 400:
            last_exc = httpx.HTTPStatusError(
                f"retryable {resp.status_code}", request=resp.request, response=resp)
            if not await _backoff(attempt, last_exc):
                break
            continue

        body = resp.json()
        content = body["choices"][0]["message"]["content"]
        usage = body.get("usage", {})
        logger.info(
            "model=%s prompt_tokens=%s completion_tokens=%s latency_ms=%s",
            profile.model, usage.get("prompt_tokens"),
            usage.get("completion_tokens"), latency_ms)
        return content, usage

    raise last_exc  # type: ignore[misc]


async def _backoff(attempt: int, exc: Exception) -> bool:
    """Sleep before the next retry. Returns False if attempts are exhausted."""
    if attempt == len(_BACKOFF) - 1:
        return False
    delay = _BACKOFF[attempt]
    logger.warning("attempt %d failed (%s), retrying in %ss", attempt + 1, exc, delay)
    await asyncio.sleep(delay)
    return True
