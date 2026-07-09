"""Specialist registry — one lookup keyed by specialist name.

The DI container constructs this once at startup. The workflow's
:class:`~egp_maf.workflow.orchestration.specialist_executor.SpecialistExecutor`
looks up its assigned specialist from here per run so we don't rebind
the LLM/repository on every dispatch.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

from egp_maf.agents.base import SpecialistBase, SpecialistLlm
from egp_maf.agents.family_history import FamilyHistorySpecialist
from egp_maf.agents.genomic_variants import GenomicVariantsSpecialist
from egp_maf.agents.llm_bridge import MafSpecialistLlm
from egp_maf.agents.pgx import PGXSpecialist
from egp_maf.agents.phenotype import PhenotypeSpecialist
from egp_maf.agents.prs import PRSSpecialist
from egp_maf.config.llm_config import AGENT_LLM_CONFIGS
from egp_maf.errors import ConfigurationError
from egp_maf.infrastructure.compass_client import LlmClientFactory
from egp_maf.services.prompt_service import PromptService
from egp_maf.services.provenance import ProvenanceService
from egp_maf.services.repositories import (
    FamilyHistoryRepository,
    GenomicVariantsRepository,
    PGXRepository,
    PhenotypeRepository,
    PRSRepository,
)


@dataclass
class SpecialistRegistry:
    """Frozen lookup of the 5 built specialists + their LLM bridges."""

    specialists: dict[str, SpecialistBase] = field(default_factory=dict)
    llms: dict[str, SpecialistLlm] = field(default_factory=dict)

    def get(self, name: str) -> SpecialistBase:
        if name not in self.specialists:
            raise ConfigurationError(
                f"Unknown specialist '{name}'. Known: {sorted(self.specialists)}"
            )
        return self.specialists[name]

    def get_llm(self, name: str) -> SpecialistLlm:
        if name not in self.llms:
            raise ConfigurationError(
                f"No SpecialistLlm registered for '{name}'."
            )
        return self.llms[name]

    def names(self) -> list[str]:
        return sorted(self.specialists.keys())


_PROMPT_NAME: dict[str, str] = {
    "prs": "prs_agent",
    "genomic_variants": "genomic_variants_agent",
    "family_history": "family_history_agent",
    "pgx": "pgx_agent",
    "phenotype": "phenotype_agent",
}


def build_specialist_registry(
    *,
    prs_repo: PRSRepository,
    genomic_variants_repo: GenomicVariantsRepository,
    family_history_repo: FamilyHistoryRepository,
    pgx_repo: PGXRepository,
    phenotype_repo: PhenotypeRepository,
    llm_client_factory: LlmClientFactory,
    prompt_service: PromptService,
    provenance_service: ProvenanceService,
    llm_overrides: Mapping[str, SpecialistLlm] | None = None,
) -> SpecialistRegistry:
    """Wire the 5 specialists with real MAF-backed LLM bridges by default.

    ``llm_overrides`` lets callers (tests, W06 preview scenarios) inject
    stubs per specialist by name.
    """
    llm_overrides = dict(llm_overrides or {})
    registry = SpecialistRegistry()

    def _llm_for(name: str) -> SpecialistLlm:
        if name in llm_overrides:
            return llm_overrides[name]
        return MafSpecialistLlm(
            client=llm_client_factory.get(name),
            agent_id=f"specialist_{name}",
            temperature=AGENT_LLM_CONFIGS[name].temperature,
        )

    def _prompt(name: str) -> str:
        return prompt_service.get(_PROMPT_NAME[name])

    def _model(name: str) -> str:
        return AGENT_LLM_CONFIGS[name].model

    registry.specialists["prs"] = PRSSpecialist(
        system_prompt=_prompt("prs"),
        interpretation_model_name=_model("prs"),
        repository=prs_repo,
        provenance_service=provenance_service,
    )
    registry.specialists["genomic_variants"] = GenomicVariantsSpecialist(
        system_prompt=_prompt("genomic_variants"),
        interpretation_model_name=_model("genomic_variants"),
        repository=genomic_variants_repo,
        provenance_service=provenance_service,
    )
    registry.specialists["family_history"] = FamilyHistorySpecialist(
        system_prompt=_prompt("family_history"),
        interpretation_model_name=_model("family_history"),
        repository=family_history_repo,
        provenance_service=provenance_service,
    )
    registry.specialists["pgx"] = PGXSpecialist(
        system_prompt=_prompt("pgx"),
        interpretation_model_name=_model("pgx"),
        repository=pgx_repo,
        provenance_service=provenance_service,
    )
    registry.specialists["phenotype"] = PhenotypeSpecialist(
        system_prompt=_prompt("phenotype"),
        interpretation_model_name=_model("phenotype"),
        repository=phenotype_repo,
        provenance_service=provenance_service,
    )

    for name in registry.specialists:
        registry.llms[name] = _llm_for(name)

    return registry
