"""Prompt service — Foundry Prompt Catalog fetch with local-bundle fallback.

Behaviour (Design §15):

- Source of truth is the Foundry Prompt Catalog.
- A bundled copy of every prompt ships with the wheel as a fallback.
- On startup, :meth:`PromptService.warm` attempts a Foundry fetch per prompt
  with a short timeout. On failure OR when the source is set to ``bundle``,
  the bundle is used.
- Fallback emits a structured warning event so ops can alert on it.

The Foundry fetch itself is a *stub* in this workstream — the real Foundry
Prompt Catalog client is wired in the E04.3 story. The stub returns
``None`` (equivalent to "not found") so the code path is exercised end-to-end
without requiring Foundry connectivity in tests.
"""

from __future__ import annotations

from typing import Protocol

from egp_maf.config.settings import PromptsSource, Settings
from egp_maf.errors import PromptNotFound
from egp_maf.logging.setup import get_logger
from egp_maf.prompts.bundle import KNOWN_PROMPTS, PROMPT_BUNDLE

_logger = get_logger(__name__)


class FoundryPromptFetcher(Protocol):
    """Protocol for a Foundry Prompt Catalog client.

    A concrete implementation is added in a later workstream. For foundation,
    the default :class:`_NullFoundryFetcher` returns ``None`` for every name.
    """

    async def fetch(self, name: str, timeout_seconds: int) -> str | None:
        """Return prompt text, or ``None`` when unavailable."""


class _NullFoundryFetcher:
    async def fetch(self, name: str, timeout_seconds: int) -> str | None:  # noqa: ARG002
        return None


class PromptService:
    """Serves the seven system prompts by short name.

    Prompts are cached in memory. :meth:`warm` populates the cache at startup
    from Foundry (if enabled) or from the bundle. :meth:`get` returns the
    cached string or raises :class:`PromptNotFound`.
    """

    def __init__(
        self,
        settings: Settings,
        *,
        bundle: dict[str, str] | None = None,
        foundry_fetcher: FoundryPromptFetcher | None = None,
    ) -> None:
        self._settings = settings
        # Copy the bundle so mutations by the caller do not affect other
        # PromptService instances.
        self._bundle: dict[str, str] = dict(bundle if bundle is not None else PROMPT_BUNDLE)
        self._fetcher: FoundryPromptFetcher = foundry_fetcher or _NullFoundryFetcher()
        self._cache: dict[str, str] = dict(self._bundle)
        self._warmed: bool = False
        self._fallback_count: int = 0

    async def warm(self) -> None:
        """Populate the cache from the configured source.

        - ``PROMPTS_SOURCE=bundle`` — cache is already the bundle; no-op.
        - ``PROMPTS_SOURCE=foundry`` — try Foundry for each known prompt.
          On failure, keep the bundled value and log ``prompt.fallback``.
        """
        if self._warmed:
            return

        if self._settings.prompts_source == PromptsSource.BUNDLE:
            self._warmed = True
            return

        timeout = self._settings.prompts_foundry_timeout_seconds

        for name in KNOWN_PROMPTS:
            try:
                fetched = await self._fetcher.fetch(name, timeout_seconds=timeout)
            except Exception as exc:  # noqa: BLE001 — Foundry may raise anything
                _logger.warning(
                    "prompt.fallback",
                    prompt=name,
                    reason="foundry_exception",
                    exception_type=type(exc).__name__,
                )
                self._fallback_count += 1
                continue

            if fetched is None:
                _logger.warning(
                    "prompt.fallback",
                    prompt=name,
                    reason="foundry_returned_none",
                )
                self._fallback_count += 1
                continue

            self._cache[name] = fetched

        self._warmed = True

    def get(self, name: str) -> str:
        """Return the prompt text for ``name``.

        Raises
        ------
        PromptNotFound
            If ``name`` is not one of :data:`~egp_maf.prompts.bundle.KNOWN_PROMPTS`.
        """
        if name not in KNOWN_PROMPTS:
            raise PromptNotFound(
                f"Unknown prompt '{name}'. Known prompts: {sorted(KNOWN_PROMPTS)}"
            )
        # KNOWN_PROMPTS guarantees the key is present in cache (bundle-seeded).
        return self._cache[name]

    def names(self) -> list[str]:
        """Return the sorted list of known prompt names."""
        return sorted(KNOWN_PROMPTS)

    @property
    def fallback_count(self) -> int:
        """Number of prompts that fell back to the bundle in the last :meth:`warm`."""
        return self._fallback_count
