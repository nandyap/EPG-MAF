"""
PGX (pharmacogenomics) agent tools.

DB-agnostic: all queries go through a QueryExecutor callable so the tools
work against DuckDB, PostgreSQL, or any other backend without changes.

Default behaviour: lazily connects to DuckDB via config/settings.py db_path.

To override (e.g. in tests or for a different backend):

    import agents.pgx.tools.tools as pgx_tools
    pgx_tools.configure(my_executor)   # inject
    pgx_tools.reset()                  # restore default
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
def explore_patient_pgx(patient_id: str) -> list[dict]:
    """
    Lightweight discovery: return the genes assessed for this patient with
    their diplotype and phenotype. Call this first before looking up
    drug-level annotation detail.

    Args:
        patient_id: The patient to explore.

    Returns:
        List of dicts with keys: patient_id, gene, diplotype, phenotype.
        No drug or recommendation data — use search_pgx_annotations for that.
    """
    return _get_executor()(
        """
        SELECT patient_id, gene, diplotype, phenotype
        FROM patient_pgx_status
        WHERE patient_id = ?
        ORDER BY gene
        """,
        [patient_id],
    )


@tool
def search_pgx_annotations(
    gene: str | None = None,
    phenotype: str | None = None,
    drug: str | None = None,
) -> list[dict]:
    """
    Look up PGX annotation records from the reference table.
    Use this after explore_patient_pgx to find drug recommendations for a
    patient's gene/phenotype combination.

    Match strategy:
      - gene: exact match — pass the value directly from explore_patient_pgx.
      - phenotype: exact match — vocabulary-constrained, from explore_patient_pgx.
      - drug: substring match (case-insensitive) — use for free-text queries.

    Args:
        gene:      Exact gene name. e.g. 'CYP2D6'.
        phenotype: Exact metabolizer phenotype. e.g. 'Normal Metabolizer'.
        drug:      Substring filter on drug name.

    Returns:
        List of dicts with keys: gene, phenotype, drug, recommendation, summary, source.
    """
    conditions: list[str] = []
    params: list[Any] = []
    if gene:
        conditions.append("gene = ?")
        params.append(gene)
    if phenotype:
        conditions.append("phenotype = ?")
        params.append(phenotype)
    if drug:
        conditions.append("drug ILIKE ?")
        params.append(f"%{drug}%")
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    return _get_executor()(
        f"""
        SELECT gene, phenotype, drug, recommendation, summary, source
        FROM pgx_annotations
        {where}
        ORDER BY gene, drug
        """,
        params,
    )


@tool
def get_patient_pgx(
    patient_id: str,
    gene: str | None = None,
) -> list[dict]:
    """
    Retrieve a patient's pharmacogenomics status joined with drug recommendations.
    Returns one row per gene-drug combination based on the patient's diplotype/phenotype.
    If a patient's phenotype has no matching drug annotations, drug/recommendation/
    summary/source will be null (LEFT JOIN — the gene row is still returned).
    Call this after explore_patient_pgx and search_pgx_annotations, passing
    the exact gene from explore_patient_pgx.

    Args:
        patient_id: The patient to retrieve PGX data for.
        gene:       Exact gene name to filter by. e.g. 'CYP2D6'. If None, returns all genes.

    Returns:
        List of dicts with keys: patient_id, gene, diplotype, phenotype,
        drug, recommendation, summary, source.
    """
    execute = _get_executor()
    where = "WHERE pps.patient_id = ?"
    params: list[Any] = [patient_id]
    if gene:
        where += " AND pps.gene = ?"
        params.append(gene)
    sql = f"""
        SELECT
            pps.patient_id,
            pps.gene,
            pps.diplotype,
            pps.phenotype,
            pa.drug,
            pa.recommendation,
            pa.summary,
            pa.source
        FROM patient_pgx_status pps
        LEFT JOIN pgx_annotations pa
            ON pps.gene     = pa.gene
           AND pps.phenotype = pa.phenotype
        {where}
        ORDER BY pps.gene, pa.drug
    """
    return execute(sql, params)
