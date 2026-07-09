"""
PRS agent tools.

DB-agnostic: all queries go through a QueryExecutor callable so the tools
work against DuckDB, PostgreSQL, or any other backend without changes.

Default behaviour: lazily connects to DuckDB via config/settings.py db_path.

To override (e.g. in tests or for a different backend)::

    import agents.prs.tools.tools as prs_tools
    prs_tools.configure(my_executor)   # inject
    prs_tools.reset()                  # restore default
"""
from __future__ import annotations

from typing import Any, Callable, Sequence

from langchain_core.tools import tool

# ── QueryExecutor interface ─────────────────────────────────────────
# (sql: str, params: Sequence[Any]) -> list[row_dict]
# SQL uses ? positional placeholders (ANSI SQL / DuckDB / SQLite compatible).
QueryExecutor = Callable[[str, Sequence[Any]], list[dict]]

_executor: QueryExecutor | None = None


def configure(executor: QueryExecutor) -> None:
    """Inject a custom query executor (replaces the default DuckDB one)."""
    global _executor
    _executor = executor


def reset() -> None:
    """Restore the default DuckDB executor. Call this in test teardown."""
    global _executor
    _executor = None


def _get_executor() -> QueryExecutor:
    """Return the active executor, falling back to a DuckDB closure."""
    if _executor is not None:
        return _executor
    # Lazy import — duckdb is only required when no executor is configured.
    import duckdb  # noqa: PLC0415
    from config.settings import get_settings
    db_path = get_settings().db_path

    def _duckdb_execute(sql: str, params: Sequence[Any]) -> list[dict]:
        con = duckdb.connect(db_path, read_only=True)
        try:
            cur = con.execute(sql, list(params))
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]
        finally:
            con.close()

    return _duckdb_execute


# ── Tools ────────────────────────────────────────────────

@tool
def explore_patient_prs(patient_id: str) -> list[dict]:
    """
    Lightweight discovery: return the PRS scores recorded for this patient
    with minimal fields. Call this first to see which prs_names and diseases
    exist for the patient before looking up annotation detail.

    Args:
        patient_id: The patient to explore.

    Returns:
        List of dicts with keys: patient_id, prs_name, disease_name, risk_band.
        No annotation data — use search_prs_annotations for that.
    """
    return _get_executor()(
        """
        SELECT patient_id, prs_name, disease_name, risk_band
        FROM patient_prs
        WHERE patient_id = ?
        ORDER BY disease_name
        """,
        [patient_id],
    )


@tool
def search_prs_annotations(
    prs_name: str | None = None,
    disease_name: str | None = None,
) -> list[dict]:
    """
    Look up PRS annotation records from the reference table.
    Use this after explore_patient_prs to understand what a specific score means.

    Match strategy:
      - prs_name: exact match — pass the value directly from explore_patient_prs.
      - disease_name: substring match (case-insensitive) — use for free-text queries.

    Args:
        prs_name:     Exact PRS identifier. e.g. 'PRS_AD_001'.
        disease_name: Substring filter on disease name.

    Returns:
        List of dicts with keys: prs_name, disease_name, source, notes.
    """
    conditions: list[str] = []
    params: list[Any] = []
    if prs_name:
        conditions.append("prs_name = ?")
        params.append(prs_name)
    if disease_name:
        conditions.append("disease_name ILIKE ?")
        params.append(f"%{disease_name}%")
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    return _get_executor()(
        f"""
        SELECT prs_name, disease_name, source, notes
        FROM prs_annotations
        {where}
        ORDER BY disease_name
        """,
        params,
    )


@tool
def get_patient_prs(
    patient_id: str,
    prs_name: str | None = None,
    disease_name: str | None = None,
) -> list[dict]:
    """
    Retrieve PRS scores for a patient, joined with prs_annotations metadata.
    Call this after explore_patient_prs and search_prs_annotations, passing
    the exact identifiers you have chosen as filters.

    All filters use exact matching — pass values directly from explore_patient_prs.
    Omit all filters to return all PRS scores for the patient.

    Args:
        patient_id:   The patient to retrieve scores for.
        prs_name:     Exact PRS name filter. e.g. 'PRS_AD_001'.
        disease_name: Exact disease name filter.

    Returns:
        List of dicts with keys: patient_id, prs_name, disease_name,
        prs_score, percentile, risk_band, source, metadata_notes.
    """
    executor = _get_executor()
    conditions = ["pp.patient_id = ?"]
    params: list[Any] = [patient_id]
    if prs_name:
        conditions.append("pp.prs_name = ?")
        params.append(prs_name)
    if disease_name:
        conditions.append("pp.disease_name = ?")
        params.append(disease_name)
    where = " AND ".join(conditions)
    return executor(
        f"""
        SELECT pp.patient_id, pp.prs_name, pp.disease_name, pp.prs_score,
               pp.percentile, pp.risk_band,
               pa.source, pa.notes AS metadata_notes
        FROM patient_prs pp
        LEFT JOIN prs_annotations pa ON pp.prs_name = pa.prs_name
        WHERE {where}
        """,
        params,
    )