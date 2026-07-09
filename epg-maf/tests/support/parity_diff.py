"""Structural-equality diff helper for the W06 mode-parity harness.

The problem: two workflow runs (one sequential, one parallel) produce
:class:`ChatWorkflowState`s that should be *structurally identical* on
every field the clinician sees, but will differ on timing metadata
(``updated_at`` on each specialist slot, ``timestamp`` on messages) and
possibly on ``router_iterations`` (fewer under parallel).

:func:`deep_diff` returns a list of dotted-path differences, ignoring
the well-known volatile keys. An empty list means the two states are
structurally equal.

This module is *test-only* — it lives under :mod:`tests.support` and
carries no runtime dependency.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

# Keys that legitimately differ between runs / modes and must be excluded
# from structural equality. Kept as a frozenset so callers can extend it
# per-scenario without mutating the shared default.
DEFAULT_IGNORE_KEYS: frozenset[str] = frozenset(
    {
        "updated_at",         # SpecialistSlot per-write timestamp
        "produced_at",        # stub-specialist payload timestamp
        "timestamp",          # SessionMessage created-at
        "router_iterations",  # parallel mode uses fewer iterations
        "retrieved_at",       # DBProvenance stamp
    }
)


def deep_diff(
    a: Any,
    b: Any,
    *,
    path: str = "",
    ignore_keys: Iterable[str] = DEFAULT_IGNORE_KEYS,
    ignore_list_order_at: Iterable[str] = ("agents_completed",),
) -> list[str]:
    """Return dotted-path differences between ``a`` and ``b``.

    Semantics:

    - Dicts compared key-by-key; keys in ``ignore_keys`` are skipped at
      any depth.
    - Lists compared element-by-element in order, **except** when the
      current ``path`` (or a suffix of it) is in ``ignore_list_order_at``,
      in which case the two are compared as sorted lists.
    - Scalars compared with ``==``.

    An empty return list means the two structures are equal for our
    parity purposes.
    """
    diffs: list[str] = []
    _walk(a, b, path=path, ignore_keys=set(ignore_keys),
          ignore_list_order_at=set(ignore_list_order_at), diffs=diffs)
    return diffs


def _walk(
    a: Any,
    b: Any,
    *,
    path: str,
    ignore_keys: set[str],
    ignore_list_order_at: set[str],
    diffs: list[str],
) -> None:
    # Type mismatch — record and stop.
    if type(a) is not type(b) and not (isinstance(a, dict) and isinstance(b, dict)) \
            and not (isinstance(a, list) and isinstance(b, list)):
        diffs.append(f"{path or '<root>'}: type {type(a).__name__} != {type(b).__name__}")
        return

    if isinstance(a, dict) and isinstance(b, dict):
        keys_a = {k for k in a if k not in ignore_keys}
        keys_b = {k for k in b if k not in ignore_keys}
        if keys_a != keys_b:
            only_a = sorted(keys_a - keys_b)
            only_b = sorted(keys_b - keys_a)
            if only_a:
                diffs.append(f"{path or '<root>'}: only in first: {only_a}")
            if only_b:
                diffs.append(f"{path or '<root>'}: only in second: {only_b}")
        for k in sorted(keys_a & keys_b):
            _walk(
                a[k],
                b[k],
                path=f"{path}.{k}" if path else k,
                ignore_keys=ignore_keys,
                ignore_list_order_at=ignore_list_order_at,
                diffs=diffs,
            )
        return

    if isinstance(a, list) and isinstance(b, list):
        # Path-based order-insensitive comparison.
        current_key = path.rsplit(".", 1)[-1]
        if current_key in ignore_list_order_at:
            sa = sorted(a, key=_stable_key)
            sb = sorted(b, key=_stable_key)
            if sa != sb:
                diffs.append(f"{path}: sorted lists differ: {sa!r} != {sb!r}")
            return
        if len(a) != len(b):
            diffs.append(f"{path}: list length {len(a)} != {len(b)}")
            return
        for i, (x, y) in enumerate(zip(a, b, strict=True)):
            _walk(
                x,
                y,
                path=f"{path}[{i}]",
                ignore_keys=ignore_keys,
                ignore_list_order_at=ignore_list_order_at,
                diffs=diffs,
            )
        return

    if a != b:
        diffs.append(f"{path or '<root>'}: {a!r} != {b!r}")


def _stable_key(value: Any) -> str:
    """Turn any value into a sortable string for order-insensitive
    list comparison. We only need stability, not a natural ordering."""
    try:
        return repr(value)
    except Exception:
        return str(id(value))
