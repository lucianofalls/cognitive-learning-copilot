"""HTTP client for the local Ollama chat API (section 15).

Deliberately not using the `ollama` SDK: a plain httpx call is easier to
mock in tests, keeps the dependency surface small, and makes the exact
request/response shape explicit. Only ever talks to
`ollama.base_url` (default http://127.0.0.1:11434), which is loopback --
this is the single call site that would need to change if the app were
ever pointed at a remote model, and it should not be.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx
from pydantic import BaseModel, ValidationError

from meeting_copilot.config import OllamaSettings
from meeting_copilot.logging_config import log_event

logger = logging.getLogger(__name__)


class OllamaUnavailableError(RuntimeError):
    pass


class OllamaInvalidResponseError(RuntimeError):
    pass


async def call_local_llm(
    messages: list[dict[str, str]],
    schema: dict[str, Any],
    settings: OllamaSettings,
) -> dict[str, Any]:
    """POST /api/chat with a JSON Schema `format` and return the parsed JSON body.

    Raises OllamaUnavailableError if Ollama cannot be reached at all, and
    OllamaInvalidResponseError if it responds but the message content is
    not parseable JSON (schema validation happens one level up, where the
    caller knows which Pydantic model applies).
    """
    payload = {
        "model": settings.model,
        "messages": messages,
        "stream": False,
        "think": settings.think,
        "format": schema,
        "options": {
            "temperature": settings.temperature,
            "num_ctx": settings.context_tokens,
        },
    }

    try:
        async with httpx.AsyncClient(timeout=settings.request_timeout_seconds) as client:
            response = await client.post(f"{settings.base_url}/api/chat", json=payload)
            response.raise_for_status()
            body = response.json()
    except httpx.HTTPError as exc:
        log_event(logger, "ollama_client", "request_failed", level=logging.ERROR, error=str(exc))
        raise OllamaUnavailableError(str(exc)) from exc

    content = body.get("message", {}).get("content", "")
    try:
        return json.loads(content)
    except json.JSONDecodeError as exc:
        raise OllamaInvalidResponseError(f"Model did not return valid JSON: {exc}") from exc


async def call_and_validate(
    messages: list[dict[str, str]],
    model_cls: type[BaseModel],
    settings: OllamaSettings,
    *,
    repair_attempts: int = 1,
) -> BaseModel:
    """Call the LLM and validate the JSON body against `model_cls`.

    On a validation failure, makes at most `repair_attempts` additional
    calls asking the model to fix its previous output, per section 14's
    "at most one repair attempt" rule.
    """
    schema = model_cls.model_json_schema()
    raw = await call_local_llm(messages, schema, settings)

    attempts_left = repair_attempts
    working_messages = list(messages)
    while True:
        try:
            return model_cls.model_validate(raw)
        except ValidationError as exc:
            if attempts_left <= 0:
                raise OllamaInvalidResponseError(
                    f"Model output failed schema validation: {exc}"
                ) from exc
            attempts_left -= 1
            working_messages = working_messages + [
                {"role": "assistant", "content": json.dumps(raw)},
                {
                    "role": "user",
                    "content": (
                        "Your previous JSON response did not match the required "
                        "schema. Return corrected JSON only, matching the schema "
                        f"exactly. Validation errors: {exc}"
                    ),
                },
            ]
            raw = await call_local_llm(working_messages, schema, settings)


async def check_ollama_health(settings: OllamaSettings) -> bool:
    """Quick readiness probe used by /api/health -- hits /api/tags, not /api/chat."""
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.get(f"{settings.base_url}/api/tags")
            response.raise_for_status()
            tags = response.json().get("models", [])
            return any(settings.model in (m.get("name") or m.get("model") or "") for m in tags)
    except httpx.HTTPError:
        return False
