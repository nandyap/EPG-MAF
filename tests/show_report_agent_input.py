"""
show_report_agent_input.py
──────────────────────────
Runs the full orchestration pipeline with the same query used in the
main integration test and prints — as pretty-printed JSON — exactly
what the report agent will receive.

The output is the serialised form of prs, genomic_variants, and
family_history keys from OrchestrationAgentState (i.e. the three
XxxStateOutput objects after privacy stripping).

Run from project root:
    python3 tests/show_report_agent_input.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]   # .../EGP-Window/EGP-Window
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import duckdb

import agents.prs.tools.tools as prs_tools
import agents.genomic_variants.tools.tools as gv_tools
import agents.family_history.tools.tools as fh_tools
import agents.pgx.tools.tools as pgx_tools
import agents.phenotype.tools.tools as phenotype_tools
from agents.main.graph.graph import graph
from config.settings import get_settings


def _make_executor(db_path: str):
    def execute(sql: str, params) -> list[dict]:
        con = duckdb.connect(db_path, read_only=True)
        try:
            cur = con.execute(sql, list(params))
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]
        finally:
            con.close()
    return execute


def _get_patient_id(executor) -> str:
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
    rows = executor("SELECT patient_id FROM patient_prs LIMIT 1", [])
    if not rows:
        raise RuntimeError("No rows in patient_prs — is the DB seeded?")
    return str(rows[0]["patient_id"])


def main() -> None:
    settings = get_settings()
    executor = _make_executor(settings.db_path)

    prs_tools.configure(executor)
    gv_tools.configure(executor)
    fh_tools.configure(executor)
    pgx_tools.configure(executor)
    phenotype_tools.configure(executor)

    patient_id = _get_patient_id(executor)
    print(f"patient_id : {patient_id!r}\n", flush=True)

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

    # ── Build the payload the report agent will receive ───────────
    report_input: dict = {
        "patient_id": result.get("patient_id"),
        "original_query": result.get("original_query"),
        "agents_completed": result.get("agents_completed"),
    }

    for key in ("prs", "genomic_variants", "family_history", "pgx", "phenotype"):
        val = result.get(key)
        report_input[key] = val.model_dump() if val is not None else None

    print("=" * 72)
    print("REPORT AGENT INPUT (OrchestrationAgentState — public fields)")
    print("=" * 72)
    print(json.dumps(report_input, indent=2, default=str))


if __name__ == "__main__":
    main()
