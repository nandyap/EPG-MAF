"""MAF ``OpenAIChatClient`` factory per agent.

Replaces the prototype's ``config/llm.py :: get_llm(agent_name)`` which
returned a ``langchain_openai.ChatOpenAI``.

For Compass via APIM (Design ADR-003), we point ``base_url`` at the APIM
endpoint and pass the APIM subscription key as ``api_key``. Compass is
OpenAI-compatible so ``OpenAIChatClient`` is the correct MAF client type.

Configuration parity with the prototype:
- ``model_id`` = ``AGENT_LLM_CONFIGS[<agent>].model``
- ``temperature`` = ``0.0`` for every agent (deterministic replay).
- ``base_url`` = ``Settings.llm_base_url`` (APIM in prod, mock in dev).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from egp_maf.config.llm_config import AGENT_LLM_CONFIGS, AgentLlmConfig
from egp_maf.config.settings import Settings
from egp_maf.errors import ConfigurationError

if TYPE_CHECKING:  # pragma: no cover
    from agent_framework.openai import OpenAIChatClient

_logger = logging.getLogger(__name__)


class LlmClientFactory:
    """Caches one MAF ``OpenAIChatClient`` per agent name.

    Not tied to any specific specialist. Consumers pass an agent short
    name (``prs``, ``chat``, …); the factory looks up the model from
    ``AGENT_LLM_CONFIGS`` and returns a client wired to APIM.
    """

    def __init__(
        self,
        settings: Settings,
        configs: dict[str, AgentLlmConfig] | None = None,
        *,
        client_constructor: Any = None,
    ) -> None:
        """Store configuration.

        Parameters
        ----------
        settings:
            Application settings.
        configs:
            Per-agent LLM configs. Defaults to the module-level
            ``AGENT_LLM_CONFIGS``.
        client_constructor:
            Callable used to build a client. Injected in unit tests so we do
            not require ``agent-framework`` to be installed to exercise the
            factory's caching and validation logic.
        """
        self._settings = settings
        self._configs = configs if configs is not None else AGENT_LLM_CONFIGS
        self._client_constructor = client_constructor
        self._clients: dict[str, "OpenAIChatClient"] = {}

    def get(self, agent_name: str) -> "OpenAIChatClient":
        """Return a cached client for ``agent_name``.

        Raises
        ------
        ConfigurationError
            If ``agent_name`` is not in ``AGENT_LLM_CONFIGS``.
        """
        if agent_name in self._clients:
            return self._clients[agent_name]

        if agent_name not in self._configs:
            raise ConfigurationError(
                f"Unknown agent name '{agent_name}'. "
                f"Known agents: {sorted(self._configs.keys())}"
            )

        cfg = self._configs[agent_name]
        constructor = self._client_constructor or self._default_constructor

        client = constructor(
            api_key=self._settings.llm_api_key.get_secret_value(),
            base_url=self._settings.llm_base_url,
            model_id=cfg.model,
        )
        self._clients[agent_name] = client
        return client

    def config_for(self, agent_name: str) -> AgentLlmConfig:
        """Return the ``AgentLlmConfig`` used to construct the client for
        ``agent_name``. Useful for callers that need the model temperature
        or notes without holding a client reference.
        """
        if agent_name not in self._configs:
            raise ConfigurationError(f"Unknown agent name '{agent_name}'")
        return self._configs[agent_name]

    def clear(self) -> None:
        """Drop all cached clients. Intended for tests only."""
        self._clients.clear()

    # ── Internals ────────────────────────────────────────────────────
    @staticmethod
    def _default_constructor(
        *, api_key: str, base_url: str, model_id: str
    ) -> "OpenAIChatClient":
        """Default constructor — real MAF ``OpenAIChatClient``.

        Note ``model_id`` is the shim's kwarg name for consistency with
        the prototype's ``config/llm.py``; MAF 1.10.0's
        ``OpenAIChatClient`` takes ``model`` as the positional/keyword
        argument, so we adapt here.
        """
        from agent_framework.openai import OpenAIChatClient  # type: ignore[import-untyped]

        return OpenAIChatClient(
            model=model_id,
            api_key=api_key,
            base_url=base_url,
        )
