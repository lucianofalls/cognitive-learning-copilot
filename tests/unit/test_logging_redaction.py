import importlib
import json
import logging


def test_forbidden_fields_are_redacted_by_default(monkeypatch, capsys):
    monkeypatch.delenv("DEBUG_CONTENT", raising=False)
    import meeting_copilot.logging_config as logging_config

    importlib.reload(logging_config)

    logger = logging.getLogger("test.redaction")
    logging_config.configure_logging()
    logging_config.log_event(
        logger,
        "test_component",
        "test_event",
        transcript="This is sensitive meeting content.",
        latency_ms=42,
    )

    output = capsys.readouterr().out.strip().splitlines()[-1]
    payload = json.loads(output)
    assert payload["transcript"] == "[redacted]"
    assert payload["latency_ms"] == 42
    assert payload["component"] == "test_component"


def test_debug_content_true_keeps_fields(monkeypatch, capsys):
    monkeypatch.setenv("DEBUG_CONTENT", "true")
    import meeting_copilot.logging_config as logging_config

    importlib.reload(logging_config)

    logger = logging.getLogger("test.redaction.debug")
    logging_config.configure_logging()
    logging_config.log_event(logger, "test_component", "test_event", transcript="visible in debug mode")

    output = capsys.readouterr().out.strip().splitlines()[-1]
    payload = json.loads(output)
    assert payload["transcript"] == "visible in debug mode"

    # Reset the module-level flag for subsequent tests in the same process.
    monkeypatch.delenv("DEBUG_CONTENT", raising=False)
    importlib.reload(logging_config)
