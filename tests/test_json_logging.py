"""Tests for structured JSON logging and config log_format."""

from __future__ import annotations

import io
import json
import logging

from repo_intel.config import _setup_json_handler


class TestJsonLogHandler:
    def _capture_json(self, message: str, level: int = logging.INFO):
        stream = io.StringIO()
        handler = _setup_json_handler()
        handler.stream = stream
        record = logging.LogRecord(
            name="test_json",
            level=level,
            pathname="test.py",
            lineno=1,
            msg=message,
            args=(),
            exc_info=None,
        )
        handler.emit(record)
        return stream.getvalue()

    def test_emits_valid_json(self) -> None:
        line = self._capture_json("hello world")
        parsed = json.loads(line)
        assert isinstance(parsed, dict)

    def test_contains_timestamp(self) -> None:
        line = self._capture_json("test msg")
        parsed = json.loads(line)
        assert "ts" in parsed

    def test_contains_level(self) -> None:
        line = self._capture_json("test msg", level=logging.WARNING)
        parsed = json.loads(line)
        assert parsed["level"] == "WARNING"

    def test_contains_logger_name(self) -> None:
        line = self._capture_json("test msg")
        parsed = json.loads(line)
        assert parsed["logger"] == "test_json"

    def test_contains_message(self) -> None:
        line = self._capture_json("the actual message")
        parsed = json.loads(line)
        assert parsed["msg"] == "the actual message"

    def test_exception_included(self) -> None:
        exc_info = (ValueError, ValueError("boom"), None)
        stream = io.StringIO()
        handler = _setup_json_handler()
        handler.stream = stream
        record = logging.LogRecord(
            name="test_json",
            level=logging.ERROR,
            pathname="test.py",
            lineno=1,
            msg="error occurred",
            args=(),
            exc_info=exc_info,
        )
        handler.emit(record)
        parsed = json.loads(stream.getvalue())
        assert "exc" in parsed
        assert "ValueError" in parsed["exc"]
