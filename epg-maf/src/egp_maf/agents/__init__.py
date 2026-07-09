"""Specialist agents — W05.

Realises the design promise that W04 set up: 5 domain specialists, each a
ReAct + structured-extraction two-pass pipeline over the Repository from
W03. Every specialist follows the same 10-step recipe (see
:class:`.base.SpecialistBase`) — only the SQL and the interpretation
prompt change.

Public API:

- :class:`.base.SpecialistBase` — the template method that owns the recipe.
- :class:`.base.SpecialistLlm` — the protocol that isolates every LLM
  call. W05 ships a MAF ``Agent``-backed implementation
  (:class:`.llm_bridge.MafSpecialistLlm`); unit tests use deterministic
  stubs.
- :class:`.tool_shims` — 15 :func:`agent_framework.tool`-wrapped functions
  that expose Repository methods to the ReAct pass.
- :class:`.state_outputs` — 5 :class:`SpecialistSlotOutput` subclasses
  (one per domain) carrying typed payloads.
- :class:`.prs.PRSSpecialist` etc. — the 5 concrete specialists.

MAF touch points: :class:`agent_framework.Agent`,
:func:`agent_framework.tool`, :class:`agent_framework.ChatOptions`
(for structured extraction), :class:`agent_framework.openai.OpenAIChatClient`
(via :class:`~egp_maf.infrastructure.compass_client.LlmClientFactory`).
"""

from egp_maf.agents.base import (
    SpecialistBase,
    SpecialistExtractionRequest,
    SpecialistLlm,
    SpecialistReactRequest,
    SpecialistReactResult,
    SpecialistRunError,
)
from egp_maf.agents.family_history import FamilyHistorySpecialist
from egp_maf.agents.genomic_variants import GenomicVariantsSpecialist
from egp_maf.agents.pgx import PGXSpecialist
from egp_maf.agents.phenotype import PhenotypeSpecialist
from egp_maf.agents.prs import PRSSpecialist
from egp_maf.agents.registry import SpecialistRegistry, build_specialist_registry
from egp_maf.agents.state_outputs import (
    FamilyHistoryStateOutput,
    GenomicVariantsStateOutput,
    PGXStateOutput,
    PhenotypeStateOutput,
    PRSStateOutput,
    SpecialistSlotOutput,
    SpecialistStatus,
)

__all__ = [
    "FamilyHistorySpecialist",
    "FamilyHistoryStateOutput",
    "GenomicVariantsSpecialist",
    "GenomicVariantsStateOutput",
    "PGXSpecialist",
    "PGXStateOutput",
    "PRSSpecialist",
    "PRSStateOutput",
    "PhenotypeSpecialist",
    "PhenotypeStateOutput",
    "SpecialistBase",
    "SpecialistExtractionRequest",
    "SpecialistLlm",
    "SpecialistReactRequest",
    "SpecialistReactResult",
    "SpecialistRegistry",
    "SpecialistRunError",
    "SpecialistSlotOutput",
    "SpecialistStatus",
    "build_specialist_registry",
]
