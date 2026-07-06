"""Logging helpers with built-in secret redaction.

Per the project's security rules, no secret (API key, token, bearer) may ever be
written to a log. :class:`RedactingFilter` scrubs known secret values and common
credential patterns from every emitted record before it is formatted.
"""

from __future__ import annotations

import logging
import os
import re

# Environment variables whose *values* must never appear in logs.
_SECRET_ENV_KEYS = (
    "GEMINI_API_KEY",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "EPIDEMIC_API_KEY",
    "FREESOUND_API_KEY",
    "ARTLIST_API_TOKEN",
    "AUDIIO_API_TOKEN",
    "MUSICBED_API_TOKEN",
)

# Patterns that look like credentials even if we do not know the exact value.
_PATTERNS = (
    re.compile(r"(?i)(authorization\s*[:=]\s*)(bearer\s+)?[A-Za-z0-9._\-]+"),
    re.compile(r"(?i)(api[_-]?key\s*[:=]\s*)[A-Za-z0-9._\-]+"),
    re.compile(r"(?i)(token\s*[:=]\s*)[A-Za-z0-9._\-]+"),
)

_REDACTED = "***REDACTED***"


class RedactingFilter(logging.Filter):
    """A logging filter that removes secrets from every record's message."""

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003 - stdlib name
        try:
            message = record.getMessage()
        except Exception:  # pragma: no cover - defensive; never block logging
            return True

        redacted = self._redact(message)
        if redacted != message:
            # Replace the message and drop args (already interpolated above).
            record.msg = redacted
            record.args = ()
        return True

    @staticmethod
    def _redact(text: str) -> str:
        """Return ``text`` with known secret values and patterns masked."""
        for env_key in _SECRET_ENV_KEYS:
            value = os.environ.get(env_key)
            if value:
                text = text.replace(value, _REDACTED)
        for pattern in _PATTERNS:
            text = pattern.sub(lambda m: f"{m.group(1)}{_REDACTED}", text)
        return text


def configure_logging(level: str = "INFO") -> logging.Logger:
    """Configure and return the package logger with redaction enabled.

    Args:
        level: Logging level name (e.g. "INFO", "DEBUG").

    Returns:
        The configured ``cinesfx`` logger.
    """
    logger = logging.getLogger("cinesfx")
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)-7s [%(name)s] %(message)s")
        )
        handler.addFilter(RedactingFilter())
        logger.addHandler(handler)

    logger.propagate = False
    return logger


def get_logger(name: str = "cinesfx") -> logging.Logger:
    """Return a child logger that inherits the redacting handler."""
    return logging.getLogger(name if name.startswith("cinesfx") else f"cinesfx.{name}")
