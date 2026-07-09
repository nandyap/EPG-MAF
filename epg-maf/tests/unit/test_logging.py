"""Unit tests for :mod:`egp_maf.logging.setup`."""

from __future__ import annotations

import io
import json
import logging

import pytest
import structlog

from egp_maf.config.settings import Settings
from egp_maf.logging.setup import configure_logging, get_logger


class TestConfigureLogging:
    def test_returns_logger(self, settings: Settings) -> None:
        logger = configure_logging(settings)
        assert logger is not None

    def test_dev_uses_console_renderer(
        self, monkeypatch: pytest.MonkeyPatch, minimal_env: None
    ) -> None:
        monkeypatch.setenv("EGP_ENV", "dev")
        s = Settings()  # type: ignore[call-arg]
        configure_logging(s)
        # No structured JSON in dev output — inspect the processor chain.
        processors = structlog.get_config()["processors"]
        assert any(
            "ConsoleRenderer" in type(p).__name__ for p in processors
        )

    def test_prod_uses_json_renderer(
        self, monkeypatch: pytest.MonkeyPatch, minimal_env: None
    ) -> None:
        monkeypatch.setenv("EGP_ENV", "prod")
        s = Settings()  # type: ignore[call-arg]
        configure_logging(s)
        processors = structlog.get_config()["processors"]
        assert any(
            "JSONRenderer" in type(p).__name__ for p in processors
        )

    def test_stamps_service_metadata(
        self, monkeypatch: pytest.MonkeyPatch, minimal_env: None, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setenv("EGP_ENV", "prod")
        monkeypatch.setenv("EGP_SERVICE_VERSION", "1.2.3-test")
        s = Settings()  # type: ignore[call-arg]
        configure_logging(s)

        logger = get_logger(__name__)
        logger.info("test.event", key="value")

        captured = capsys.readouterr().out.strip().splitlines()
        assert captured, "expected at least one log line"
        payload = json.loads(captured[-1])
        assert payload["service"] == "egp-maf"
        assert payload["service_version"] == "1.2.3-test"
        assert payload["env"] == "prod"
        assert payload["event"] == "test.event"
        assert payload["key"] == "value"

    def test_respects_log_level(
        self, monkeypatch: pytest.MonkeyPatch, minimal_env: None, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setenv("EGP_ENV", "prod")
        monkeypatch.setenv("EGP_LOG_LEVEL", "ERROR")
        s = Settings()  # type: ignore[call-arg]
        configure_logging(s)

        logger = get_logger(__name__)
        logger.info("suppressed.event")
        logger.error("visible.event")

        out = capsys.readouterr().out.strip().splitlines()
        events = [json.loads(line)["event"] for line in out]
        assert "suppressed.event" not in events
        assert "visible.event" in events
