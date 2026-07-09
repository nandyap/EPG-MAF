"""
LLM model configuration.

All per-agent model choices live here so that:
- swapping a model for any agent is a one-line change
- reasoning vs standard models are explicit and documented
- agents stay thin — they just call get_llm("prs")
"""
from dataclasses import dataclass
from langchain_openai import ChatOpenAI
from config.settings import get_settings

settings = get_settings()


@dataclass
class AgentLLMConfig:
    model: str
    temperature: float
    reasoning: bool = False         # documents intent — is this a reasoning model?
    note: str = ""                  # why this model was chosen for this agent


# ── Per-agent model config ───────────────────────────────────────────
# Change model choices here — nowhere else.

AGENT_LLM_CONFIGS: dict[str, AgentLLMConfig] = {

    "prs": AgentLLMConfig(
        model="gpt-4.1",
        temperature=0.0,
        note="Straightforward retrieval + percentile interpretation. "
             "Standard model sufficient."
    ),

    "pgx": AgentLLMConfig(
        model="gpt-4.1",
        temperature=0.0,
        note="Drug-gene interaction lookup. Deterministic — no reasoning needed."
    ),

    "genomic_variants": AgentLLMConfig(
        model="gpt-4.1",
        temperature=0.0,
        note="Variant pathogenicity interpretation benefits from reasoning — "
             "evidence weighting across ACMG criteria is complex."
    ),

    "family_history": AgentLLMConfig(
        model="gpt-4.1",
        temperature=0.0,
        note="Pedigree threshold evaluation. Switch to o3 for production once available."
    ),

    "phenotype": AgentLLMConfig(
        model="gpt-4.1",
        temperature=0.0,
        note="Diagnosis/EHR retrieval. Structured DB lookups, minimal reasoning."
    ),

    "main": AgentLLMConfig(
        model="gpt-4.1",
        temperature=0.0,
        note="Orchestrator — routes queries to subagents. "
             "gpt-4.1 used for testing"
    ),
    "chat": AgentLLMConfig(
        model="gpt-5.1",
        temperature=0.0,
        note="Chat agent for user interaction. More advanced model for better conversational quality. "
    ),
}


# ── Factory ──────────────────────────────────────────────────────────

def get_llm(agent_name: str) -> ChatOpenAI:
    """
    Returns a configured LLM instance for the named agent.
    
    Usage:
        from config.llm import get_llm
        prs_llm = get_llm("prs")
    """
    if agent_name not in AGENT_LLM_CONFIGS:
        raise ValueError(
            f"No LLM config found for agent '{agent_name}'. "
            f"Available agents: {list(AGENT_LLM_CONFIGS.keys())}"
        )

    cfg = AGENT_LLM_CONFIGS[agent_name]

    return ChatOpenAI(
        model=cfg.model,
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        temperature=cfg.temperature,
    )