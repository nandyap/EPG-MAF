# Clinical Genomics Decision-Support System

A multi-agent clinical genomics assistant built with [LangGraph](https://github.com/langchain-ai/langgraph). Clinicians interact through a conversational chat interface; structured specialist agents retrieve and interpret patient genomic data from a DuckDB database and return clinician-ready responses.

---

## Overview

The system is organised as a graph of agents. A **chat agent** handles the conversation layer — deciding whether a clinician's message needs new data, or can be answered from context already retrieved in the session. When data is needed it delegates to the **main orchestration agent**, which routes to whichever **specialist subagents** are relevant to the query. Results are accumulated across the conversation and synthesised into a focused natural-language reply.

```
Clinician message
      │
      ▼
┌─────────────┐   needs data   ┌──────────────────┐   routes to   ┌─────────────────────┐
│ Chat Agent  │ ─────────────► │   Main Agent      │ ────────────► │  Specialist Agent   │
│ (routing +  │                │  (orchestrator)   │               │  prs / variants /   │
│  synthesis) │ ◄───────────── │                   │ ◄──────────── │  family_history /   │
└─────────────┘  AI response   └──────────────────┘   results     │  pgx / phenotype    │
                                                                   └─────────────────────┘
```

Each subagent runs a ReAct loop against the DuckDB, extracts structured output, and attaches DB provenance. The main agent re-evaluates after each subagent completes, dispatching only the agents relevant to the query — never re-running an agent that has already been completed for the current topic.

---

## Tool Calling Architecture

Every specialist subagent follows a structured three-tool pattern (two tools for phenotype, which has no annotation table):

| Tool | Name pattern | Role |
|------|-------------|------|
| **1 — Explore** | `explore_patient_<domain>` | Lightweight patient-scoped discovery. Takes only `patient_id`. Queries a single patient-side table (`patient_prs`, `patient_variants`, etc.) filtered by `patient_id` — no SQL JOIN to any reference or annotation table. Returns the minimal set of keys (IDs, names, flags) the agent needs to orient itself. |
| **2 — Annotate** | `search_<domain>_annotations` | Reference-only lookup. Takes identifiers or search terms. Queries annotation/reference tables only — no patient table, no `patient_id` filter. Primary key fields use exact matching (values come directly from Tool 1); free-text concept fields use substring matching. |
| **3 — Retrieve** | `get_patient_<domain>` | Full patient result. The only tool that JOINs a patient table to an annotation table. All filter parameters are optional; when supplied they use exact matching — the agent has precise identifiers by this point. |

The system prompt for each agent explicitly mandates this call order, preventing agents from skipping the explore step and calling the retrieve tool directly.

```
explore_patient_<domain>(patient_id)
  └─► search_<domain>_annotations(exact_id | fuzzy_term)
        └─► get_patient_<domain>(patient_id, exact_id, ...)
```

This separation keeps individual tool queries cheap and focused, and ensures annotation context is always gathered before a full patient JOIN is executed.

---

## Agents

### Chat Agent — `agents/chat/`

The user-facing layer. Receives clinician messages and handles two responsibilities:

**1. Routing** — A structured-output LLM call decides whether the query needs a DB lookup. If the disease or topic has shifted substantially from a previous query (e.g., Alzheimer's → breast cancer), the affected agents are invalidated and re-dispatched. Otherwise the cached results are reused.

**2. Synthesis** — After data retrieval (or if no retrieval is needed), the chat LLM answers the clinician's specific question using all available clinical context. Provenance records are stripped before synthesis; all other structured fields are included.

---

### Main Agent — `agents/main/`

The orchestration layer. Receives a patient ID, a query, and the current completion state. An LLM emits a `RouterDecision` selecting which specialist to run next, and the graph loops — subagent → router → subagent — until all relevant agents have completed, at which point it returns `end`.

The router respects `agents_completed` to prevent unnecessary re-runs and accepts an optional `requested_diseases` filter to narrow subagent retrieval to specific conditions.

---

### PRS Agent — `agents/prs/`

Retrieves and interprets polygenic risk scores (PRS). Follows the three-tool pattern:

1. `explore_patient_prs` — returns the `prs_name`, `disease_name`, and `risk_band` recorded for this patient (no JOIN).
2. `search_prs_annotations` — looks up source and notes from `prs_annotations` by exact `prs_name` or fuzzy `disease_name`.
3. `get_patient_prs` — fetches the full joined row from `patient_prs JOIN prs_annotations` using exact filters.

Produces `PRSResult` objects with percentile, risk band, disease name, annotation metadata, and a per-score clinical interpretation.

---

### Genomic Variants Agent — `agents/genomic_variants/`

Retrieves rare genomic variants for a patient. Follows the three-tool pattern:

1. `explore_patient_genomic_variants` — returns the `variant_id` and `genotype` for each variant carried by this patient (no JOIN).
2. `search_variant_annotations` — looks up full annotation detail from `variant_annotations` by exact `variant_id` or fuzzy gene/disease/pathogenicity filters.
3. `get_patient_genomic_variants` — fetches the full joined row from `patient_variants JOIN variant_annotations` using exact filters.

Produces `GenomicVariantResult` objects with gene, variant ID, pathogenicity, extended annotations (parsed from `annotations_json`), and a clinical interpretation. Tracks pathogenic and likely-pathogenic counts as derived fields.

---

### Family History Agent — `agents/family_history/`

Evaluates structured family history criteria (e.g., NCCN HBOC, Amsterdam II) against the patient's recorded kinship data. Follows the three-tool pattern:

1. `explore_patient_family_history` — returns the `disease_name`, `criteria_name`, and `meets_threshold` for each record (no JOIN).
2. `search_family_history_annotations` — looks up description and guideline source from `kinship_history_annotations` by exact `criteria_name` or fuzzy `disease_name`.
3. `get_patient_family_history` — fetches the full joined row from `patient_kinship_history JOIN kinship_history_annotations` using exact filters.

Produces `FamilyHistoryCriteriaResult` objects indicating whether each threshold is met, with a qualified interpretation when the search population was demographically incomplete. Privacy-sensitive aggregate fields are stripped before results are passed to the orchestrator.

---

### PGX Agent — `agents/pgx/`

Retrieves pharmacogenomics (PGX) records — drug-gene interactions, metabolizer status, and CPIC-based prescribing recommendations. Follows the three-tool pattern:

1. `explore_patient_pgx` — returns the `gene`, `diplotype`, and `phenotype` assessed for this patient (no JOIN).
2. `search_pgx_annotations` — looks up drug recommendations from `pgx_annotations` by exact `gene`/`phenotype` or fuzzy `drug` name.
3. `get_patient_pgx` — fetches the full joined row from `patient_pgx_status LEFT JOIN pgx_annotations` using an exact `gene` filter.

Produces `PGXDrugResult` objects per drug-gene pair with diplotype, phenotype, recommendation, and a clinical interpretation of the metabolizer status.

---

### Phenotype Agent — `agents/phenotype/`

Retrieves the patient's clinical diagnoses from the OMOP-coded diagnoses table. Uses a two-tool pattern (no separate annotation table exists for this domain):

1. `explore_patient_phenotype` — returns the distinct `(disease_name, term, code_type)` combinations recorded for this patient. Used to identify relevant conditions before pulling full encounter detail.
2. `get_patient_diagnoses` — fetches grouped encounter statistics (encounter count, first/last dates, codes, terms) using an exact `disease_name` filter from step 1.

Produces `PhenotypeDiseaseResult` objects with disease name, encounter statistics, relevance judgment, and a clinical interpretation. A `search_phenotype_annotations` tool will be added when a dedicated annotation table is introduced.

---

## Project Structure

```
agents/
├── chat/               # Chat agent (routing + synthesis)
│   ├── graph/
│   ├── models/
│   ├── prompts/
│   ├── state/
│   └── tests/
├── main/               # Main orchestration agent
│   ├── graph/
│   ├── models/
│   ├── prompts/
│   ├── state/
│   └── tests/
├── prs/                # Polygenic risk score subagent
├── genomic_variants/   # Rare variant subagent
├── family_history/     # Family history subagent
├── pgx/                # Pharmacogenomics subagent
├── phenotype/          # Phenotype / diagnoses subagent
└── shared/
    └── state/          # Shared Pydantic models (provenance, tool execution, vocabularies)
config/
├── llm.py              # Per-agent model configuration (one place to swap models)
└── settings.py         # Environment settings (DB path, API key, base URL)
test_data/
├── clinical_genetics.duckdb   # Seeded test database
└── schema.sql                 # DuckDB schema
langgraph.json          # Graph registry for langgraph dev
requirements.txt
```

---

## Setup

**1. Clone and install dependencies**

```bash
git clone <repo-url>
cd Shiny-Graph
pip install -r requirements.txt
```

**2. Configure environment**

Create a `.env` file in the project root:

```env
LLM_API_KEY=your-api-key-here
LLM_BASE_URL=https://api.core42.ai/v1   # or https://api.openai.com/v1
```

The settings file accepts `LLM_API_KEY` or `OPENAI_API_KEY`. `LLM_BASE_URL` defaults to `https://api.core42.ai/v1` if omitted.

**3. Verify the test database**

The repository includes a seeded DuckDB at `test_data/clinical_genetics.duckdb`. No additional DB setup is required for development and testing.

---

## Launching LangGraph Dev

With `langgraph-cli` installed (included in `requirements.txt`), run from the project root:

```bash
langgraph dev
```

This starts the LangGraph development server and opens LangGraph Studio in your browser. Two graphs are registered:

| Graph ID | Entry point                          | Description                          |
|----------|--------------------------------------|--------------------------------------|
| `chat`   | `agents/chat/graph/graph.py:graph`   | Full chat interface (recommended)    |
| `main`   | `agents/main/graph/graph.py:graph`   | Orchestration agent (direct access)  |

**Invoking the chat graph** — example initial state:

```json
{
  "patient_id": "P001",
  "messages": [
    { "role": "user", "content": "What are this patient's polygenic risk scores for Alzheimer's disease?" }
  ],
  "agents_completed": []
}
```

Send follow-up messages in the same thread to continue the conversation. The graph accumulates subagent results across turns and only re-queries the database when new information is needed.

---

## Model Configuration

All per-agent model choices are centralised in `config/llm.py`. To change the model for any agent, edit the `AGENT_LLM_CONFIGS` dict — no changes are needed elsewhere.

| Agent              | Current model | Notes                                      |
|--------------------|---------------|--------------------------------------------|
| `chat`             | gpt-5.1       | Conversational routing and synthesis       |
| `main`             | gpt-4.1       | Orchestration routing                      |
| `prs`              | gpt-4.1       | PRS retrieval and percentile interpretation |
| `genomic_variants` | gpt-4.1       | Variant pathogenicity interpretation       |
| `family_history`   | gpt-4.1       | Pedigree threshold evaluation              |
| `pgx`              | gpt-4.1       | Drug-gene interaction lookup               |
| `phenotype`        | gpt-4.1       | Diagnosis retrieval                        |

---

## Running Tests

Each agent has its own integration test that wires the DuckDB executor and runs the full agent pipeline.

```bash
# Individual agents
python3 agents/chat/tests/test_chat_agent.py
python3 agents/main/tests/test_main_agent.py
python3 agents/prs/tests/test_prs_agent.py
python3 agents/genomic_variants/tests/test_genomic_variants_agent.py
python3 agents/family_history/tests/test_family_history_agent.py
python3 agents/pgx/tests/test_pgx_agent.py
python3 agents/phenotype/tests/test_phenotype_agent.py

# All tests via pytest
pytest agents/
```

---

## Next Steps / Improvements

### 1. Parallelise subagent execution

Subagents are currently dispatched sequentially by the main orchestration agent — each runs to completion before the router decides what to call next. For queries that touch multiple domains (e.g. PRS + variants + PGX), the agents are independent and could run concurrently using LangGraph's `Send` API or a `fan-out / fan-in` subgraph pattern. This would reduce end-to-end latency proportionally to the number of agents dispatched.

### 2. Ontology subagent

Disease names, gene symbols, and clinical terms appear across multiple tables (`prs_annotations.disease_name`, `variant_annotations.disease_name`, `diagnoses.disease_name`, `kinship_history_annotations.disease_name`) but are not normalised to a shared ontology. A lightweight ontology subagent — or a shared lookup tool — could map free-text terms and synonyms to canonical identifiers (OMIM, MONDO, HPO) before subagents run. This would improve cross-domain result correlation and reduce missed matches when the same condition is named differently across tables.

### 3. Evaluation loops in the main graph

The main agent currently routes to subagents and returns results without any self-verification step. Adding an evaluation loop — where the orchestrator checks result completeness, flags missing or low-confidence outputs, and re-dispatches a subagent with a refined query if needed — would improve robustness. This could be implemented as an LLM-scored `EvaluationDecision` node that sits between each subagent completion and the next routing step, mirroring patterns from LangGraph's corrective RAG examples.
