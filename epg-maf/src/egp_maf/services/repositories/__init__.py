"""Repository infrastructure — base class + 5 domain repositories.

Domain repositories each map to one specialist's tool set from the
LangGraph prototype. Every one inherits :class:`BaseRepository` and adds
domain-specific SQL methods; all cross-cutting concerns (pool acquisition,
RBAC, provenance construction) live in the base.

Design references:

- Design ADR-005 (Repositories over an executor callable).
- Design ADR-017 (RBAC at Repository entry).
- Design §11.7 (Provenance at construction time).
"""

from egp_maf.services.repositories.base import BaseRepository
from egp_maf.services.repositories.family_history import FamilyHistoryRepository
from egp_maf.services.repositories.genomic_variants import GenomicVariantsRepository
from egp_maf.services.repositories.pgx import PGXRepository
from egp_maf.services.repositories.phenotype import PhenotypeRepository
from egp_maf.services.repositories.prs import PRSRepository

__all__ = [
    "BaseRepository",
    "FamilyHistoryRepository",
    "GenomicVariantsRepository",
    "PGXRepository",
    "PRSRepository",
    "PhenotypeRepository",
]
