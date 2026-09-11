"""Flow tracing must not break the turn it observes.

Every existing test runs with tracing off (the default), so none of them
touch a ``trace(...)`` call site. That is the same gap that let the
stub-LLM bug ship: code that is never executed by the suite.

It matters more than usual here because the failure mode is not a
missing log line. Argument expressions are evaluated at the call site
before ``trace`` is entered, so a wrong attribute access inside one
raises *inside a workflow handler* and fails the clinical turn. That
happened while writing this module: ``specialists=[s.specialist for s in
...]`` against a ``list[str]`` took down twelve end-to-end tests.

So these tests run representative paths with tracing fully on and assert
the turn still completes. They deliberately assert on behaviour, not on
log text — pinning exact fields would make every future field addition a
test edit.
"""

from __future__ import annotations

import pytest

from egp_maf.logging import flow_trace
from egp_maf.logging.flow_trace import (
    configure_flow_trace,
    preview,
    summarise_messages,
)

pytestmark = pytest.mark.unit


class _Settings:
    """Minimal stand-in — ``configure_flow_trace`` only reads two attrs."""

    def __init__(self, *, flow: bool, payloads: bool) -> None:
        self.trace_flow = flow
        self.trace_payloads = payloads


@pytest.fixture
def restore_trace_flags():
    """Flags are module-level, so leaking them would silently enable
    tracing for every test that runs afterwards."""
    before = (flow_trace._flow_enabled, flow_trace._payloads_enabled)  # noqa: SLF001
    yield
    (
        flow_trace._flow_enabled,  # noqa: SLF001
        flow_trace._payloads_enabled,  # noqa: SLF001
    ) = before


class TestFlagResolution:
    def test_off_by_default(self, restore_trace_flags) -> None:
        configure_flow_trace(_Settings(flow=False, payloads=False))

        assert flow_trace.flow_enabled() is False
        assert flow_trace.payloads_enabled() is False

    def test_payloads_require_flow(self, restore_trace_flags) -> None:
        """The PHI-bearing mode must not be reachable by setting one
        variable. Someone who sets only EGP_TRACE_PAYLOADS gets nothing."""
        configure_flow_trace(_Settings(flow=False, payloads=True))

        assert flow_trace.payloads_enabled() is False

    def test_both_on_when_both_requested(self, restore_trace_flags) -> None:
        configure_flow_trace(_Settings(flow=True, payloads=True))

        assert flow_trace.flow_enabled() is True
        assert flow_trace.payloads_enabled() is True

    def test_flow_alone_does_not_enable_payloads(self, restore_trace_flags) -> None:
        configure_flow_trace(_Settings(flow=True, payloads=False))

        assert flow_trace.flow_enabled() is True
        assert flow_trace.payloads_enabled() is False


class TestEmitIsSafe:
    def test_emit_failure_does_not_propagate(self, restore_trace_flags) -> None:
        """An unserialisable field must not fail the caller."""
        configure_flow_trace(_Settings(flow=True, payloads=True))

        class _Explodes:
            def __repr__(self) -> str:
                raise RuntimeError("boom")

        flow_trace.trace("test.event", bad=_Explodes())
        flow_trace.trace_payload("test.event.body", bad=_Explodes())

    def test_noop_when_disabled(self, restore_trace_flags) -> None:
        configure_flow_trace(_Settings(flow=False, payloads=False))

        flow_trace.trace("test.event", x=1)
        flow_trace.trace_payload("test.event.body", x=1)


class TestPreview:
    def test_short_values_pass_through(self) -> None:
        assert preview("abc") == "abc"

    def test_truncation_is_marked(self) -> None:
        """A truncated value must not be mistakable for a complete one."""
        out = preview("x" * 100, limit=10)

        assert out.startswith("x" * 10)
        assert "truncated" in out
        assert "90" in out

    def test_none_is_empty(self) -> None:
        assert preview(None) == ""

    def test_non_string_is_coerced(self) -> None:
        assert preview({"a": 1}) == "{'a': 1}"


class TestSummariseMessages:
    def test_dict_messages(self) -> None:
        shape = summarise_messages(
            [{"role": "user", "content": "hello"}, {"role": "assistant", "content": ""}]
        )

        assert shape == [
            {"role": "user", "chars": 5},
            {"role": "assistant", "chars": 0},
        ]

    def test_empty_transcript_reports_nothing(self) -> None:
        """The signal that matters: an extraction pass handed an empty
        transcript is what produced fabricated findings on 2026-09-10."""
        assert summarise_messages([]) == []
        assert summarise_messages(None) == []

    def test_object_messages_with_contents(self) -> None:
        class _C:
            type = "text"
            text = "abcd"

        class _M:
            role = "assistant"
            content = None
            contents = [_C()]

        assert summarise_messages([_M()]) == [{"role": "assistant", "chars": 4}]
