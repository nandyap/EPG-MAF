"""W11 — HTTP layer (FastAPI).

Public surface:

- :func:`create_app` — build a :class:`fastapi.FastAPI` app wired to
  a DI :class:`Container`.
- :class:`ChatRequestBody` / :class:`ChatResponseBody` — Pydantic
  models for the ``POST /chat`` contract.

This module is the FIRST layer that owns the HTTP surface. Prior
workstreams delivered everything under it:

- **W07** — :class:`Authenticator` protocol behind
  :class:`EntraTokenAuthenticator` / :class:`StubAuthenticator`.
- **W08** — :func:`workflow_request_span` root span for the turn +
  :func:`get_current_trace_and_span_ids` for response correlation.
- **W09** — :func:`format_error_response` transport-agnostic
  ``{error_code, message, trace_id}`` envelope.
- **W04/W05** — :class:`WorkflowRuntime.run_turn` executes the
  chat workflow.
"""

from __future__ import annotations

from egp_maf.api.app import create_app
from egp_maf.api.schemas import ChatRequestBody, ChatResponseBody

__all__ = ["create_app", "ChatRequestBody", "ChatResponseBody"]
