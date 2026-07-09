"""Shared state objects.

- :class:`ClinicianContext` — request-scoped identity, propagated to every
  Repository call for RBAC and audit.
- :class:`SessionDocument` — persisted conversation state, stored in Cosmos.

Specialist output types (``PRSStateOutput``, ``GenomicVariantsStateOutput``,
etc.) are added in the specialist workstream.
"""

from egp_maf.state.clinician_context import ClinicianContext
from egp_maf.state.session_document import (
    CURRENT_SCHEMA_VERSION,
    SessionDocument,
    SessionMessage,
)

__all__ = [
    "CURRENT_SCHEMA_VERSION",
    "ClinicianContext",
    "SessionDocument",
    "SessionMessage",
]
