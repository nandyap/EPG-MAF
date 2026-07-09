"""
Family history agent tools.

DB-agnostic: all queries go through a QueryExecutor callable so the tools
work against DuckDB, PostgreSQL, or any other backend without changes.

Default behaviour: lazily connects to DuckDB via config/settings.py db_path.

To override (e.g. in tests or for a different backend):

    import agents.family_history.tools.tools as fh_tools
    fh_tools.configure(my_executor)   # inject
    fh_tools.reset()                  # restore default
"""
from __future__ import annotations

from typing import Any, Callable, Sequence

from langchain_core.tools import tool

# ── QueryExecutor interface ──────────────────────────────────────────
QueryExecutor = Callable[[str, Sequence[Any]], list[dict]]

_executor: QueryExecutor | None = None


def configure(executor: QueryExecutor) -> None:
    """Inject a custom query executor (replaces the default DuckDB one)."""
    global _executor
    _executor = executor


def reset() -> None:
    """Restore the default DuckDB executor."""
    global _executor
    _executor = None


def _get_executor() -> QueryExecutor:
    """Return the active executor, falling back to a DuckDB closure."""
    if _executor is not None:
        return _executor
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


# ── Tools ────────────────────────────────────────────────────────────

@tool
def explore_patient_family_history(patient_id: str) -> list[dict]:
    """
    Lightweight discovery: return the disease/criteria combinations recorded
    for this patient with their threshold results. Call this first before
    looking up annotation detail.

    Args:
        patient_id: The patient to explore.

    Returns:
        List of dicts with keys: patient_id, disease_name, criteria_name, meets_threshold.
        No annotation data — use search_family_history_annotations for that.
    """
    return _get_executor()(
        """
        SELECT patient_id, disease_name, criteria_name, meets_threshold
        FROM patient_kinship_history
        WHERE patient_id = ?
        ORDER BY disease_name, criteria_name
        """,
        [patient_id],
    )


@tool
def search_family_history_annotations(
    criteria_name: str | None = None,
    disease_name: str | None = None,
) -> list[dict]:
    """
    Look up family history criteria annotation records from the reference table.
    Use this after explore_patient_family_history to understand what a specific
    disease/criteria combination means.

    Match strategy:
      - criteria_name: exact match — pass the value directly from explore_patient_family_history.
      - disease_name: substring match (case-insensitive) — use for free-text queries.

    Args:
        criteria_name: Exact criteria name. e.g. 'Amsterdam II'.
        disease_name:  Substring filter on disease name.

    Returns:
        List of dicts with keys: disease_name, criteria_name, description, source.
    """
    execute = _get_executor()
    conditions: list[str] = []
    params: list[Any] = []
    if criteria_name:
        conditions.append("criteria_name = ?")
        params.append(criteria_name)
    if disease_name:
        conditions.append("disease_name ILIKE ?")
        params.append(f"%{disease_name}%")
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    return execute(
        f"""
        SELECT disease_name, criteria_name, description, source
        FROM kinship_history_annotations
        {where}
        ORDER BY disease_name, criteria_name
        """,
        params,
    )


@tool
def get_patient_family_history(
    patient_id: str,
    disease_name: str | None = None,
    criteria_name: str | None = None,
) -> list[dict]:
    """
    Retrieve a patient's family history records joined with criteria annotations.
    Call this after explore_patient_family_history and search_family_history_annotations,
    passing the exact disease_name and criteria_name from explore results.

    All filters use exact matching. Omit both to return all records for the patient.

    Args:
        patient_id:    The patient to retrieve family history for.
        disease_name:  Exact disease name filter.
        criteria_name: Exact criteria name filter.

    Returns:
        List of dicts with keys: patient_id, disease_name, criteria_name,
        affected_relative_count, total_relatives_searched,
        meets_threshold, search_context_notes,
        last_observed_diagnosis_in_database, criteria_description, criteria_source.
    """
    execute = _get_executor()
    where_clauses = ["pkh.patient_id = ?"]
    params: list[Any] = [patient_id]
    if disease_name:
        where_clauses.append("pkh.disease_name = ?")
        params.append(disease_name)
    if criteria_name:
        where_clauses.append("pkh.criteria_name = ?")
        params.append(criteria_name)
    where = "WHERE " + " AND ".join(where_clauses)
    sql = f"""
        SELECT
            pkh.patient_id,
            pkh.disease_name,
            pkh.criteria_name,
            pkh.affected_relative_count,
            pkh.total_relatives_searched,
            pkh.meets_threshold,
            pkh.search_context_notes,
            CAST(pkh.last_observed_diagnosis_in_database AS VARCHAR) AS last_observed_diagnosis_in_database,
            kha.description  AS criteria_description,
            kha.source       AS criteria_source
        FROM patient_kinship_history pkh
        LEFT JOIN kinship_history_annotations kha
            ON pkh.disease_name  = kha.disease_name
           AND pkh.criteria_name = kha.criteria_name
        {where}
        ORDER BY pkh.disease_name, pkh.criteria_name
    """
    return execute(sql, params)
