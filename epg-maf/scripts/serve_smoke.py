"""Serve the FastAPI app with the stub container so a browser can hit it.

Run:

    cd epg-maf
    .\.venv\Scripts\Activate.ps1
    python scripts\serve_smoke.py

Then open:

    http://127.0.0.1:8000/docs          Swagger UI (interactive)
    http://127.0.0.1:8000/redoc         ReDoc (read-only, prettier)
    http://127.0.0.1:8000/healthz       plain health probe

The Container is the same stub-wired one used by ``smoke_run.py`` -
no LLM key, no Postgres, no Cosmos. Perfect for showing the API
surface to non-technical stakeholders (product owners, managers,
clinical reviewers) without touching a real endpoint.

Send POST /chat with:

    Authorization: Bearer {"oid":"demo","tid":"demo","roles":["Clinician"],"exp":9999999999}

Body:

    {
      "thread_id": "T-1",
      "patient_id": "P001",
      "message": "What PRS does this patient have?"
    }

The response will show the workflow's canned PRS result flowing
through the API projection - exact same code path as production.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("LLM_API_KEY", "smoke-run-stub")

# Make ``tests.support`` and this repo's ``scripts`` package importable.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from smoke_run import _make_container  # reuse the wiring


def main() -> None:
    import uvicorn

    from egp_maf.api import create_app

    # Slice 2: use the keyword-driven stub router so demo questions
    # dispatch realistically ("what PRS…?" → prs only; "family history?"
    # → family_history only; "give me everything" → all five).
    container = _make_container(scenario="keyword")
    app = create_app(container)

    print("\n" + "=" * 60)
    print(" EGP Window - smoke server ready")
    print("=" * 60)
    print(" Swagger UI:  http://127.0.0.1:8000/docs")
    print(" ReDoc:       http://127.0.0.1:8000/redoc")
    print(" Health:      http://127.0.0.1:8000/healthz")
    print("=" * 60)
    print(" POST /chat requires: Authorization: Bearer <json-token>")
    print(' Token: {"oid":"demo","tid":"demo","roles":["Clinician"],"exp":9999999999}')
    print("=" * 60 + "\n")

    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")


if __name__ == "__main__":
    main()
