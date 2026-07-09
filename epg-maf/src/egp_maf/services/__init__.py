"""Cross-cutting services.

- :class:`PromptService` — fetch/serve system prompts with Foundry fetch +
  local bundle fallback.
- :class:`ThreadStateProvider` — Cosmos-backed session state CRUD with
  ETag-based optimistic concurrency.
"""

from egp_maf.services.prompt_service import PromptService
from egp_maf.services.thread_state import ThreadStateProvider

__all__ = ["PromptService", "ThreadStateProvider"]
