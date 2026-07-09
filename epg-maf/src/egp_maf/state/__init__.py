"""Shared state objects.

- :class:`ClinicianContext` — request-scoped identity, propagated to every
  Repository call for RBAC and audit.
- :class:`DBProvenance` — audit-trail record linking a clinical fact to its
  DB source row.
- :class:`SessionDocument` — persisted conversation state, stored in Cosmos.

Specialist output types (``PRSStateOutput``, ``GenomicVariantsStateOutput``,
etc.) are added in the specialist workstream.
"""

from egp_maf.state.clinician_context import ClinicianContext
from egp_maf.state.provenance import DBProvenance, find_provenance_for_field
from egp_maf.state.session_document import (
    CURRENT_SCHEMA_VERSION,
    SessionDocument,
    SessionMessage,
)

__all__ = [
    "CURRENT_SCHEMA_VERSION",
    "ClinicianContext",
    "DBProvenance",
    "SessionDocument",
    "SessionMessage",
    "find_provenance_for_field",
]
