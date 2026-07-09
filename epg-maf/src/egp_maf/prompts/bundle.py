"""Prompt bundle — the 7 system prompts + 1 synthesis prompt (chat has 2).

Loaded from the ``data/`` directory at import time. Byte-parity with the
LangGraph prototype is verified by ``tests/parity/test_prompt_parity.py``.

The single documented deviation from the prototype is the removal of the
duplicated rule 6 in ``main_agent`` — see Design §15.5.
"""

from __future__ import annotations

from importlib.resources import files

from egp_maf.errors import PromptNotFound

# Prompt short names — must stay in sync with the router prompts and with
# egp_maf.config.llm_config.AGENT_LLM_CONFIGS.
KNOWN_PROMPTS: frozenset[str] = frozenset(
    {
        "chat_router",
        "chat_synthesis",
        "main_agent",
        "prs_agent",
        "genomic_variants_agent",
        "family_history_agent",
        "pgx_agent",
        "phenotype_agent",
    }
)

_DATA_PKG = "egp_maf.prompts.data"


def load_bundle() -> dict[str, str]:
    """Load every bundled prompt as a ``{name: text}`` mapping.

    The mapping is a fresh dict on every call so callers can safely mutate.
    """
    bundle: dict[str, str] = {}
    resource_root = files(_DATA_PKG)
    for name in KNOWN_PROMPTS:
        resource = resource_root.joinpath(f"{name}.txt")
        if not resource.is_file():
            raise PromptNotFound(
                f"Bundled prompt '{name}.txt' missing from {_DATA_PKG}"
            )
        bundle[name] = resource.read_text(encoding="utf-8")
    return bundle


# ── Module-level snapshot ─────────────────────────────────────────────
# Cheap: 8 files, small strings. Loaded once at import time so callers can
# obtain a prompt without going through :class:`PromptService` — useful for
# tests and for future compile-time schema derivation (Foundry).
PROMPT_BUNDLE: dict[str, str] = load_bundle()
