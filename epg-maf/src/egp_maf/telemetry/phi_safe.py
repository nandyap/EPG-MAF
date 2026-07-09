"""PHI-safety guards on OTEL span attributes.

Design §10.4: no PHI, no prompt text, no row content on spans. This
module supplies the one function every caller should use to set span
attributes:

.. code-block:: python

    from opentelemetry import trace
    from egp_maf.telemetry import safe_set_attribute

    span = trace.get_current_span()
    safe_set_attribute(span, "specialist.name", "prs")  # OK
    safe_set_attribute(span, "prompt_text", "…")  # → ForbiddenAttributeError

An import-linter rule pins direct calls to
:meth:`opentelemetry.trace.Span.set_attribute` at zero outside
:mod:`egp_maf.telemetry.spans` (which itself uses
:func:`safe_set_attribute`).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from egp_maf.errors import EgpError
from egp_maf.telemetry.attributes import (
    ALLOWED_ATTRIBUTES,
    FORBIDDEN_ATTRIBUTES,
)

if TYPE_CHECKING:  # pragma: no cover
    from opentelemetry.trace import Span


class ForbiddenAttributeError(EgpError):
    """Raised when a caller tries to set a PHI-forbidden attribute on
    a span. Design §10.4."""

    error_code = "phi_attribute_forbidden"
    http_status = 500


def safe_set_attribute(span: "Span", key: str, value: Any) -> None:
    """Set ``key = value`` on ``span`` after enforcing the PHI-safety
    contract.

    - If ``key`` is in :data:`FORBIDDEN_ATTRIBUTES`,
      :class:`ForbiddenAttributeError` is raised — no attribute is
      applied.
    - If ``key`` is not in :data:`ALLOWED_ATTRIBUTES`, we silently drop
      it. The reason: we want ``ALLOWED_ATTRIBUTES`` to be a strict
      contract, but we don't want a typo in a caller to crash a
      production workflow. Drift shows up as missing attributes in
      dashboards, which QA catches. **Forbidden names, on the other
      hand, are a security regression — those raise loudly.**
    - Otherwise, forwards to :meth:`Span.set_attribute`.
    """
    if key in FORBIDDEN_ATTRIBUTES:
        raise ForbiddenAttributeError(
            f"Attempted to set PHI-forbidden attribute {key!r} on a span. "
            f"See egp_maf.telemetry.attributes.FORBIDDEN_ATTRIBUTES."
        )
    if key not in ALLOWED_ATTRIBUTES:
        # Silent drop — surfaces as missing attribute in dashboards.
        return
    # Some values (None) aren't valid OTEL attribute values; skip.
    if value is None:
        return
    span.set_attribute(key, value)
