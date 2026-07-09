"""Unit tests for :class:`egp_maf.services.prompt_service.PromptService`."""

from __future__ import annotations

import pytest

from egp_maf.config.settings import PromptsSource, Settings
from egp_maf.errors import PromptNotFound
from egp_maf.prompts.bundle import KNOWN_PROMPTS, PROMPT_BUNDLE
from egp_maf.services.prompt_service import FoundryPromptFetcher, PromptService


class _RecordingFetcher:
    """Test fetcher that records calls and returns configured values."""

    def __init__(self, responses: dict[str, str | None] | None = None) -> None:
        self.responses = responses or {}
        self.calls: list[tuple[str, int]] = []

    async def fetch(self, name: str, timeout_seconds: int) -> str | None:
        self.calls.append((name, timeout_seconds))
        return self.responses.get(name)


class _RaisingFetcher:
    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    async def fetch(self, name: str, timeout_seconds: int) -> str | None:
        raise self._exc


class TestPromptServiceBundleMode:
    async def test_warm_is_no_op_in_bundle_mode(self, settings: Settings) -> None:
        fetcher = _RecordingFetcher(responses={})
        svc = PromptService(settings, foundry_fetcher=fetcher)
        await svc.warm()
        assert fetcher.calls == []
        assert svc.fallback_count == 0

    async def test_get_returns_bundled_text(self, settings: Settings) -> None:
        svc = PromptService(settings)
        await svc.warm()
        for name in KNOWN_PROMPTS:
            assert svc.get(name) == PROMPT_BUNDLE[name]

    def test_get_unknown_prompt_raises(self, settings: Settings) -> None:
        svc = PromptService(settings)
        with pytest.raises(PromptNotFound):
            svc.get("nonexistent_prompt")


class TestPromptServiceFoundryMode:
    async def test_warm_fetches_all_known_prompts(
        self, monkeypatch: pytest.MonkeyPatch, minimal_env: None
    ) -> None:
        monkeypatch.setenv("PROMPTS_SOURCE", "foundry")
        s = Settings()  # type: ignore[call-arg]
        fetcher = _RecordingFetcher(
            responses={name: f"fetched:{name}" for name in KNOWN_PROMPTS}
        )
        svc = PromptService(s, foundry_fetcher=fetcher)

        await svc.warm()

        assert len(fetcher.calls) == len(KNOWN_PROMPTS)
        for name in KNOWN_PROMPTS:
            assert svc.get(name) == f"fetched:{name}"

    async def test_none_response_falls_back_to_bundle(
        self, monkeypatch: pytest.MonkeyPatch, minimal_env: None
    ) -> None:
        monkeypatch.setenv("PROMPTS_SOURCE", "foundry")
        s = Settings()  # type: ignore[call-arg]
        # Return None for prs_agent only; everything else fetches successfully.
        fetcher = _RecordingFetcher(
            responses={
                name: (None if name == "prs_agent" else f"fetched:{name}")
                for name in KNOWN_PROMPTS
            }
        )
        svc = PromptService(s, foundry_fetcher=fetcher)
        await svc.warm()

        assert svc.get("prs_agent") == PROMPT_BUNDLE["prs_agent"]
        assert svc.get("chat_router") == "fetched:chat_router"
        assert svc.fallback_count == 1

    async def test_exception_falls_back_to_bundle(
        self, monkeypatch: pytest.MonkeyPatch, minimal_env: None
    ) -> None:
        monkeypatch.setenv("PROMPTS_SOURCE", "foundry")
        s = Settings()  # type: ignore[call-arg]
        fetcher = _RaisingFetcher(RuntimeError("foundry down"))
        svc = PromptService(s, foundry_fetcher=fetcher)

        await svc.warm()

        # All fall back — cache is unchanged from the initial bundle.
        for name in KNOWN_PROMPTS:
            assert svc.get(name) == PROMPT_BUNDLE[name]
        assert svc.fallback_count == len(KNOWN_PROMPTS)

    async def test_warm_is_idempotent(self, settings: Settings) -> None:
        fetcher = _RecordingFetcher(responses={})
        svc = PromptService(settings, foundry_fetcher=fetcher)
        await svc.warm()
        await svc.warm()
        # Bundle-mode: no fetches at all, even on the second call.
        assert fetcher.calls == []

    def test_names_returns_sorted(self, settings: Settings) -> None:
        svc = PromptService(settings)
        assert svc.names() == sorted(KNOWN_PROMPTS)
