# EGP Window — MAF Implementation (`epg-maf`)

Target-stack implementation of the EGP Window clinical genomics decision-support agent.
Sibling to the LangGraph prototype (`agents/`, `config/`, `test_data/`) which remains
untouched as the **reference implementation** for parity testing.

**Stack:** Python 3.11+ · Microsoft Agent Framework · Azure OpenAI-compatible APIM →
Compass · PostgreSQL (psycopg 3) · Azure Cosmos DB for NoSQL · Azure Container Apps
(deployment target).

**Design baseline:** `../docs/architecture-discovery-report.md`,
`../docs/solution-design-package.md`, `../docs/engineering-implementation-plan.md`.

## Layout

```
src/egp_maf/
├── config/            Settings (env), AGENT_LLM_CONFIGS
├── di/                Hand-rolled DI container + lifecycle
├── infrastructure/    db_pool (psycopg 3), compass_client (MAF), cosmos_client
├── logging/           Structured JSON logging
├── prompts/           Bundled prompts + PromptService loader
├── services/          PromptService, ThreadStateProvider
├── state/             SessionDocument, ClinicianContext
└── errors.py          Typed exceptions (grows per workstream)

tests/
├── unit/              Fast, no external deps
├── integration/       Requires local Postgres + Cosmos emulator
└── parity/            Byte-parity vs. LangGraph prototype
```

## Setup

```powershell
cd epg-maf
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
cp .env.example .env             # populate secrets locally
pytest tests/unit                # unit tests (no services required)
```

## Workstreams

Each workstream has a log at `../docs/workstreams/W<NN>-<name>.md`.

- **W01 — Foundation** (this workstream): config, DI, logging, prompt loader, Postgres
  pool, Cosmos client, ThreadStateProvider, Compass client factory. No agents.
- W02 onwards: repositories, specialists, workflow, orchestration, auth, observability,
  resilience, testing, cutover.

## Coding conventions

- One package per concern (`config/`, `services/`, `infrastructure/`, `state/`, …).
- Constructor injection everywhere. No module-level singletons except configuration.
- Typed interfaces (`Protocol` classes) for anything the DI container can swap.
- `mypy --strict` on `src/`; `ruff` on everything.
- Zero PHI in logs, spans, or exceptions — enforced by tests.
