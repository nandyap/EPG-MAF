"""Repository base — shared plumbing every domain Repository inherits.

The point of :class:`BaseRepository` is that a domain Repository (in W03)
only writes SQL. Everything else — connection acquisition, RBAC, row
conversion, provenance construction — is inherited.

Contract for W03 subclasses:

1. Take ``pool_factory``, ``authz``, ``provenance`` and ``clock`` (optional)
   in their constructor. Call ``super().__init__(...)`` with them.
2. In every public method, first call ``self._authorize(ctx, patient_id)``.
3. Use ``self._fetch_all(sql, params)`` to run SELECTs; it returns a
   list of dict rows.
4. Use ``self._build_provenance(...)`` to attach construction-time provenance
   to every result row before returning it.

The base class is deliberately small — it does not decide which SQL runs
or what shape the results take. Those decisions live in the domain
Repository, which is where clinical reasoning naturally sits.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any

from egp_maf.errors import DatabaseUnavailable
from egp_maf.infrastructure.db_pool import DbPoolFactory
from egp_maf.services.authz import AuthzPolicy
from egp_maf.services.provenance import ProvenanceService
from egp_maf.state.clinician_context import ClinicianContext
from egp_maf.state.provenance import DBProvenance
from egp_maf.telemetry import db_span, safe_set_attribute


class BaseRepository:
    """Abstract base for every domain Repository.

    Subclasses in W03 add SQL-bearing methods. Everything cross-cutting —
    connection acquisition, RBAC, provenance — lives here.
    """

    def __init__(
        self,
        *,
        pool_factory: DbPoolFactory,
        authz: AuthzPolicy,
        provenance: ProvenanceService,
    ) -> None:
        self._pool_factory = pool_factory
        self._authz = authz
        self._provenance = provenance

    # ── RBAC ────────────────────────────────────────────────────────
    def _authorize(self, ctx: ClinicianContext, patient_id: str) -> None:
        """Raise :class:`AccessDenied` if the clinician is not permitted."""
        self._authz.enforce_read(ctx, patient_id)

    # ── SQL execution ───────────────────────────────────────────────
    async def _fetch_all(
        self,
        sql: str,
        params: Sequence[Any],
    ) -> list[dict[str, Any]]:
        """Run ``sql`` with ``params`` and return rows as dicts.

        Uses the pool's row factory to return ``dict[str, Any]`` — matches
        the prototype's tool return shape (Discovery §5.1). W08 wraps
        the call in a ``db.query`` span; row count is attached on
        success so dashboards can partition read latency by result
        size.
        """
        pool = self._pool_factory.pool
        table = _infer_table(sql)
        with db_span(table=table, operation="SELECT") as _span:
            try:
                async with pool.connection() as conn:
                    async with conn.cursor() as cur:
                        await cur.execute(sql, list(params))
                        columns = (
                            [d.name for d in cur.description]
                            if cur.description
                            else []
                        )
                        rows = await cur.fetchall()
                        dict_rows = [
                            dict(zip(columns, row, strict=True)) for row in rows
                        ]
                        safe_set_attribute(_span, "db.row_count", len(dict_rows))
                        return dict_rows
            except Exception as exc:
                # Wrap any driver error as DatabaseUnavailable so callers can
                # react with a stable HTTP status. Preserve the original exception
                # via ``__cause__``. Span records the exception via db_span.
                raise DatabaseUnavailable(
                    f"Query failed: {exc.__class__.__name__}"
                ) from exc

    # ── Provenance ──────────────────────────────────────────────────
    def _build_provenance(
        self,
        *,
        tool_name: str,
        tool_parameters: dict[str, Any],
        source_table: str,
        source_row: dict[str, Any],
        fields_derived: list[str],
    ) -> DBProvenance:
        """Delegate to the ProvenanceService with construction-time metadata."""
        return self._provenance.build(
            tool_name=tool_name,
            tool_parameters=tool_parameters,
            source_table=source_table,
            source_row=source_row,
            fields_derived=fields_derived,
        )


# ── W08: SQL → table-name heuristic for the ``db.query`` span ────────

_FROM_TABLE_RE = re.compile(r"\bFROM\s+([A-Za-z_][A-Za-z0-9_]*)", re.IGNORECASE)


def _infer_table(sql: str) -> str:
    """Best-effort extraction of the primary table name from a SQL
    ``SELECT`` for use as a low-cardinality span attribute.

    Returns ``"unknown"`` when the heuristic can't find a table (which
    happens for CTE-heavy statements — we don't need parser-perfect
    coverage for a telemetry label).
    """
    match = _FROM_TABLE_RE.search(sql)
    return match.group(1).lower() if match else "unknown"
