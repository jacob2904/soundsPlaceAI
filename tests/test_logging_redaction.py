"""Tests that secrets never reach the logs."""

import logging

from cinesfx.logging_utils import RedactingFilter


def _record(message: str) -> logging.LogRecord:
    return logging.LogRecord(
        name="cinesfx.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg=message,
        args=(),
        exc_info=None,
    )


def test_redacts_known_env_secret(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-super-secret-123")
    flt = RedactingFilter()
    record = _record("calling api with sk-super-secret-123 now")
    flt.filter(record)
    assert "sk-super-secret-123" not in record.getMessage()
    assert "REDACTED" in record.getMessage()


def test_redacts_authorization_header_pattern():
    flt = RedactingFilter()
    record = _record("Authorization: Bearer abcDEF123.token-value")
    flt.filter(record)
    assert "abcDEF123.token-value" not in record.getMessage()


def test_redacts_api_key_pattern():
    flt = RedactingFilter()
    record = _record("api_key=1234567890abcdef")
    flt.filter(record)
    assert "1234567890abcdef" not in record.getMessage()


def test_leaves_clean_message_untouched():
    flt = RedactingFilter()
    record = _record("analysed 3 scenes")
    flt.filter(record)
    assert record.getMessage() == "analysed 3 scenes"
