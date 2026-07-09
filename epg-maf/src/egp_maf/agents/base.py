"""Specialist template — the 10-step recipe every domain follows.

The prototype's five specialist ``*_node`` functions all follow the
same shape (see Discovery §2.4 and the plan's F07.1 acceptance criteria):

1. Read `patient_id`, `original_query`, `requested_diseases` from state.
2. Build a user message from those.
3. **ReAct pass** — LLM + tools produce a message trace with tool calls.
4. Extract raw ``ToolExecution`` records from the trace.
5. **Structured-extraction pass** — a second LLM call fills a
   :class:`<Domain>ResultList` from the tool trace.
6. Attach ``DBProvenance`` records per typed result.
7. Set ``interpretation_model`` / ``summary_model`` from settings.
8. Compute domain-specific programmatic fields (``pathogenic_count``,
   ``genes_assessed``, ``diseases_meeting_threshold``, …).
9. **Domain hook** — apply any last-mile transform (family_history
   applies :meth:`.to_public`).
10. Wrap in the domain's :class:`SpecialistSlotOutput` subclass.

W05 realises this as an abstract :class:`SpecialistBase`. Every concrete
specialist implements just the pieces that vary: which tools it binds,
which result-list schema it extracts into, which programmatic derived
fields to compute, and what its ``to_slot_output`` looks like. The
rest (state read, ReAct dispatch, extraction dispatch, provenance,
model attribution) is inherited.

The two LLM calls happen through a :class:`SpecialistLlm` protocol so
unit tests substitute deterministic stubs. W05 ships the real MAF
implementation in :mod:`egp_maf.agents.llm_bridge`.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Generic, Protocol, TypeVar

from agent_framework import FunctionTool
from pydantic import BaseModel

from egp_maf.errors import EgpError
from egp_maf.state.clinician_context import ClinicianContext
from egp_maf.state.provenance import DBProvenance
from egp_maf.state.results.family_history import (  # noqa: F401 — used by subclasses
    FamilyHistoryResultList,
)

_logger = logging.getLogger(__name__)

# ── Types shared by all specialists ─────────────────────────────────

ResultListT = TypeVar("ResultListT", bound=BaseModel)


class SpecialistRunError(EgpError):
    """Raised when a specialist run fails unrecoverably. Callers
    (:class:`SpecialistExecutor`) translate this into a ``status='failed'``
    :class:`SpecialistSlotOutput` and swallow it — the workflow keeps
    running."""

    error_code = "specialist_failed"
    http_status = 500


@dataclass(frozen=True)
class ToolCall:
    """Serialised record of one tool call made by the LLM during ReAct.

    Domain-neutral wrapper around whatever the LLM framework produces.
    The :class:`SpecialistLlm` implementation is responsible for
    converting its native format into this shape.
    """

    tool_name: str
    tool_parameters: dict[str, Any]
    tool_output: list[dict[str, Any]]
    error: str | None = None


@dataclass(frozen=True)
class SpecialistReactRequest:
    """Inputs to the ReAct pass."""

    system_prompt: str
    user_message: str
    tools: list[FunctionTool]


@dataclass(frozen=True)
class SpecialistReactResult:
    """Outputs from the ReAct pass.

    ``transcript`` is the full serialisable turn history — passed
    verbatim into the extraction pass so the LLM can see everything it
    called. ``tool_calls`` is the parsed audit trail used to build
    :class:`DBProvenance` records.
    """

    transcript: list[dict[str, Any]]
    tool_calls: list[ToolCall]


@dataclass(frozen=True)
class SpecialistExtractionRequest(Generic[ResultListT]):
    """Inputs to the extraction pass."""

    transcript: list[dict[str, Any]]
    extraction_instruction: str
    response_schema: type[ResultListT]


class SpecialistLlm(Protocol):
    """The seam that isolates every LLM call.

    - :meth:`run_react` — one ReAct-style call with tools; returns a
      transcript + parsed tool trace.
    - :meth:`run_extraction` — one structured-output call; returns an
      instance of ``response_schema``.

    W05's :class:`~egp_maf.agents.llm_bridge.MafSpecialistLlm` implements
    this against MAF's ``Agent`` + ``OpenAIChatClient``. Tests supply
    :class:`~egp_maf.agents.llm_bridge.StubSpecialistLlm`.
    """

    async def run_react(self, request: SpecialistReactRequest) -> SpecialistReactResult: ...

    async def run_extraction(
        self, request: SpecialistExtractionRequest[ResultListT]
    ) -> ResultListT: ...


# ── The template ─────────────────────────────────────────────────────


@dataclass(frozen=True)
class SpecialistInputs:
    """The three canonical inputs a specialist reads from state."""

    patient_id: str
    original_query: str
    requested_diseases: list[str] | None


class SpecialistBase(ABC, Generic[ResultListT]):
    """Template method for the 10-step specialist recipe.

    Subclasses provide domain specifics. Everything else lives here.
    """

    #: Short name — matches the workflow's specialist identifier and the
    #: prototype's ``agents_completed`` entry.
    name: str

    def __init__(
        self,
        *,
        system_prompt: str,
        interpretation_model_name: str,
    ) -> None:
        self._system_prompt = system_prompt
        self._interpretation_model_name = interpretation_model_name

    # ── Abstract seams (per-domain) ─────────────────────────────────

    @abstractmethod
    def build_tools(
        self,
        ctx: ClinicianContext,
        patient_id: str,
    ) -> list[FunctionTool]:
        """Return the domain's tool shims bound to this run."""

    @abstractmethod
    def build_extraction_instruction(self, patient_id: str) -> str:
        """The natural-language instruction appended to the ReAct trace
        for the extraction pass. Domain-specific because it names which
        fields the LLM should fill (interpretation, summary, sub-model
        breakouts, etc.)."""

    @property
    @abstractmethod
    def response_schema(self) -> type[ResultListT]:
        """The Pydantic type the extraction pass fills."""

    @abstractmethod
    async def build_provenance(
        self,
        *,
        result_list: ResultListT,
        tool_calls: list[ToolCall],
        ctx: ClinicianContext,
        patient_id: str,
    ) -> ResultListT:
        """Attach :class:`DBProvenance` to every typed result. Domain-
        specific because each domain matches provenance rows to results
        on a different identifier (``prs_name``, ``variant_id``,
        ``(disease_name, criteria_name)``, ``gene``, ``disease_name``)."""

    @abstractmethod
    def apply_derived_fields(
        self,
        result_list: ResultListT,
        patient_id: str,
    ) -> ResultListT:
        """Compute programmatic derived fields on the ``ResultList``
        wrapper (``pathogenic_count``, ``genes_assessed``,
        ``diseases_meeting_threshold``, ``relevant_disease_names``, …).
        Called after the extraction pass; result-level LLM fields already
        exist by this point."""

    @abstractmethod
    def to_slot_output(
        self,
        result_list: ResultListT | None,
        *,
        status: str,
        errors: list[str],
    ) -> BaseModel:
        """Wrap the (optional) result list in the domain's
        :class:`SpecialistSlotOutput` subclass. **This is the hook family
        history uses to apply the privacy-strip** (via ``to_public``)."""

    # ── The template method itself ──────────────────────────────────

    async def run(
        self,
        *,
        inputs: SpecialistInputs,
        ctx: ClinicianContext,
        llm: SpecialistLlm,
    ) -> BaseModel:
        """Run the full 10-step pipeline. Returns the domain-specific
        :class:`SpecialistSlotOutput`.

        This method never raises: every failure path produces a
        ``status='failed'`` slot with a populated ``errors`` list.
        Callers (the workflow executor) always get a valid slot output.
        """
        started_at = datetime.now(timezone.utc)
        errors: list[str] = []

        try:
            # Steps 1–2: read inputs, build user message.
            user_message = self._build_user_message(inputs)

            # Step 3: ReAct pass.
            tools = self.build_tools(ctx, inputs.patient_id)
            react = await llm.run_react(
                SpecialistReactRequest(
                    system_prompt=self._system_prompt,
                    user_message=user_message,
                    tools=tools,
                )
            )

            # Step 4: tool trace is already parsed by the LLM impl.

            # Step 5: extraction pass.
            extracted = await llm.run_extraction(
                SpecialistExtractionRequest(
                    transcript=react.transcript,
                    extraction_instruction=self.build_extraction_instruction(
                        inputs.patient_id
                    ),
                    response_schema=self.response_schema,
                )
            )

            # Step 6: provenance.
            extracted = await self.build_provenance(
                result_list=extracted,
                tool_calls=react.tool_calls,
                ctx=ctx,
                patient_id=inputs.patient_id,
            )

            # Step 7: model attribution — done here because it applies
            # uniformly to any result_list with ``interpretation_model``
            # / ``summary_model`` fields (all 5 domains have them).
            self._attribute_model(extracted)

            # Step 8: derived fields.
            extracted = self.apply_derived_fields(extracted, inputs.patient_id)

            # Steps 9–10: domain-specific transform + wrap.
            slot_output = self.to_slot_output(
                extracted, status="completed", errors=errors
            )

            _logger.info(
                "specialist.run.completed",
                extra={
                    "specialist": self.name,
                    "patient_id": inputs.patient_id,
                    "duration_ms": int(
                        (datetime.now(timezone.utc) - started_at).total_seconds() * 1000
                    ),
                    "tool_call_count": len(react.tool_calls),
                },
            )
            return slot_output

        except Exception as exc:  # noqa: BLE001 — must not raise out of a specialist
            _logger.exception(
                "specialist.run.failed",
                extra={
                    "specialist": self.name,
                    "patient_id": inputs.patient_id,
                    "error_class": type(exc).__name__,
                },
            )
            errors.append(f"{type(exc).__name__}: {exc}")
            return self.to_slot_output(None, status="failed", errors=errors)

    # ── Helpers ─────────────────────────────────────────────────────

    def _build_user_message(self, inputs: SpecialistInputs) -> str:
        """The shared user-message shape used by every prototype specialist."""
        if inputs.requested_diseases:
            disease_line = (
                "Focus on the following diseases only: "
                + ", ".join(inputs.requested_diseases)
                + "."
            )
        else:
            disease_line = self._default_scope_line()
        query_line = f"User query context: {inputs.original_query or '(none)'}"
        return (
            f"Patient ID: {inputs.patient_id}\n\n"
            f"{disease_line}\n\n"
            f"{query_line}"
        )

    def _default_scope_line(self) -> str:
        """Overridable by subclasses that phrase the 'all' scope differently.

        Default matches the prototype PRS/PGX/FamilyHistory/GenomicVariants
        wording. Phenotype/prompt-specific specialists override.
        """
        return "Retrieve all available records for this patient."

    def _attribute_model(self, result_list: BaseModel) -> None:
        """Set ``interpretation_model`` / ``summary_model`` fields where
        the LLM populated an interpretation/summary but didn't set the
        attribution (matches the prototype's behaviour)."""
        model_name = self._interpretation_model_name

        results = getattr(result_list, "results", None)
        if isinstance(results, list):
            for r in results:
                interp = getattr(r, "interpretation", None)
                if interp is not None and getattr(r, "interpretation_model", None) is None:
                    try:
                        r.interpretation_model = model_name
                    except (AttributeError, TypeError):
                        # Frozen model or unsupported field — no-op.
                        pass

        summary = getattr(result_list, "summary", None)
        if summary is not None and getattr(result_list, "summary_model", None) is None:
            try:
                result_list.summary_model = model_name
            except (AttributeError, TypeError):
                pass


# ── Provenance helper (shared across domains) ────────────────────────


def attach_provenance_to_results(
    *,
    results: list[Any],
    tool_calls: list[ToolCall],
    tool_source_table: dict[str, str],
    tool_fields_derived: dict[str, list[str]],
    row_matches_result: Any,
    provenance_builder: Any = None,
) -> None:
    """Attach one :class:`DBProvenance` per (result × source-table) pair.

    Ports the prototype's ``_attach_provenance`` shape (see
    ``agents/prs/graph/graph.py::_attach_provenance``) generically.

    Parameters
    ----------
    results:
        The typed result objects — each gains a :attr:`provenance` entry.
    tool_calls:
        The parsed ReAct-pass audit trail.
    tool_source_table:
        Provenance-eligible tool names → ``source_table`` string. Only
        ``get_*`` tools appear here; ``explore_*`` and ``search_*`` do
        not carry provenance (Discovery §5.7).
    tool_fields_derived:
        Same keys as ``tool_source_table``; value is the list of fields
        on the result derived from this tool.
    row_matches_result:
        Callable ``(row: dict, result: T) -> bool`` — domain-specific
        matcher. E.g. PRS matches on ``row["prs_name"] == result.prs_name``;
        family history matches on the ``(disease_name, criteria_name)``
        pair.
    provenance_builder:
        Optional ``(**kwargs) -> DBProvenance`` factory so specialists
        can inject the shared :class:`ProvenanceService` (needed for
        consistent ``retrieved_at`` and future OTEL correlation). When
        ``None``, constructs :class:`DBProvenance` directly.
    """
    for result in results:
        seen_tools: set[str] = set()
        for call in tool_calls:
            if call.tool_name not in tool_source_table:
                continue
            if call.tool_name in seen_tools:
                continue
            for row in call.tool_output:
                if not isinstance(row, dict):
                    continue
                if not row_matches_result(row, result):
                    continue
                kwargs: dict[str, Any] = dict(
                    tool_name=call.tool_name,
                    tool_parameters=dict(call.tool_parameters),
                    source_table=tool_source_table[call.tool_name],
                    source_row=dict(row),
                    fields_derived=list(tool_fields_derived[call.tool_name]),
                )
                provenance = (
                    provenance_builder(**kwargs)
                    if provenance_builder is not None
                    else DBProvenance(**kwargs)
                )
                result.provenance.append(provenance)
                seen_tools.add(call.tool_name)
                break
