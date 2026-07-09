"""
Genomic variants agent tools.

All tools are DB-agnostic: by default they open a DuckDB connection using
the path from settings, but callers (e.g. tests) can inject any executor
that satisfies the QueryExecutor protocol via configure().
"""
from __future__ import annotations
from typing import Any, Callable, Optional, Sequence
from langchain_core.tools import tool

QueryExecutor = Callable[[str, Sequence[Any]], list[dict]]
_executor: QueryExecutor | None = None


def configure(executor: QueryExecutor) -> None:
    """Inject a custom executor (e.g. a test-scoped DuckDB connection)."""
    global _executor
    _executor = executor


def reset() -> None:
    """Remove any injected executor; reverts to lazy DuckDB default."""
    global _executor
    _executor = None


def _get_executor() -> QueryExecutor:
    if _executor is not None:
        return _executor
    import duckdb
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


@tool
def get_patient_genomic_variants(
    patient_id: str,
    variant_id: Optional[str] = None,
    disease_name: Optional[str] = None,
    gene: Optional[str] = None,
    variant_type: Optional[str] = None,
    pathogenicity: Optional[str] = None,
) -> list[dict]:
    """
    Retrieve genomic variants for a patient, joined with full annotation data.
    Call this after explore_patient_genomic_variants and search_variant_annotations,
    passing the exact identifiers you have chosen as filters.

    All filters use exact matching — pass values directly from explore results.
    Omit all filters to retrieve all variants for the patient.

    Args:
        patient_id:    Patient identifier.
        variant_id:    Exact variant identifier from explore_patient_genomic_variants.
        disease_name:  Exact disease name filter.
        gene:          Exact gene name filter. e.g. 'BRCA1'.
        variant_type:  Exact variant type filter. e.g. 'missense'.
        pathogenicity: Exact pathogenicity class filter. e.g. 'Pathogenic'.

    Returns:
        List of rows with fields: variant_id, genotype, sequencing_platform,
        variant_caller, call_quality (from patient_variants); gene, variant_type,
        pathogenicity, pathogenicity_source, disease_name, inheritance,
        annotations_json, notes (from variant_annotations).
        Note: hgvs_c, hgvs_p, gnomad_af, and common_name are inside annotations_json.
    """
    executor = _get_executor()

    conditions = ["pv.patient_id = ?"]
    params: list[Any] = [patient_id]

    if variant_id:
        conditions.append("pv.variant_id = ?")
        params.append(variant_id)
    if disease_name:
        conditions.append("va.disease_name = ?")
        params.append(disease_name)
    if gene:
        conditions.append("va.gene = ?")
        params.append(gene)
    if variant_type:
        conditions.append("va.variant_type = ?")
        params.append(variant_type)
    if pathogenicity:
        conditions.append("va.pathogenicity = ?")
        params.append(pathogenicity)

    where_clause = " AND ".join(conditions)

    sql = f"""
        SELECT
            pv.variant_id,
            pv.genotype,
            pv.sequencing_platform,
            pv.variant_caller,
            pv.call_quality,
            va.gene,
            va.variant_type,
            va.pathogenicity,
            va.pathogenicity_source,
            va.disease_name,
            va.inheritance,
            va.annotations_json,
            va.notes
        FROM patient_variants pv
        LEFT JOIN variant_annotations va ON pv.variant_id = va.variant_id
        WHERE {where_clause}
    """
    return executor(sql, params)


@tool
def explore_patient_genomic_variants(patient_id: str) -> list[dict]:
    """
    Lightweight discovery: return the variant IDs and genotypes recorded for
    this patient. Call this first to see which variants exist before looking
    up annotation detail.

    Args:
        patient_id: The patient to explore.

    Returns:
        List of dicts with keys: patient_id, variant_id, genotype.
        No annotation data — use search_variant_annotations for that.
    """
    return _get_executor()(
        """
        SELECT patient_id, variant_id, genotype
        FROM patient_variants
        WHERE patient_id = ?
        ORDER BY variant_id
        """,
        [patient_id],
    )


@tool
def search_variant_annotations(
    variant_id: Optional[str] = None,
    gene: Optional[str] = None,
    pathogenicity: Optional[str] = None,
    disease_name: Optional[str] = None,
) -> list[dict]:
    """
    Look up variant annotation records from the reference table.
    Use this after explore_patient_genomic_variants to understand what a
    specific variant means before pulling the full patient result.

    Match strategy:
      - variant_id: exact match — pass the value directly from explore_patient_genomic_variants.
      - gene, pathogenicity, disease_name: substring match (case-insensitive) —
        use for catalog browsing before a specific variant_id is known.

    Args:
        variant_id:    Exact variant identifier.
        gene:          Substring filter on gene name.
        pathogenicity: Substring filter on pathogenicity class.
        disease_name:  Substring filter on disease name.

    Returns:
        List of dicts with keys: variant_id, gene, variant_type, pathogenicity,
        pathogenicity_source, disease_name, inheritance, notes, annotations_json.
    """
    conditions: list[str] = []
    params: list[Any] = []
    if variant_id:
        conditions.append("variant_id = ?")
        params.append(variant_id)
    if gene:
        conditions.append("gene ILIKE ?")
        params.append(f"%{gene}%")
    if pathogenicity:
        conditions.append("pathogenicity ILIKE ?")
        params.append(f"%{pathogenicity}%")
    if disease_name:
        conditions.append("disease_name ILIKE ?")
        params.append(f"%{disease_name}%")
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    return _get_executor()(
        f"""
        SELECT variant_id, gene, variant_type, pathogenicity,
               pathogenicity_source, disease_name, inheritance,
               notes, annotations_json
        FROM variant_annotations
        {where}
        ORDER BY gene, pathogenicity
        """,
        params,
    )
