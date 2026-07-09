"""
Integration test for the main orchestration agent.

Verifies that an Alzheimer's query correctly routes through both the
prs_agent and genomic_variants_agent subagents and terminates cleanly.

Run from project root:
    python3 agents/main/tests/test_main_agent.py
    python3 -m agents.main.tests.test_main_agent
"""
from __future__ import annotations

# ── sys.path fix ──────────────────────────────────────────────────
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]  # .../EGP-Window/EGP-Window
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
# ──────────────────────────────────────────────────────────────────

import duckdb
import json

import agents.prs.tools.tools as prs_tools
import agents.genomic_variants.tools.tools as gv_tools
import agents.family_history.tools.tools as fh_tools
import agents.pgx.tools.tools as pgx_tools
import agents.phenotype.tools.tools as phenotype_tools
from agents.prs.tools.tools import QueryExecutor
from agents.main.graph.graph import graph
from config.settings import get_settings


def make_duckdb_executor(db_path: str) -> QueryExecutor:
    """DuckDB-backed QueryExecutor for both tool modules."""
    def execute(sql: str, params) -> list[dict]:
        con = duckdb.connect(db_path, read_only=True)
        try:
            cur = con.execute(sql, list(params))
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]
        finally:
            con.close()
    return execute


def get_test_patient_id(executor: QueryExecutor) -> str:
    """
    Pick a patient that has data in both patient_prs and patient_variants.
    Falls back to patient_prs only if no intersection exists in the DB.
    """
    rows = executor(
        """
        SELECT pv.patient_id
        FROM patient_variants pv
        JOIN patient_prs pp ON pv.patient_id = pp.patient_id
        LIMIT 1
        """,
        [],
    )
    if rows:
        return str(rows[0]["patient_id"])

    # Fallback: any patient with PRS data
    rows = executor("SELECT patient_id FROM patient_prs LIMIT 1", [])
    if not rows:
        raise RuntimeError("No rows in patient_prs — is the DB seeded?")
    return str(rows[0]["patient_id"])


def test_main_orchestrator() -> None:
    """
    End-to-end test: Alzheimer's query routes to prs_agent then
    genomic_variants_agent and terminates with next='end'.
    """
    settings = get_settings()
    executor = make_duckdb_executor(settings.db_path)

    # Wire all four tool modules to the same DB executor
    prs_tools.configure(executor)
    gv_tools.configure(executor)
    fh_tools.configure(executor)
    pgx_tools.configure(executor)
    phenotype_tools.configure(executor)

    patient_id = get_test_patient_id(executor)
    print(f"\n--- Running main orchestrator for patient_id={patient_id!r} ---\n")

    initial_state = {
        "patient_id": patient_id,
        "original_query": (
            "What is this patient's Alzheimer's disease risk "
            "based on their polygenic risk scores, genomic variants, "
            "and family history? Also summarise any relevant drug-gene "
            "interactions from their pharmacogenomics profile, "
            "and list any relevant past diagnoses."
        ),
        "agents_completed": [],
    }

    result = graph.invoke(initial_state)

    # ── Print summary ─────────────────────────────────────────────
    print(f"Final routing decision : {result.get('next')!r}")
    print(f"Agents completed       : {result.get('agents_completed')}")

    prs_out = result.get("prs")
    gv_out = result.get("genomic_variants")

    if prs_out:
        print(f"\nPRS status  : {prs_out.status}")
        if prs_out.output:
            print(f"PRS summary : {prs_out.output.summary}")
            print(f"PRS results : {len(prs_out.output.results)} score(s)")

    if gv_out:
        print(f"\nGV status   : {gv_out.status}")
        if gv_out.output:
            print(f"GV summary  : {gv_out.output.summary}")
            print(f"GV variants : {len(gv_out.output.results)} variant(s)")
            print(f"GV pathogenic count: {gv_out.output.pathogenic_count}")

    fh_out = result.get("family_history")
    if fh_out:
        print(f"\nFH status   : {fh_out.status}")
        if fh_out.output:
            print(f"FH summary  : {fh_out.output.summary}")
            print(f"FH results  : {len(fh_out.output.results)} record(s)")
            print(f"FH diseases meeting threshold: {fh_out.output.diseases_meeting_threshold}")

    pgx_out = result.get("pgx")
    if pgx_out:
        print(f"\nPGX status  : {pgx_out.status}")
        if pgx_out.output:
            print(f"PGX summary : {pgx_out.output.summary}")
            print(f"PGX results : {len(pgx_out.output.results)} drug-gene pair(s)")
            print(f"PGX genes   : {pgx_out.output.genes_assessed}")
            print(f"PGX drugs with recs: {pgx_out.output.drugs_with_recommendations}")

    ph_out = result.get("phenotype")
    if ph_out:
        print(f"\nPhenotype status   : {ph_out.status}")
        if ph_out.output:
            print(f"Phenotype summary  : {ph_out.output.summary}")
            print(f"Phenotype results  : {len(ph_out.output.results)} condition(s)")
            print(f"Relevant conditions: {ph_out.output.relevant_disease_names}")

    # ── Assertions ────────────────────────────────────────────────
    completed = result.get("agents_completed", [])

    assert "prs" in completed, (
        f"Expected 'prs' in agents_completed, got: {completed}"
    )
    assert "genomic_variants" in completed, (
        f"Expected 'genomic_variants' in agents_completed, got: {completed}"
    )

    assert prs_out is not None, "prs output should not be None"
    assert prs_out.status == "complete", (
        f"PRS agent status={prs_out.status!r}. Errors: {prs_out.errors}"
    )

    assert gv_out is not None, "genomic_variants output should not be None"
    assert gv_out.status == "complete", (
        f"Genomic variants agent status={gv_out.status!r}. Errors: {gv_out.errors}"
    )

    assert "family_history" in completed, (
        f"Expected 'family_history' in agents_completed, got: {completed}"
    )
    assert fh_out is not None, "family_history output should not be None"
    assert fh_out.status == "complete", (
        f"Family history agent status={fh_out.status!r}. Errors: {fh_out.errors}"
    )

    assert "pgx" in completed, (
        f"Expected 'pgx' in agents_completed, got: {completed}"
    )
    assert pgx_out is not None, "pgx output should not be None"
    assert pgx_out.status == "complete", (
        f"PGX agent status={pgx_out.status!r}. Errors: {pgx_out.errors}"
    )

    assert "phenotype" in completed, (
        f"Expected 'phenotype' in agents_completed, got: {completed}"
    )
    assert ph_out is not None, "phenotype output should not be None"
    assert ph_out.status == "complete", (
        f"Phenotype agent status={ph_out.status!r}. Errors: {ph_out.errors}"
    )

    assert result.get("next") == "end", (
        f"Expected next='end', got {result.get('next')!r} — router did not terminate cleanly"
    )

    print("\n--- All assertions passed ---")


if __name__ == "__main__":
    test_main_orchestrator()
    sys.exit(0)
