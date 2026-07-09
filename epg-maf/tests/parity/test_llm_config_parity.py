"""LLM-config parity — the ``AGENT_LLM_CONFIGS`` dict must match the prototype
byte-for-byte on ``model`` and ``temperature`` for every agent.

Skips silently if the prototype is not present alongside this checkout.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from egp_maf.config.llm_config import AGENT_LLM_CONFIGS

_HERE = Path(__file__).resolve()
_WORKSPACE = _HERE.parents[3]
_PROTOTYPE_CONFIG = _WORKSPACE / "config"


def _requires_prototype() -> pytest.MarkDecorator:
    if not (_PROTOTYPE_CONFIG / "llm.py").exists():
        return pytest.mark.skip(reason="Prototype config/llm.py not found")
    return pytest.mark.parity


@_requires_prototype()
class TestLlmConfigParity:
    def test_prototype_agent_names_match(self) -> None:
        prototype_configs = _load_prototype_configs()
        assert set(prototype_configs.keys()) == set(AGENT_LLM_CONFIGS.keys())

    def test_prototype_models_match(self) -> None:
        prototype_configs = _load_prototype_configs()
        for name, expected in prototype_configs.items():
            actual = AGENT_LLM_CONFIGS[name]
            assert actual.model == expected["model"], (
                f"model mismatch for {name}: {actual.model!r} vs {expected['model']!r}"
            )

    def test_prototype_temperatures_match(self) -> None:
        prototype_configs = _load_prototype_configs()
        for name, expected in prototype_configs.items():
            actual = AGENT_LLM_CONFIGS[name]
            assert actual.temperature == expected["temperature"], (
                f"temperature mismatch for {name}: "
                f"{actual.temperature!r} vs {expected['temperature']!r}"
            )


def _load_prototype_configs() -> dict[str, dict[str, object]]:
    """Parse the prototype ``config/llm.py`` without importing it.

    We do not ``import config.llm`` because that would load
    ``langchain_openai`` and require the prototype's dependencies. Instead
    we execute the module source in a stub-injected namespace.
    """
    source_path = _PROTOTYPE_CONFIG / "llm.py"
    source = source_path.read_text(encoding="utf-8")

    # Stub the modules that the prototype imports at top level.
    class _StubChatOpenAI:  # noqa: D401
        """Stub."""

        def __init__(self, **kwargs: object) -> None:
            self.kwargs = kwargs

    class _StubSettings:
        llm_api_key = "stub"
        llm_base_url = "https://stub"

    stub_langchain = type(sys)("langchain_openai")
    stub_langchain.ChatOpenAI = _StubChatOpenAI  # type: ignore[attr-defined]

    stub_config = type(sys)("config")
    stub_config_settings = type(sys)("config.settings")
    stub_config_settings.get_settings = lambda: _StubSettings()  # type: ignore[attr-defined]
    stub_config.settings = stub_config_settings  # type: ignore[attr-defined]

    saved = {
        "langchain_openai": sys.modules.get("langchain_openai"),
        "config": sys.modules.get("config"),
        "config.settings": sys.modules.get("config.settings"),
    }
    sys.modules["langchain_openai"] = stub_langchain
    sys.modules["config"] = stub_config
    sys.modules["config.settings"] = stub_config_settings
    try:
        namespace: dict[str, object] = {"__name__": "prototype_llm"}
        exec(compile(source, str(source_path), "exec"), namespace)
    finally:
        for name, mod in saved.items():
            if mod is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = mod

    prototype_configs = namespace["AGENT_LLM_CONFIGS"]
    return {
        name: {"model": cfg.model, "temperature": cfg.temperature}
        for name, cfg in prototype_configs.items()  # type: ignore[union-attr]
    }
