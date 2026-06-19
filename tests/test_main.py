"""
Tests for POV-4 FastAPI application and logging framework.

Covers:
    - /health endpoint returns 200 with correct payload
    - Application lifespan (startup/shutdown) runs cleanly
    - configure_logging is idempotent (safe to call twice)
    - get_logger returns a named Logger instance
    - JSON formatter produces valid JSON output
    - Text formatter produces human-readable output
"""

import json
import logging
import os

import pytest
from fastapi.testclient import TestClient

# Provide minimal required env vars before importing the app,
# since Settings are instantiated at module load via create_app().
os.environ.setdefault("SNOWFLAKE_ACCOUNT", "test.us-east-1")
os.environ.setdefault("SNOWFLAKE_USER", "test_user")
os.environ.setdefault("SNOWFLAKE_PASSWORD", "test_pass")
os.environ.setdefault("SNOWFLAKE_WAREHOUSE", "TEST_WH")
os.environ.setdefault("SNOWFLAKE_DATABASE", "TEST_DB")
os.environ.setdefault("SNOWFLAKE_SCHEMA", "TEST_SCHEMA")
os.environ.setdefault("SNOWFLAKE_ROLE", "TEST_ROLE")
os.environ.setdefault("GEMINI_API_KEY", "test_gemini_key")
os.environ.setdefault("LOG_FORMAT", "text")  # text is cleaner in test output


from src.app.main import app  # noqa: E402 — must come after env setup
from src.core.logging import _JsonFormatter, _TextFormatter, configure_logging, get_logger  # noqa: E402


# =============================================================================
# Health endpoint tests
# =============================================================================


class TestHealthEndpoint:
    def setup_method(self):
        self.client = TestClient(app, raise_server_exceptions=True)

    def test_health_returns_200(self):
        response = self.client.get("/health")
        assert response.status_code == 200

    def test_health_returns_healthy_status(self):
        response = self.client.get("/health")
        data = response.json()
        assert data["status"] == "healthy"

    def test_health_returns_app_name(self):
        response = self.client.get("/health")
        data = response.json()
        assert "app" in data
        assert len(data["app"]) > 0

    def test_health_returns_version(self):
        response = self.client.get("/health")
        data = response.json()
        assert "version" in data

    def test_health_returns_environment(self):
        response = self.client.get("/health")
        data = response.json()
        assert "environment" in data

    def test_no_unexpected_business_routes(self):
        """Phase 1 must expose only /health. No business, telemetry, or POV-3 routes."""
        routes = [r.path for r in app.routes]
        # Only openapi + health routes should be registered in Phase 1
        business_routes = [r for r in routes if r.startswith("/api")]
        assert business_routes == [], f"Unexpected business routes registered: {business_routes}"

    def test_lifespan_startup_and_shutdown(self):
        """
        Exercises the full lifespan context (startup + shutdown) by using
        TestClient as a context manager. This covers the configure_logging
        and logger.info calls inside the lifespan function.
        """
        with TestClient(app) as client:
            response = client.get("/health")
            assert response.status_code == 200


# =============================================================================
# Logging framework tests
# =============================================================================


class TestConfigureLogging:
    def test_configure_logging_does_not_raise(self):
        """configure_logging() must succeed without errors."""
        # Reset the guard so we can call it in test context
        import src.core.logging as log_module
        log_module._configured = False
        configure_logging(level="INFO", fmt="text")

    def test_configure_logging_is_idempotent(self):
        """Calling configure_logging() twice must not add duplicate handlers."""
        import src.core.logging as log_module
        log_module._configured = False
        configure_logging(level="DEBUG", fmt="text")
        handler_count_after_first = len(logging.getLogger().handlers)
        configure_logging(level="DEBUG", fmt="text")  # second call — must be a no-op
        assert len(logging.getLogger().handlers) == handler_count_after_first

    def test_configure_logging_json_format(self):
        import src.core.logging as log_module
        log_module._configured = False
        configure_logging(level="INFO", fmt="json")
        root = logging.getLogger()
        assert any(isinstance(h.formatter, _JsonFormatter) for h in root.handlers)

    def test_configure_logging_text_format(self):
        import src.core.logging as log_module
        log_module._configured = False
        configure_logging(level="INFO", fmt="text")
        root = logging.getLogger()
        assert any(isinstance(h.formatter, _TextFormatter) for h in root.handlers)


class TestGetLogger:
    def test_returns_logger_instance(self):
        logger = get_logger("test.module")
        assert isinstance(logger, logging.Logger)

    def test_logger_has_correct_name(self):
        logger = get_logger("pov4.detector")
        assert logger.name == "pov4.detector"

    def test_dunder_name_usage(self):
        """Validates the standard usage pattern: get_logger(__name__)."""
        logger = get_logger(__name__)
        assert logger.name == __name__


class TestJsonFormatter:
    def setup_method(self):
        self.formatter = _JsonFormatter()

    def _make_record(self, message: str, **kwargs) -> logging.LogRecord:
        record = logging.LogRecord(
            name="test.logger",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg=message,
            args=(),
            exc_info=None,
        )
        for k, v in kwargs.items():
            setattr(record, k, v)
        return record

    def test_produces_valid_json(self):
        record = self._make_record("Test message")
        output = self.formatter.format(record)
        parsed = json.loads(output)
        assert isinstance(parsed, dict)

    def test_required_fields_present(self):
        record = self._make_record("Test message")
        parsed = json.loads(self.formatter.format(record))
        assert "timestamp" in parsed
        assert "level" in parsed
        assert "logger" in parsed
        assert "message" in parsed

    def test_message_content_correct(self):
        record = self._make_record("Finding persisted")
        parsed = json.loads(self.formatter.format(record))
        assert parsed["message"] == "Finding persisted"

    def test_level_is_correct(self):
        record = self._make_record("test")
        parsed = json.loads(self.formatter.format(record))
        assert parsed["level"] == "INFO"

    def test_extra_fields_included(self):
        record = self._make_record("test", finding_id="abc-123")
        parsed = json.loads(self.formatter.format(record))
        assert parsed.get("finding_id") == "abc-123"

    def test_exception_info_included_in_json(self):
        """Covers logging.py line 58: exc_info is serialised into the JSON payload."""
        try:
            raise ValueError("test exception for coverage")
        except ValueError:
            import sys
            exc_info = sys.exc_info()

        record = logging.LogRecord(
            name="test.logger",
            level=logging.ERROR,
            pathname=__file__,
            lineno=1,
            msg="something failed",
            args=(),
            exc_info=exc_info,
        )
        output = self.formatter.format(record)
        parsed = json.loads(output)
        assert "exception" in parsed
        assert "ValueError" in parsed["exception"]


class TestTextFormatter:
    def test_produces_string_output(self):
        formatter = _TextFormatter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname=__file__,
            lineno=1, msg="text log", args=(), exc_info=None,
        )
        output = formatter.format(record)
        assert isinstance(output, str)
        assert "text log" in output
