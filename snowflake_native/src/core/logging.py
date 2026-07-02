"""
POV-4: Structured logging framework.

Provides a consistent, application-wide logger factory. All modules obtain
their logger exclusively through `get_logger()` to ensure uniform formatting
and configuration.

Design decisions:
- Structured JSON logging is the default for production to support log
  aggregation pipelines (e.g., Datadog, CloudWatch, GCP Logging).
- 'text' format is supported for local development readability.
- No external observability integration (tracing, metrics) in Phase 1.

Reference: docs/architecture/project_structure.md (core/logger.py)
"""

import logging
import sys
from typing import Any


# ---------------------------------------------------------------------------
# Internal formatter implementations
# ---------------------------------------------------------------------------


class _JsonFormatter(logging.Formatter):
    """
    Formats log records as single-line JSON objects.

    Each record includes: timestamp, level, logger name, message,
    and any extra key-value pairs bound to the record.
    """

    def format(self, record: logging.LogRecord) -> str:
        import json
        from datetime import datetime, timezone

        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Attach any extra fields passed via `extra={}` to logging calls.
        for key, value in record.__dict__.items():
            if key not in {
                "name", "msg", "args", "levelname", "levelno", "pathname",
                "filename", "module", "exc_info", "exc_text", "stack_info",
                "lineno", "funcName", "created", "msecs", "relativeCreated",
                "thread", "threadName", "processName", "process", "message",
                "taskName",
            }:
                payload[key] = value

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, default=str)


class _TextFormatter(logging.Formatter):
    """
    Human-readable text formatter for local development.

    Format: [TIMESTAMP] LEVEL     logger_name: message
    """

    FORMAT = "%(asctime)s  %(levelname)-8s  %(name)s: %(message)s"
    DATEFMT = "%Y-%m-%dT%H:%M:%S"

    def __init__(self) -> None:
        super().__init__(fmt=self.FORMAT, datefmt=self.DATEFMT)


# ---------------------------------------------------------------------------
# Logger registry
# ---------------------------------------------------------------------------

_configured: bool = False


def configure_logging(level: str = "INFO", fmt: str = "json") -> None:
    """
    Configure the root logging handler for the application.

    Must be called exactly once at application startup (from main.py lifespan).
    Subsequent calls are ignored to prevent duplicate handlers.

    Args:
        level: Logging level string. One of DEBUG, INFO, WARNING, ERROR, CRITICAL.
        fmt:   Output format. 'json' for structured logging, 'text' for development.
    """
    global _configured
    if _configured:
        return

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_JsonFormatter() if fmt == "json" else _TextFormatter())

    root_logger = logging.getLogger()
    root_logger.setLevel(level.upper())
    root_logger.handlers.clear()
    root_logger.addHandler(handler)

    # Silence overly verbose third-party loggers.
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)

    _configured = True


def get_logger(name: str) -> logging.Logger:
    """
    Return a named logger for use within a module.

    Usage:
        from src.core.logging import get_logger
        logger = get_logger(__name__)

        logger.info("Finding persisted", extra={"finding_id": str(finding.finding_id)})

    Args:
        name: Logger name, conventionally passed as ``__name__``.

    Returns:
        A standard library Logger instance.
    """
    return logging.getLogger(name)
