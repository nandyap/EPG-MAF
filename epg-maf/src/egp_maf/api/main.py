"""Production ASGI entrypoint — imported by uvicorn/gunicorn.

Usage::

    uvicorn egp_maf.api.main:app --host 0.0.0.0 --port 8080

The container is built lazily on first import so unit tests keep using
their own containers.
"""

from __future__ import annotations

from egp_maf.api.app import create_app
from egp_maf.di import build_container

# Container is built once per process. Lifecycle (Postgres pool, Cosmos
# client, LLM factory) is opened by the FastAPI startup event that
# ``create_app`` registers.
_container = build_container()
app = create_app(_container)
