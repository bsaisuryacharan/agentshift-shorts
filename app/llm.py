"""Free-first LLM access used by every agent in the loop.

Order of preference is deliberate: zero-cost models first, paid/keyed providers last.
Every call fails closed (raises ProviderError) and every attempt is logged to
logs/llm_usage.jsonl so the loop can measure how often the free tier held.

Providers
---------
1. opencode Zen  -> https://opencode.ai/inference/openai/v1  (OPENCODE_API_KEY)
2. OpenRouter    -> https://openrouter.ai/api/v1             (OPENROUTER_API_KEY)
3. Groq          -> https://api.groq.com/openai/v1           (GROQ_API_KEY)
4. Gemini        -> google-genai SDK                          (GEMINI_API_KEY)
"""
from __future__ import annotations

import base64
import json
import os
import re
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable

import httpx

from .providers import ProviderError
from .settings import Settings

OPENCODE_URL = "https://opencode.ai/inference/openai/v1/chat/completions"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

# Verified free on models.dev at cost 0. Order = preference, strongest reasoning first.
OPENCODE_TEXT = [
    "deepseek-v4.1-flash-free",
    "glm-5.3-flash-free",
    "qwen3.6-plus-free",
    "nemotron-3.5-lightning-free",
    "longcat-2.0-free",
]
OPENCODE_VISION = ["nemotron-3.5-super-vl-free"]
OPENROUTER_TEXT = [
    "nvidia/nemotron-3-super-120b-a12b:free",
    "nvidia/nemotron-3-ultra-550b-a55b:free",
    "google/gemma-4-31b-it:free",
]
OPENROUTER_VISION = ["nvidia/nemotron-3.5-super-vl:free"]

# Gemini quota is per model: 2.5-flash is routinely exhausted on free keys, 3-flash-preview
# answered text and vision calls while 2.5-flash returned 429.
GEMINI_MODELS = [
    m.strip() for m in os.getenv("GEMINI_TEXT_MODEL", "gemini-3-flash-preview,gemini-2.5-flash-lite").split(",")
    if m.strip()
]
GEMINI_VISION_MODELS = [
    m.strip() for m in os.getenv(
        "GEMINI_VISION_MODEL", "gemini-3-flash-preview,gemini-2.5-flash-lite"
    ).split(",")
    if m.strip()
]
# gpt-oss-120b is a reasoning model; it returns an empty string unless given room to think.
GROQ_TEXT = os.getenv("GROQ_TEXT_MODEL", "qwen/qwen3.8-27b")

USAGE_LOG = Path("logs/llm_usage.jsonl")


@dataclass
class LLMResult:
    text: str
    provider: str
    model: str
    seconds: float
    attempts: list[str] = field(default_factory=list)


def _log(record: dict[str, Any]) -> None:
    USAGE_LOG.parent.mkdir(parents=True, exist_ok=True)
    with USAGE_LOG.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def _openai_compatible(
    url: str,
    key: str,
    model: str,
    messages: list[dict[str, Any]],
    temperature: float,
    timeout: float,
    extra_headers: dict[str, str] | None = None,
) -> str:
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    headers.update(extra_headers or {})
    payload = {
        "model": model,
        "temperature": temperature,
        "messages": messages,
        "max_tokens": 4096,
        "response_format": {"type": "json_object"},
    }
    response = httpx.post(url, headers=headers, json=payload, timeout=timeout)
    response.raise_for_status()
    data = response.json()
    content = data.get("choices", [{}])[0].get("message", {}).get("content")
    if not content:
        raise ProviderError(f"{model} returned no content")
    return content


def _gemini(
    settings: Settings,
    prompt: str,
    schema: dict,
    timeout: float,
    images: Iterable[Path] = (),
    model: str | None = None,
) -> str:
    """Native REST call. The SDK ignores our timeout and drops inline images, so we post directly."""
    parts: list[dict[str, Any]] = [{"text": prompt}]
    for path in images:
        mime = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
        parts.append({
            "inline_data": {"mime_type": mime, "data": base64.b64encode(path.read_bytes()).decode()}
        })
    payload: dict[str, Any] = {
        "contents": [{"parts": parts}],
        "generationConfig": {
            "temperature": 0.4,
            "responseMimeType": "application/json",
            "responseJsonSchema": schema,
        },
    }
    response = httpx.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model or GEMINI_MODEL}:generateContent",
        headers={"x-goog-api-key": settings.gemini_api_key or ""},
        json=payload,
        timeout=timeout,
    )
    response.raise_for_status()
    candidates = response.json().get("candidates") or []
    if not candidates:
        raise ProviderError("gemini returned no candidates")
    return "".join(
        part.get("text", "") for part in candidates[0].get("content", {}).get("parts", [])
    )


def _extract_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text).strip()
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            raise ProviderError("LLM did not return JSON") from None
        value = json.loads(text[start : end + 1])
    if not isinstance(value, dict):
        raise ProviderError("LLM returned JSON that is not an object")
    return value


def _image_part(path: Path) -> dict[str, Any]:
    mime = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
    encoded = base64.b64encode(path.read_bytes()).decode()
    return {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{encoded}"}}


class LLM:
    """Role-scoped client. `role` is written into the prompt and the usage log."""

    def __init__(self, settings: Settings | None = None, role: str = "director"):
        self.settings = settings or Settings()
        self.role = role

    # -- capability reporting -------------------------------------------------
    def providers(self) -> list[str]:
        found = []
        if os.getenv("OPENCODE_API_KEY"):
            found.append("opencode")
        if os.getenv("OPENROUTER_API_KEY"):
            found.append("openrouter")
        if self.settings.groq_api_key:
            found.append("groq")
        if self.settings.gemini_api_key:
            found.append("gemini")
        return found

    def available(self) -> bool:
        return bool(self.providers())

    # -- raw chat -------------------------------------------------------------
    def chat(self, messages: list[dict[str, Any]], images: Iterable[Path] = (),
             temperature: float = 0.4, timeout: float = 120.0) -> LLMResult:
        images = list(images)
        if images:
            messages = [dict(m) for m in messages]
            for message in reversed(messages):
                if message.get("role") == "user":
                    text = message.get("content")
                    if isinstance(text, str):
                        message["content"] = [{"type": "text", "text": text}]
                    message["content"].extend(_image_part(p) for p in images)
                    break

        attempts: list[str] = []
        started = time.time()
        ladder: list[tuple[str, str]] = []

        if os.getenv("OPENCODE_API_KEY"):
            for model in (OPENCODE_VISION if images else OPENCODE_TEXT):
                ladder.append(("opencode", model))
        if os.getenv("OPENROUTER_API_KEY"):
            for model in (OPENROUTER_VISION if images else OPENROUTER_TEXT):
                ladder.append(("openrouter", model))
        if self.settings.groq_api_key:
            ladder.append(("groq", GROQ_TEXT))
        if self.settings.gemini_api_key:
            for model in (GEMINI_VISION_MODELS if images else GEMINI_MODELS):
                ladder.append(("gemini", model))

        if not ladder:
            raise ProviderError(
                "No LLM credentials. Set OPENCODE_API_KEY, OPENROUTER_API_KEY, GROQ_API_KEY, "
                "or GEMINI_API_KEY."
            )

        for provider, model in ladder:
            try:
                if provider == "opencode":
                    text = _openai_compatible(
                        OPENCODE_URL, os.environ["OPENCODE_API_KEY"], model, messages,
                        temperature, timeout,
                        {"HTTP-Referer": "https://github.com/anomalyco/opencode", "X-Title": "shorts-factory"},
                    )
                elif provider == "openrouter":
                    text = _openai_compatible(
                        OPENROUTER_URL, os.environ["OPENROUTER_API_KEY"], model, messages,
                        temperature, timeout, {"HTTP-Referer": "https://localhost", "X-Title": "shorts-factory"},
                    )
                elif provider == "groq":
                    text = _openai_compatible(
                        GROQ_URL, self.settings.groq_api_key or "", model, messages, temperature, timeout
                    )
                else:
                    flat = "\n".join(
                        m["content"] if isinstance(m.get("content"), str) else json.dumps(m.get("content"))
                        for m in messages
                    )
                    text = _gemini(
                        self.settings, flat, {"type": "object"}, timeout,
                        images=images, model=model,
                    )
                elapsed = time.time() - started
                _log({"at": datetime.now(UTC).isoformat(), "role": self.role, "provider": provider,
                      "model": model, "ok": True, "seconds": round(elapsed, 2),
                      "vision": bool(images), "attempts": attempts})
                return LLMResult(text=text, provider=provider, model=model, seconds=elapsed, attempts=attempts)
            except Exception as error:  # noqa: BLE001 - failover is the contract
                attempts.append(f"{provider}/{model}: {type(error).__name__}: {error}")

        _log({"at": datetime.now(UTC).isoformat(), "role": self.role, "ok": False,
              "seconds": round(time.time() - started, 2), "attempts": attempts})
        raise ProviderError("All LLM providers failed: " + " | ".join(attempts))

    # -- JSON contract --------------------------------------------------------
    def json(self, instruction: str, schema: dict, images: Iterable[Path] = (),
             temperature: float = 0.4) -> dict:
        prompt = (
            f"You are the {self.role} for an original YouTube Shorts channel.\n"
            "Do not invent facts, sources, quotes, studies, statistics, or events.\n"
            "Return ONLY a JSON object. No prose. No markdown fences.\n"
            f"Schema: {json.dumps(schema)}\n\n{instruction}"
        )
        result = self.chat([{"role": "user", "content": prompt}], images=images, temperature=temperature)
        try:
            return _extract_json(result.text)
        except Exception:
            repair = (
                "Your previous reply was not valid JSON for the schema. Return ONLY the JSON object.\n"
                f"Schema: {json.dumps(schema)}"
            )
            fixed = self.chat(
                [{"role": "system", "content": "You output strict JSON only."},
                 {"role": "user", "content": repair}],
                temperature=0.0,
            )
            return _extract_json(fixed.text)
