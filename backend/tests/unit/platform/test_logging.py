"""Logging pipeline: JSON output, redaction in the pipeline, idempotent setup."""

from __future__ import annotations

import json
import logging

import pytest
from opentelemetry.sdk.trace import TracerProvider

from spidey.platform.config import Environment
from spidey.platform.logging import add_trace_context, configure_logging, get_logger
from spidey.platform.security.scrubbing import REDACTED
from tests.conftest import make_settings


class TestConfigureLogging:
    def test_idempotent_root_handler(self) -> None:
        settings = make_settings()
        configure_logging(settings)
        configure_logging(settings)
        assert len(logging.getLogger().handlers) == 1

    def test_json_output_in_non_dev(self, capsys: pytest.CaptureFixture[str]) -> None:
        configure_logging(make_settings(environment=Environment.TEST))
        get_logger("test.logger").info("something_happened", answer=42)
        line = capsys.readouterr().out.strip().splitlines()[-1]
        event = json.loads(line)
        assert event["event"] == "something_happened"
        assert event["answer"] == 42
        assert event["level"] == "info"
        assert "timestamp" in event

    def test_secrets_redacted_through_pipeline(self, capsys: pytest.CaptureFixture[str]) -> None:
        configure_logging(make_settings(environment=Environment.TEST))
        get_logger("test.logger").info(
            "login", password="hunter2", note="token ghp_abcdefghijklmnopqrst123456"
        )
        out = capsys.readouterr().out
        assert "hunter2" not in out
        assert "ghp_" not in out
        assert REDACTED in out

    def test_stdlib_records_render_through_pipeline(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        configure_logging(make_settings(environment=Environment.TEST))
        logging.getLogger("third.party").warning("plain stdlib message")
        line = capsys.readouterr().out.strip().splitlines()[-1]
        event = json.loads(line)
        assert event["event"] == "plain stdlib message"
        assert event["level"] == "warning"


class TestTraceContext:
    def test_no_active_span_adds_nothing(self) -> None:
        event = add_trace_context(None, "info", {"event": "x"})
        assert "trace_id" not in event

    def test_active_span_ids_attached(self) -> None:
        tracer = TracerProvider().get_tracer("test")
        with tracer.start_as_current_span("op") as span:
            event = add_trace_context(None, "info", {"event": "x"})
            expected = format(span.get_span_context().trace_id, "032x")
        assert event["trace_id"] == expected
        assert len(event["span_id"]) == 16
