"""Cross-cutting services.

- :class:`PromptService` — fetch/serve system prompts with Foundry fetch +
  local bundle fallback.
- :class:`ThreadStateProvider` — Cosmos-backed session state CRUD with
  ETag-based optimistic concurrency.
- :class:`ProvenanceService` — construction-time :class:`DBProvenance` builder.
- :class:`AuthzPolicy` (protocol) plus :class:`AllowlistAuthzPolicy` — RBAC
  at Repository entry.
- :class:`BaseRepository` and the 5 domain repositories (W03) — shared
  plumbing + SQL for each specialist domain.
"""

from egp_maf.services.authz import AllowlistAuthzPolicy, AuthzPolicy
from egp_maf.services.prompt_service import PromptService
from egp_maf.services.provenance import ProvenanceService
from egp_maf.services.repositories import (
    BaseRepository,
    FamilyHistoryRepository,
    GenomicVariantsRepository,
    PGXRepository,
    PhenotypeRepository,
    PRSRepository,
)
from egp_maf.services.thread_state import ThreadStateProvider

__all__ = [
    "AllowlistAuthzPolicy",
    "AuthzPolicy",
    "BaseRepository",
    "FamilyHistoryRepository",
    "GenomicVariantsRepository",
    "PGXRepository",
    "PhenotypeRepository",
    "PRSRepository",
    "PromptService",
    "ProvenanceService",
    "ThreadStateProvider",
]
