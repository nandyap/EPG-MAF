"""Structured JSON logging configuration.

Uses ``structlog`` with ``python-json-logger``-style output. In dev the
output is coloured pretty text; in prod it is JSON on stdout (ACA captures
stdout automatically).

PHI-safety: this module intentionally does NOT include a PHI-allowlist.
That responsibility lives in the Observability workstream (Design §10.4).
For now, developers must not log message bodies, row content or family-
history privacy fields — enforced by the PHI hygiene test in a later
workstream.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog
from structlog.types import EventDict, Processor

from egp_maf.config.settings import Settings


def _add_service_metadata(settings: Settings) -> Processor:
    """Return a processor that stamps every event with service metadata."""

    def processor(_: Any, __: str, event_dict: EventDict) -> EventDict:
        event_dict.setdefault("service", "egp-maf")
        event_dict.setdefault("service_version", settings.service_version)
        event_dict.setdefault("env", settings.env)
        return event_dict

    return processor


def configure_logging(settings: Settings) -> structlog.stdlib.BoundLogger:
    """Configure structlog and stdlib logging.

    Idempotent — safe to call more than once.
    """

    # 1. Stdlib root logger — feeds structlog.
    log_level = getattr(logging, settings.log_level.upper().replace("WARN", "WARNING"))
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=log_level,
        force=True,  # override previous configuration
    )

    # 1b. Quieten third-party loggers that are verbose at INFO.
    #
    # The Azure SDK's http_logging_policy logs the full request URL plus
    # every response header at INFO, so a single Cosmos write produced
    # ~25 lines. At one Cosmos read and one write per turn that buried
    # our own logs and made reading a trace of a single chat turn a
    # manual filtering exercise.
    #
    # WARNING keeps genuine SDK problems (throttling, retries, auth
    # failures) visible while dropping the per-request narration. The
    # credential chain is separated out because "DefaultAzureCredential
    # acquired a token from ManagedIdentityCredential" on every call is
    # reassuring exactly once.
    for noisy in (
        "azure.core.pipeline.policies.http_logging_policy",
        "azure.identity",
        "azure.identity.aio",
        "azure.cosmos",
        "urllib3.connectionpool",
        "httpx",
    ):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    # 2. Structlog processor pipeline.
    shared_processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        _add_service_metadata(settings),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    if settings.is_production() or settings.env == "preprod":
        renderer: Processor = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=True)

    structlog.configure(
        processors=[*shared_processors, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    return structlog.get_logger("egp_maf")


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Return a bound logger. Callers should pass ``__name__``."""
    return structlog.get_logger(name or "egp_maf")
