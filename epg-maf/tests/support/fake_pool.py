"""Test-support fake for the psycopg async pool.

The five domain-repository unit tests use this rather than a real database.
Verifies:

- SQL text was issued (regex-tolerant to whitespace).
- Parameter list is exactly what we expected.
- Rows return as dicts (matches psycopg row factory behaviour).

Kept separate from ``tests/support/authz_doubles.py`` so imports read
cleanly per concern.
"""

from __future__ import annotations

from typing import Any


class FakeColumn:
    def __init__(self, name: str) -> None:
        self.name = name


class FakeCursor:
    """Records the SQL + params and returns the pre-configured rows."""

    def __init__(self, pool: "FakePool") -> None:
        self._pool = pool
        self.description: list[FakeColumn] | None = None

    async def execute(self, sql: str, params: list[Any]) -> None:
        self._pool.executed.append((sql, list(params)))
        # Pop the next canned response
        rows_and_columns = self._pool.next_response()
        self._rows = rows_and_columns[0]
        column_names = rows_and_columns[1]
        self.description = [FakeColumn(name) for name in column_names]

    async def fetchall(self) -> list[tuple[Any, ...]]:
        return self._rows


class FakeCursorCtx:
    def __init__(self, pool: "FakePool") -> None:
        self._pool = pool

    async def __aenter__(self) -> FakeCursor:
        return FakeCursor(self._pool)

    async def __aexit__(self, *_: object) -> None:
        return None


class FakeConn:
    def __init__(self, pool: "FakePool") -> None:
        self._pool = pool

    def cursor(self) -> FakeCursorCtx:
        return FakeCursorCtx(self._pool)


class FakeConnCtx:
    def __init__(self, pool: "FakePool") -> None:
        self._pool = pool

    async def __aenter__(self) -> FakeConn:
        return FakeConn(self._pool)

    async def __aexit__(self, *_: object) -> None:
        return None


class FakePool:
    """Programmable stand-in for ``psycopg_pool.AsyncConnectionPool``.

    Push one ``(rows, column_names)`` tuple per anticipated execute() call
    via :meth:`push_response`.
    """

    def __init__(self) -> None:
        self.executed: list[tuple[str, list[Any]]] = []
        self._responses: list[tuple[list[tuple[Any, ...]], list[str]]] = []

    def push_response(
        self, rows: list[tuple[Any, ...]], column_names: list[str]
    ) -> None:
        self._responses.append((rows, column_names))

    def next_response(self) -> tuple[list[tuple[Any, ...]], list[str]]:
        if not self._responses:
            return ([], [])
        return self._responses.pop(0)

    def connection(self) -> FakeConnCtx:
        return FakeConnCtx(self)


class FakePoolFactory:
    """Duck-typed as ``DbPoolFactory`` — exposes ``.pool`` and ``get_pool()``.

    ``BaseRepository`` awaits ``get_pool()`` so the pool can be opened on
    demand (and recover after a failed startup connect). The synchronous
    ``pool`` property is kept for callers that already hold an open pool.
    """

    def __init__(self, pool: FakePool) -> None:
        self.fake_pool = pool

    @property
    def pool(self) -> FakePool:
        return self.fake_pool

    async def get_pool(self) -> FakePool:
        return self.fake_pool
