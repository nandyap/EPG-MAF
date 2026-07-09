"""Per-agent LLM configuration.

Byte-parity port of the prototype's ``config/llm.py`` ``AGENT_LLM_CONFIGS``
dict. Same seven agents, same model IDs, same temperatures, same notes.

The prototype instantiated ``langchain_openai.ChatOpenAI`` here. The MAF
implementation defers construction to
``egp_maf.infrastructure.compass_client.LlmClientFactory`` so the factory
can be swapped independently of the config table.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AgentLlmConfig:
    """Per-agent model configuration.

    Mirrors the shape of the prototype's ``AgentLLMConfig`` dataclass.

    Attributes
    ----------
    model:
        Compass model id (e.g. ``gpt-4.1``, ``gpt-5.1``).
    temperature:
        Sampling temperature. Always ``0.0`` in Phase 1 (deterministic
        replay for clinical evaluation — see Design ADR-018).
    reasoning:
        Documents intent — is this a reasoning-tier model.
    note:
        Why this model was chosen for this agent (prototype-preserved).
    """

    model: str
    temperature: float
    reasoning: bool = False
    note: str = ""


# ── Per-agent config ─────────────────────────────────────────────────
# Change model choices here — nowhere else.
# Byte-equal to the prototype (verified by tests/parity/test_llm_config_parity.py).

AGENT_LLM_CONFIGS: dict[str, AgentLlmConfig] = {
    "prs": AgentLlmConfig(
        model="gpt-4.1",
        temperature=0.0,
        note=(
            "Straightforward retrieval + percentile interpretation. "
            "Standard model sufficient."
        ),
    ),
    "pgx": AgentLlmConfig(
        model="gpt-4.1",
        temperature=0.0,
        note="Drug-gene interaction lookup. Deterministic — no reasoning needed.",
    ),
    "genomic_variants": AgentLlmConfig(
        model="gpt-4.1",
        temperature=0.0,
        note=(
            "Variant pathogenicity interpretation benefits from reasoning — "
            "evidence weighting across ACMG criteria is complex."
        ),
    ),
    "family_history": AgentLlmConfig(
        model="gpt-4.1",
        temperature=0.0,
        note="Pedigree threshold evaluation. Switch to o3 for production once available.",
    ),
    "phenotype": AgentLlmConfig(
        model="gpt-4.1",
        temperature=0.0,
        note="Diagnosis/EHR retrieval. Structured DB lookups, minimal reasoning.",
    ),
    "main": AgentLlmConfig(
        model="gpt-4.1",
        temperature=0.0,
        note="Orchestrator — routes queries to subagents. gpt-4.1 used for testing",
    ),
    "chat": AgentLlmConfig(
        model="gpt-5.1",
        temperature=0.0,
        note=(
            "Chat agent for user interaction. More advanced model for better "
            "conversational quality. "
        ),
    ),
}

# Frozenset of legal agent names for compile-time safety checks.
KNOWN_AGENT_NAMES: frozenset[str] = frozenset(AGENT_LLM_CONFIGS.keys())
