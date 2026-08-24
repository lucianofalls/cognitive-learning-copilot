"""JSON logging that never writes transcript, prompt, or audio content.

Per docs/PRIVACY.md and section 26 of the product spec, log records are
restricted to technical metadata: component name, event name, durations,
counts and sanitized error messages. Free-text fields (transcript text,
LLM prompts/responses) must never be passed as log arguments unless the
DEBUG_CONTENT environment variable is explicitly set to "true", which is
intended for local development only and prints a loud warning on startup.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Any

DEBUG_CONTENT = os.environ.get("DEBUG_CONTENT", "false").lower() == "true"

# Fields that must never leak into a log record's message or extras.
_FORBIDDEN_KEYS = {
    "transcript",
    "transcript_text",
    "prompt",
    "full_prompt",
    "llm_response",
    "audio",
    "participant_name",
}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).astimezone().isoformat(),
            "level": record.levelname,
            "component": getattr(record, "component", record.name),
            "event": getattr(record, "event", record.getMessage()),
        }
        extra = getattr(record, "extra_fields", None)
        if extra:
            for key, value in extra.items():
                if key in _FORBIDDEN_KEYS and not DEBUG_CONTENT:
                    payload[key] = "[redacted]"
                else:
                    payload[key] = value
        if record.exc_info:
            payload["error"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(level: int = logging.INFO) -> None:
    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)

    # argostranslate logs every internal step at INFO, including the raw
    # text it's translating (e.g. "paragraphs: ['...']") -- that's live
    # transcript content, and it would flow straight through the root
    # logger into these structured logs unless silenced here. Not
    # covered by JsonFormatter's _FORBIDDEN_KEYS redaction, which only
    # catches content passed as our own log_event() extra fields, not a
    # third-party library logging arbitrary positional args at INFO.
    if not DEBUG_CONTENT:
        logging.getLogger("argostranslate").setLevel(logging.WARNING)

    if DEBUG_CONTENT:
        root.warning(
            json.dumps(
                {
                    "level": "WARNING",
                    "component": "logging_config",
                    "event": "debug_content_enabled",
                    "message": (
                        "DEBUG_CONTENT=true: transcript and prompt content "
                        "may be written to logs. Do not use in a real meeting."
                    ),
                }
            )
        )


def log_event(
    logger: logging.Logger,
    component: str,
    event: str,
    level: int = logging.INFO,
    **fields: Any,
) -> None:
    logger.log(level, event, extra={"component": component, "event": event, "extra_fields": fields})
