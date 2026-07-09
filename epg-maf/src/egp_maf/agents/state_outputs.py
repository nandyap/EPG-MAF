"""Specialist state outputs — the slim envelopes written to workflow state.

One :class:`SpecialistSlotOutput` subclass per domain, each carrying the
typed :class:`<Domain>ResultList` from :mod:`egp_maf.state.results`.

These types are the payload of :class:`~egp_maf.workflow.state.SpecialistSlot`
in W05 (in W04 the slot carried an opaque ``dict``). Specialists always
produce one of these; the wrapping ``SpecialistSlot`` is set by the
:class:`~egp_maf.workflow.orchestration.specialist_executor.SpecialistExecutor`.

**Family history** ships a ``FamilyHistoryStateOutput`` whose ``output``
is the **public projection** (privacy fields absent from the type). The
specialist calls ``.to_public()`` on the internal results before wrapping.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from egp_maf.state.results.family_history import FamilyHistoryResultListPublic
from egp_maf.state.results.genomic_variants import GenomicVariantsResultList
from egp_maf.state.results.pgx import PGXResultList
from egp_maf.state.results.phenotype import PhenotypeResultList
from egp_maf.state.results.prs import PRSResultList

SpecialistStatus = Literal["completed", "failed", "partial"]


class SpecialistSlotOutput(BaseModel):
    """Base envelope. Subclassed once per domain (Design §5.5).

    ``status`` mirrors the prototype's specialist state:
    - ``completed`` — output populated, no errors.
    - ``partial`` — output populated but the run raised recoverable errors.
    - ``failed`` — output is ``None``; ``errors`` explains why.

    ``interpretation_model`` and ``summary_model`` attribution lives on
    the payload types themselves (per :mod:`egp_maf.state.results`); the
    envelope is deliberately narrow.
    """

    status: SpecialistStatus
    errors: list[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


class PRSStateOutput(SpecialistSlotOutput):
    output: PRSResultList | None = None


class GenomicVariantsStateOutput(SpecialistSlotOutput):
    output: GenomicVariantsResultList | None = None


class FamilyHistoryStateOutput(SpecialistSlotOutput):
    """Family-history output — payload is the **public** projection.

    :class:`FamilyHistoryResultListPublic` is the type produced by
    :meth:`egp_maf.state.results.family_history.FamilyHistoryResultList.to_public`.
    The three privacy-sensitive fields are absent from the type entirely
    (not merely null), which is the contract Design §11.7 / ADR-017
    enforces at the wire boundary.
    """

    output: FamilyHistoryResultListPublic | None = None


class PGXStateOutput(SpecialistSlotOutput):
    output: PGXResultList | None = None


class PhenotypeStateOutput(SpecialistSlotOutput):
    output: PhenotypeResultList | None = None
