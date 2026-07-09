"""
Phenotype agent tools.

DB-agnostic: all queries go through a QueryExecutor callable so the tools
work against DuckDB, PostgreSQL, or any other backend without changes.

Default behaviour: lazily connects to DuckDB via config/settings.py db_path.

To override (e.g. in tests or for a different backend):

    import agents.phenotype.tools.tools as phenotype_tools
    phenotype_tools.configure(my_executor)   # inject
    phenotype_tools.reset()                  # restore default
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
def explore_patient_phenotype(patient_id: str) -> list[dict]:
    """
    Lightweight discovery: return the distinct set of disease names and terms
    recorded for this patient. Call this first to identify which conditions
    exist before fetching full encounter detail.

    Returns a compact list — one row per unique (disease_name, term, code_type)
    combination. No dates or descriptions — use get_patient_diagnoses for those.

    Args:
        patient_id: The patient to explore.

    Returns:
        List of dicts with keys: disease_name, term, code_type.
        disease_name may be null for diagnoses without a normalised mapping.
    """
    execute = _get_executor()
    return execute(
        """
        SELECT DISTINCT
            disease_name,
            term,
            code_type
        FROM diagnoses
        WHERE patient_id = ?
        ORDER BY disease_name NULLS LAST, term
        """,
        [patient_id],
    )


@tool
def get_patient_diagnoses(
    patient_id: str,
    disease_name: str | None = None,
    search_term: str | None = None,
) -> list[dict]:
    """
    Retrieve a patient's diagnoses grouped by disease/condition, with
    encounter statistics pre-aggregated in SQL.

    Returns one row per disease_name group (COALESCE(disease_name, term)).
    Each row includes encounter count, first/last encounter dates, and
    lists of distinct codes, terms, and code types.

    Optionally filter by:
      - disease_name: ILIKE match on the disease_name column
      - search_term:  ILIKE match across disease_name, term, and description
    Both filters are applied as OR if both are provided.
    Omit both to retrieve the full grouped diagnosis history.

    Args:
        patient_id:   The patient to retrieve diagnoses for.
        disease_name: Optional disease name substring filter.
        search_term:  Optional fuzzy term to match across name/term/description.

    Returns:
        List of dicts with keys: disease_name, encounter_count,
        first_encounter_date, last_encounter_date, codes, terms, code_types.
    """
    execute = _get_executor()
    conditions: list[str] = ["patient_id = ?"]
    params: list[Any] = [patient_id]

    if disease_name and search_term:
        conditions.append(
            "(disease_name = ? OR term ILIKE ? OR description ILIKE ?)"
        )
        params += [disease_name, f"%{search_term}%", f"%{search_term}%"]
    elif disease_name:
        conditions.append("disease_name = ?")
        params.append(disease_name)
    elif search_term:
        conditions.append(
            "(disease_name ILIKE ? OR term ILIKE ? OR description ILIKE ?)"
        )
        params += [f"%{search_term}%", f"%{search_term}%", f"%{search_term}%"]

    where = " AND ".join(conditions)
    sql = f"""
        SELECT
            COALESCE(disease_name, term)              AS disease_name,
            COUNT(*)                                   AS encounter_count,
            CAST(MIN(encounter_date) AS VARCHAR)       AS first_encounter_date,
            CAST(MAX(encounter_date) AS VARCHAR)       AS last_encounter_date,
            LIST(DISTINCT code)                        AS codes,
            LIST(DISTINCT term)                        AS terms,
            LIST(DISTINCT code_type)                   AS code_types
        FROM diagnoses
        WHERE {where}
        GROUP BY COALESCE(disease_name, term)
        ORDER BY COALESCE(disease_name, term) NULLS LAST
    """
    return execute(sql, params)
