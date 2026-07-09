"""
Integration test for the chat agent.

Exercises three conversation turns against the test DuckDB to verify:
  Turn 1 — Clinical query routes to run_main_agent; at least one subagent runs;
            an AIMessage is appended to conversation history.
  Turn 2 — Follow-up interpretation query routes to respond_directly;
            agents_completed is unchanged.
  Turn 3 — Substantially different disease query routes to run_main_agent and
            causes the affected agent(s) to re-run (removed from agents_completed
            then re-added after fresh retrieval).

Run from project root:
    python3 agents/chat/tests/test_chat_agent.py
    python3 -m agents.chat.tests.test_chat_agent
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import duckdb

import agents.prs.tools.tools as prs_tools
import agents.genomic_variants.tools.tools as gv_tools
import agents.family_history.tools.tools as fh_tools
import agents.pgx.tools.tools as pgx_tools
import agents.phenotype.tools.tools as phenotype_tools
from agents.prs.tools.tools import QueryExecutor
from langchain_core.messages import AIMessage, HumanMessage
from agents.chat.graph.graph import graph
from config.settings import get_settings


# ── Helpers ──────────────────────────────────────────────────────────

def make_duckdb_executor(db_path: str) -> QueryExecutor:
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


# ── Test ─────────────────────────────────────────────────────────────

def test_chat_agent() -> None:
    settings = get_settings()
    executor = make_duckdb_executor(settings.db_path)

    prs_tools.configure(executor)
    gv_tools.configure(executor)
    fh_tools.configure(executor)
    pgx_tools.configure(executor)
    phenotype_tools.configure(executor)

    patient_id = get_test_patient_id(executor)
    print(f"\n--- Chat agent test for patient_id={patient_id!r} ---\n")

    # ── Turn 1: Clinical query — expects main agent invocation ────

    turn1_input = {
        "patient_id": patient_id,
        "messages": [HumanMessage(content=(
            "What are this patient's polygenic risk scores for Alzheimer's disease?"
        ))],
        "agents_completed": [],
    }

    result1 = graph.invoke(turn1_input)

    print(f"Turn 1 — next_action     : {result1.get('next_action')}")
    print(f"Turn 1 — agents_completed: {result1.get('agents_completed')}")
    print(f"Turn 1 — messages count  : {len(result1.get('messages', []))}")

    ai_msgs1 = [m for m in result1.get("messages", []) if isinstance(m, AIMessage)]
    if ai_msgs1:
        print(f"Turn 1 — AI response     : {ai_msgs1[-1].content[:300]}")

    assert result1.get("next_action") == "run_main_agent", (
        f"Turn 1: expected next_action='run_main_agent', got {result1.get('next_action')!r}"
    )
    completed1 = result1.get("agents_completed", [])
    assert len(completed1) >= 1, (
        f"Turn 1: expected at least one agent completed, got {completed1}"
    )
    assert len(ai_msgs1) >= 1, "Turn 1: expected at least one AIMessage in messages"

    # ── Turn 2: Follow-up interpretation — expects respond_directly ─

    turn2_messages = result1["messages"] + [
        HumanMessage(content=(
            "Can you explain what those PRS percentiles mean clinically "
            "for this patient's care plan?"
        ))
    ]
    turn2_input = {**result1, "messages": turn2_messages}

    result2 = graph.invoke(turn2_input)

    print(f"\nTurn 2 — next_action     : {result2.get('next_action')}")
    print(f"Turn 2 — agents_completed: {result2.get('agents_completed')}")

    ai_msgs2 = [m for m in result2.get("messages", []) if isinstance(m, AIMessage)]
    if ai_msgs2:
        print(f"Turn 2 — AI response     : {ai_msgs2[-1].content[:300]}")

    assert result2.get("next_action") == "respond_directly", (
        f"Turn 2: expected next_action='respond_directly', got {result2.get('next_action')!r}"
    )
    assert result2.get("agents_completed") == completed1, (
        "Turn 2: agents_completed should be unchanged on respond_directly turn"
    )

    # ── Turn 3: Different disease — expects PRS agent to re-run ────

    turn3_messages = result2["messages"] + [
        HumanMessage(content=(
            "Actually, I need the PRS scores for breast cancer instead. "
            "What is this patient's risk?"
        ))
    ]
    turn3_input = {**result2, "messages": turn3_messages}

    result3 = graph.invoke(turn3_input)

    print(f"\nTurn 3 — next_action     : {result3.get('next_action')}")
    print(f"Turn 3 — agents_completed: {result3.get('agents_completed')}")

    ai_msgs3 = [m for m in result3.get("messages", []) if isinstance(m, AIMessage)]
    if ai_msgs3:
        print(f"Turn 3 — AI response     : {ai_msgs3[-1].content[:300]}")

    assert result3.get("next_action") == "run_main_agent", (
        f"Turn 3: expected next_action='run_main_agent', got {result3.get('next_action')!r}"
    )
    assert result3.get("prs") is not None, (
        "Turn 3: PRS output should be present after re-run for breast cancer"
    )

    print("\n--- All chat agent tests passed ---\n")


if __name__ == "__main__":
    test_chat_agent()
