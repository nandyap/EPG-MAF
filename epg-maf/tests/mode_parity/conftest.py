"""Fixtures + marker registration for the mode-parity harness."""

from __future__ import annotations

import pytest


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    """Auto-mark every test in this package with ``mode_parity``."""
    for item in items:
        item.add_marker(pytest.mark.mode_parity)
