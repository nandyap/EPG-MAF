"""Configuration layer — pydantic-settings + AGENT_LLM_CONFIGS.

Ports and extends ``config/settings.py`` and ``config/llm.py`` from the
LangGraph prototype. The extension covers Postgres, Cosmos, APIM/Compass,
orchestration flags and environment metadata.
"""

from egp_maf.config.llm_config import (
    AGENT_LLM_CONFIGS,
    AgentLlmConfig,
    KNOWN_AGENT_NAMES,
)
from egp_maf.config.settings import DispatchMode, PromptsSource, Settings, get_settings

__all__ = [
    "AGENT_LLM_CONFIGS",
    "AgentLlmConfig",
    "DispatchMode",
    "KNOWN_AGENT_NAMES",
    "PromptsSource",
    "Settings",
    "get_settings",
]
