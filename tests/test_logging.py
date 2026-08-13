"""Structured JSON log formatter."""
import json
import logging

from app.logging_config import JsonFormatter


def make_record(**extra: object) -> logging.LogRecord:
    record = logging.LogRecord(
        name="app.test", level=logging.INFO, pathname=__file__, lineno=1,
        msg="request served", args=(), exc_info=None,
    )
    for key, value in extra.items():
        setattr(record, key, value)
    return record


def test_formats_as_json_with_extras() -> None:
    formatter = JsonFormatter()
    record = make_record(vertical="search", latency_ms=42, cached=False)
    data = json.loads(formatter.format(record))
    assert data["message"] == "request served"
    assert data["level"] == "INFO"
    assert data["logger"] == "app.test"
    assert data["vertical"] == "search"
    assert data["latency_ms"] == 42
    assert data["cached"] is False
    assert data["ts"].endswith("+00:00")


def test_exception_is_included() -> None:
    formatter = JsonFormatter()
    try:
        raise ValueError("boom")
    except ValueError:
        import sys

        record = logging.LogRecord(
            name="app.test", level=logging.ERROR, pathname=__file__, lineno=1,
            msg="failed", args=(), exc_info=sys.exc_info(),
        )
    data = json.loads(formatter.format(record))
    assert "ValueError: boom" in data["exception"]
