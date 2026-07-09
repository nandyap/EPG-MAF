"""Repository infrastructure — base class.

The 5 domain repositories arrive in W03. This module supplies the shared
machinery every one of them inherits: :class:`BaseRepository` owns the
pool + authz + provenance wiring, and exposes ``_authorize`` and
``_fetch_all`` helpers.

Design references:

- Design ADR-005 (Repositories over an executor callable).
- Design ADR-017 (RBAC at Repository entry).
- Design §11.7 (Provenance at construction time).
"""

from egp_maf.services.repositories.base import BaseRepository

__all__ = ["BaseRepository"]
