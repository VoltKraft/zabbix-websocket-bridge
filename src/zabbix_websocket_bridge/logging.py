"""Structured logging configuration."""

import logging
import os
from urllib.parse import urlsplit, urlunsplit


class JsonFormatter(logging.Formatter):
    """Minimal structured log formatter."""

    def format(self, record: logging.LogRecord) -> str:
        import json

        data = {
            "level": record.levelname.lower(),
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            data["exception"] = self.formatException(record.exc_info)
        return json.dumps(data, separators=(",", ":"))


def configure_logging() -> None:
    """Configure application logging without exposing request payloads."""
    level_name = os.getenv("LOG_LEVEL", "info").upper()
    level = getattr(logging, level_name, logging.INFO)
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    logging.basicConfig(level=level, handlers=[handler], force=True)


def sanitize_url(url: str) -> str:
    """Remove user information from a URL before logging it."""
    parsed = urlsplit(url)
    host = parsed.hostname or ""
    if parsed.port:
        host = f"{host}:{parsed.port}"
    return urlunsplit((parsed.scheme, host, parsed.path, "", ""))
