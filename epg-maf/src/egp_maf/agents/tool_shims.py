"""``@tool``-decorated shims that expose Repository methods to the ReAct pass.

Design ADR-015: MAF agents call *tool shims*, not Repositories directly.
The shim is the point where request-scoped context (patient_id,
ClinicianContext) is bound; the Repository stays framework-agnostic.

Each factory function below returns the list of :class:`FunctionTool`
instances that a single specialist agent binds to. Every tool is
constructed per specialist run so it closes over the correct
:class:`ClinicianContext`. The factories are ordered to match the
prototype's tool sequence per agent.

Prototype references:

- ``agents/prs/tools/tools.py`` (3 tools)
- ``agents/genomic_variants/tools/tools.py`` (3 tools)
- ``agents/family_history/tools/tools.py`` (3 tools)
- ``agents/pgx/tools/tools.py`` (3 tools)
- ``agents/phenotype/tools/tools.py`` (2 tools)
"""

from __future__ import annotations

from typing import Any

from agent_framework import FunctionTool, tool

from egp_maf.services.repositories import (
    FamilyHistoryRepository,
    GenomicVariantsRepository,
    PGXRepository,
    PhenotypeRepository,
    PRSRepository,
)
from egp_maf.state.clinician_context import ClinicianContext


def _rows(models: list[Any]) -> list[dict[str, Any]]:
    """Convert a list of Pydantic models to a list of dicts.

    Used because the ReAct pass wants JSON-friendly tool outputs. Uses
    ``mode="json"`` so datetimes serialise to strings (matches the
    prototype's DuckDB-string output).
    """
    return [m.model_dump(mode="json") for m in models]


# ── PRS ──────────────────────────────────────────────────────────────


def build_prs_tools(
    repo: PRSRepository,
    ctx: ClinicianContext,
    patient_id: str,
) -> list[FunctionTool]:
    """Return the 3 PRS tools bound to this run's context."""

    @tool(
        name="explore_patient_prs",
        description=(
            "Lightweight discovery: return the PRS scores recorded for "
            "this patient with minimal fields (prs_name, disease_name, "
            "risk_band). Call this first to see which PRSes exist before "
            "looking up annotation detail."
        ),
    )
    async def _explore() -> list[dict[str, Any]]:
        return _rows(await repo.explore_patient_prs(ctx, patient_id))

    @tool(
        name="search_prs_annotations",
        description=(
            "Look up PRS annotation records from the reference table. "
            "Use exact prs_name from explore_patient_prs, or a substring "
            "disease_name filter for free-text queries."
        ),
    )
    async def _search(
        prs_name: str | None = None,
        disease_name: str | None = None,
    ) -> list[dict[str, Any]]:
        return _rows(
            await repo.search_prs_annotations(
                ctx, prs_name=prs_name, disease_name=disease_name
            )
        )

    @tool(
        name="get_patient_prs",
        description=(
            "Retrieve PRS scores for the patient JOINed with annotation "
            "metadata. Optional exact filters: prs_name, disease_name."
        ),
    )
    async def _get(
        prs_name: str | None = None,
        disease_name: str | None = None,
    ) -> list[dict[str, Any]]:
        return _rows(
            await repo.get_patient_prs(
                ctx, patient_id, prs_name=prs_name, disease_name=disease_name
            )
        )

    return [_explore, _search, _get]


# ── Genomic variants ─────────────────────────────────────────────────


def build_genomic_variants_tools(
    repo: GenomicVariantsRepository,
    ctx: ClinicianContext,
    patient_id: str,
) -> list[FunctionTool]:
    """Return the 3 genomic-variant tools bound to this run's context."""

    @tool(
        name="explore_patient_genomic_variants",
        description=(
            "Lightweight discovery: return the variant IDs and genotypes "
            "recorded for this patient. Call this first to see which "
            "variants exist."
        ),
    )
    async def _explore() -> list[dict[str, Any]]:
        return _rows(await repo.explore_patient_genomic_variants(ctx, patient_id))

    @tool(
        name="search_variant_annotations",
        description=(
            "Look up variant annotation records. Exact match on "
            "variant_id; substring match on gene/pathogenicity/disease_name."
        ),
    )
    async def _search(
        variant_id: str | None = None,
        gene: str | None = None,
        pathogenicity: str | None = None,
        disease_name: str | None = None,
    ) -> list[dict[str, Any]]:
        return _rows(
            await repo.search_variant_annotations(
                ctx,
                variant_id=variant_id,
                gene=gene,
                pathogenicity=pathogenicity,
                disease_name=disease_name,
            )
        )

    @tool(
        name="get_patient_genomic_variants",
        description=(
            "Retrieve variants for the patient with full typed annotations. "
            "annotations_json is decomposed deterministically in Python "
            "(never by the LLM). Optional exact filters: variant_id, "
            "disease_name, gene, variant_type, pathogenicity."
        ),
    )
    async def _get(
        variant_id: str | None = None,
        disease_name: str | None = None,
        gene: str | None = None,
        variant_type: str | None = None,
        pathogenicity: str | None = None,
    ) -> list[dict[str, Any]]:
        return _rows(
            await repo.get_patient_genomic_variants(
                ctx,
                patient_id,
                variant_id=variant_id,
                disease_name=disease_name,
                gene=gene,
                variant_type=variant_type,
                pathogenicity=pathogenicity,
            )
        )

    return [_explore, _search, _get]


# ── Family history ───────────────────────────────────────────────────


def build_family_history_tools(
    repo: FamilyHistoryRepository,
    ctx: ClinicianContext,
    patient_id: str,
) -> list[FunctionTool]:
    """Return the 3 family-history tools bound to this run's context."""

    @tool(
        name="explore_patient_family_history",
        description=(
            "Lightweight discovery: return the disease/criteria combos "
            "recorded for this patient with their threshold results."
        ),
    )
    async def _explore() -> list[dict[str, Any]]:
        return _rows(await repo.explore_patient_family_history(ctx, patient_id))

    @tool(
        name="search_family_history_annotations",
        description=(
            "Look up family history criteria annotations. Exact "
            "criteria_name; substring disease_name filter."
        ),
    )
    async def _search(
        criteria_name: str | None = None,
        disease_name: str | None = None,
    ) -> list[dict[str, Any]]:
        return _rows(
            await repo.search_family_history_annotations(
                ctx, criteria_name=criteria_name, disease_name=disease_name
            )
        )

    @tool(
        name="get_patient_family_history",
        description=(
            "Retrieve family history records for the patient JOINed with "
            "criteria annotations. Optional exact filters: disease_name, "
            "criteria_name."
        ),
    )
    async def _get(
        disease_name: str | None = None,
        criteria_name: str | None = None,
    ) -> list[dict[str, Any]]:
        internal = await repo.get_patient_family_history(
            ctx, patient_id, disease_name=disease_name, criteria_name=criteria_name
        )
        # LLM view is the public projection — privacy fields never reach
        # the model. Specialist still calls the Repository directly (via
        # itself, not via this tool) to obtain the internal projection
        # for provenance/audit.
        public = [r.to_public() for r in internal]
        return _rows(public)

    return [_explore, _search, _get]


# ── PGX ──────────────────────────────────────────────────────────────


def build_pgx_tools(
    repo: PGXRepository,
    ctx: ClinicianContext,
    patient_id: str,
) -> list[FunctionTool]:
    """Return the 3 PGX tools bound to this run's context."""

    @tool(
        name="explore_patient_pgx",
        description=(
            "Lightweight discovery: return the genes assessed for this "
            "patient with diplotype and phenotype."
        ),
    )
    async def _explore() -> list[dict[str, Any]]:
        return _rows(await repo.explore_patient_pgx(ctx, patient_id))

    @tool(
        name="search_pgx_annotations",
        description=(
            "Look up PGX annotation records. Exact gene/phenotype; "
            "substring drug filter."
        ),
    )
    async def _search(
        gene: str | None = None,
        phenotype: str | None = None,
        drug: str | None = None,
    ) -> list[dict[str, Any]]:
        return _rows(
            await repo.search_pgx_annotations(
                ctx, gene=gene, phenotype=phenotype, drug=drug
            )
        )

    @tool(
        name="get_patient_pgx",
        description=(
            "Retrieve the patient's PGX status JOINed with drug "
            "recommendations. Optional exact gene filter."
        ),
    )
    async def _get(gene: str | None = None) -> list[dict[str, Any]]:
        return _rows(await repo.get_patient_pgx(ctx, patient_id, gene=gene))

    return [_explore, _search, _get]


# ── Phenotype ────────────────────────────────────────────────────────


def build_phenotype_tools(
    repo: PhenotypeRepository,
    ctx: ClinicianContext,
    patient_id: str,
) -> list[FunctionTool]:
    """Return the 2 phenotype tools bound to this run's context."""

    @tool(
        name="explore_patient_phenotype",
        description=(
            "Lightweight discovery: return the distinct diseases/terms "
            "recorded for this patient. Call this first before fetching "
            "encounter detail."
        ),
    )
    async def _explore() -> list[dict[str, Any]]:
        return _rows(await repo.explore_patient_phenotype(ctx, patient_id))

    @tool(
        name="get_patient_diagnoses",
        description=(
            "Retrieve grouped diagnosis history for the patient. Optional "
            "disease_name (exact) or search_term (fuzzy across name/term/"
            "description). Both filters combine as OR when both provided."
        ),
    )
    async def _get(
        disease_name: str | None = None,
        search_term: str | None = None,
    ) -> list[dict[str, Any]]:
        return _rows(
            await repo.get_patient_diagnoses(
                ctx,
                patient_id,
                disease_name=disease_name,
                search_term=search_term,
            )
        )

    return [_explore, _get]
