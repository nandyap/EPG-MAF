"""Canonical attribute names for OTEL spans + metrics.

Every attribute name that appears on a span in this codebase must be
in :data:`ALLOWED_ATTRIBUTES`. Every forbidden name — PHI, prompt text,
row content — must be in :data:`FORBIDDEN_ATTRIBUTES` and will raise
via :func:`egp_maf.telemetry.phi_safe.safe_set_attribute`.

The two sets are the load-bearing contract for Design §10.4 PHI-safety
and §20.3 canonical span schema. Adding an attribute is a deliberate,
reviewable action: PR must add the name here and — if it might carry
PHI — get security review.

CI enforcement (see F10.4 acceptance criteria):

- Any use of :func:`opentelemetry.trace.Span.set_attribute` in
  ``egp_maf`` must go through :func:`safe_set_attribute` (import-linter
  rule).
- Test :mod:`tests.security.test_phi_hygiene` scans emitted spans for
  forbidden names.
"""

from __future__ import annotations

# ── Allowed attribute names, grouped by span kind ────────────────────
#
# Format: dotted names, lowercase. Matches Design §20.3 conventions.

# Resource attributes (attached by TelemetryProvider on every span).
_RESOURCE_ATTRIBUTES: frozenset[str] = frozenset(
    {
        "service.name",
        "service.version",
        "service.namespace",
        "deployment.environment",
    }
)

# Workflow-level attributes.
_WORKFLOW_ATTRIBUTES: frozenset[str] = frozenset(
    {
        "workflow.name",
        "workflow.executor",
        "workflow.iteration",
        "workflow.turn.outcome",
        "thread_id",
        "clinician_id",
        "tenant_id",
        "patient_id",
        "orch.mode",
        "orch.width",
        "orch.max_fanout_width",
        "orch.iteration_budget",
    }
)

# Specialist-level attributes.
_SPECIALIST_ATTRIBUTES: frozenset[str] = frozenset(
    {
        "specialist.name",
        "specialist.status",
        "specialist.error_class",
        "specialist.tool_call_count",
        "specialist.duration_ms",
    }
)

# LLM-call attributes.
_LLM_ATTRIBUTES: frozenset[str] = frozenset(
    {
        "llm.model",
        "llm.phase",  # react | extract | structured | synthesize
        "llm.prompt_tokens",
        "llm.completion_tokens",
        "llm.total_tokens",
        "llm.finish_reason",
        "llm.duration_ms",
        "llm.structured_output",
    }
)

# Tool-call attributes.
_TOOL_ATTRIBUTES: frozenset[str] = frozenset(
    {
        "tool.name",
        "tool.row_count",
        "tool.duration_ms",
        "tool.error",
    }
)

# Repository-read attributes.
_REPOSITORY_ATTRIBUTES: frozenset[str] = frozenset(
    {
        "repository.name",
        "repository.method",
        "repository.row_count",
        "repository.duration_ms",
    }
)

# DB / SQL attributes.
_DB_ATTRIBUTES: frozenset[str] = frozenset(
    {
        "db.system",
        "db.table",
        "db.operation",
        "db.row_count",
        "db.duration_ms",
        "db.statement_hash",
    }
)

# Errors — a small stable set that all layers can use.
_ERROR_ATTRIBUTES: frozenset[str] = frozenset(
    {
        "error.class",
        "error.message",
        "error.code",
    }
)


ALLOWED_ATTRIBUTES: frozenset[str] = (
    _RESOURCE_ATTRIBUTES
    | _WORKFLOW_ATTRIBUTES
    | _SPECIALIST_ATTRIBUTES
    | _LLM_ATTRIBUTES
    | _TOOL_ATTRIBUTES
    | _REPOSITORY_ATTRIBUTES
    | _DB_ATTRIBUTES
    | _ERROR_ATTRIBUTES
)


# ── Forbidden attribute names — the PHI-safety load-bearing list ─────
#
# Design §10.4 forbids these on ANY span. Attempting to set one raises
# :class:`egp_maf.telemetry.phi_safe.ForbiddenAttributeError`. The set
# is deliberately narrow: any content field that could carry patient
# data + the family_history privacy trio + LLM prompt/completion text.

FORBIDDEN_ATTRIBUTES: frozenset[str] = frozenset(
    {
        # Family history privacy strip (Design ADR-017).
        "search_context_notes",
        "affected_relative_count",
        "total_relatives_searched",
        # LLM content — never on spans.
        "prompt_text",
        "completion_text",
        "message.content",
        "messages.content",
        # Row data — never on spans (row_count is fine; the row body is not).
        "row.body",
        "row.content",
        "source_row",
        # Tool result payload — same rule.
        "tool.result",
        "tool.output",
    }
)


def is_forbidden_attribute(name: str) -> bool:
    """Return True when ``name`` is one of the forbidden attributes."""
    return name in FORBIDDEN_ATTRIBUTES


def filter_safe_attributes(
    attributes: dict[str, object] | None,
) -> dict[str, object]:
    """Return a copy of ``attributes`` with forbidden keys removed.

    Used at the boundary where a caller passes in a dict of attributes
    (e.g. from a decorator kwargs merge). We *silently drop* forbidden
    keys here rather than raise, because the caller often can't predict
    which keys the guard will reject (e.g. user-supplied metadata). The
    direct :func:`safe_set_attribute` path *does* raise, because that
    call site is deterministic.
    """
    if not attributes:
        return {}
    return {k: v for k, v in attributes.items() if k not in FORBIDDEN_ATTRIBUTES}
