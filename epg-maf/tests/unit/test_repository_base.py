"""Unit tests for :class:`egp_maf.services.repositories.base.BaseRepository`.

Covers the parts that don't touch a real database:

- ``_authorize`` delegates to :class:`AuthzPolicy` and surfaces
  :class:`AccessDenied`.
- ``_build_provenance`` delegates to :class:`ProvenanceService`.
- ``_fetch_all`` wraps driver errors as :class:`DatabaseUnavailable`.

Live-query behaviour is exercised in the integration test suite.
"""

from __future__ import annotations

from typing import Any

import pytest

from egp_maf.errors import AccessDenied, DatabaseUnavailable
from egp_maf.infrastructure.db_pool import DbPoolFactory
from egp_maf.services.provenance import ProvenanceService
from egp_maf.services.repositories import BaseRepository
from egp_maf.state.clinician_context import ClinicianContext
from tests.support.authz_doubles import ClosedAuthzPolicy, OpenAuthzPolicy


class _FakePool:
    """Test double for ``psycopg_pool.AsyncConnectionPool``."""

    def __init__(self, *, raise_on_execute: Exception | None = None) -> None:
        self._raise_on_execute = raise_on_execute
        self.executed_sql: list[tuple[str, list[Any]]] = []

    def connection(self) -> "_FakeConnCtx":
        return _FakeConnCtx(self)


class _FakeConnCtx:
    def __init__(self, pool: _FakePool) -> None:
        self._pool = pool

    async def __aenter__(self) -> "_FakeConn":
        return _FakeConn(self._pool)

    async def __aexit__(self, *_: object) -> None:
        return None


class _FakeConn:
    def __init__(self, pool: _FakePool) -> None:
        self._pool = pool

    def cursor(self) -> "_FakeCursorCtx":
        return _FakeCursorCtx(self._pool)


class _FakeCursorCtx:
    def __init__(self, pool: _FakePool) -> None:
        self._pool = pool

    async def __aenter__(self) -> "_FakeCursor":
        return _FakeCursor(self._pool)

    async def __aexit__(self, *_: object) -> None:
        return None


class _FakeCursor:
    def __init__(self, pool: _FakePool) -> None:
        self._pool = pool
        self.description: Any = None

    async def execute(self, sql: str, params: list[Any]) -> None:
        self._pool.executed_sql.append((sql, params))
        if self._pool._raise_on_execute is not None:  # noqa: SLF001
            raise self._pool._raise_on_execute  # noqa: SLF001
        # Two-column dummy result-set.
        self.description = _FakeDescription([("a", "int"), ("b", "text")])

    async def fetchall(self) -> list[tuple[Any, ...]]:
        return [(1, "x"), (2, "y")]


class _FakeDescription:
    """Minimal description iterable — each element has a ``.name`` attribute."""

    def __init__(self, columns: list[tuple[str, str]]) -> None:
        self._cols = [_FakeColumn(name) for name, _ in columns]

    def __iter__(self) -> Any:
        return iter(self._cols)


class _FakeColumn:
    def __init__(self, name: str) -> None:
        self.name = name


class _FakePoolFactory(DbPoolFactory):
    def __init__(self, pool: _FakePool) -> None:
        self._fake_pool = pool

    @property
    def pool(self) -> Any:  # type: ignore[override]
        return self._fake_pool


def _ctx() -> ClinicianContext:
    return ClinicianContext(clinician_id="c1", tenant_id="t1", roles=frozenset({"Clinician"}))


# ── Tests ────────────────────────────────────────────────────────────


class TestAuthorize:
    def test_open_policy_allows(self) -> None:
        repo = BaseRepository(
            pool_factory=_FakePoolFactory(_FakePool()),
            authz=OpenAuthzPolicy(),
            provenance=ProvenanceService(),
        )
        repo._authorize(_ctx(), "P001")  # noqa: SLF001

    def test_closed_policy_raises(self) -> None:
        repo = BaseRepository(
            pool_factory=_FakePoolFactory(_FakePool()),
            authz=ClosedAuthzPolicy(),
            provenance=ProvenanceService(),
        )
        with pytest.raises(AccessDenied):
            repo._authorize(_ctx(), "P001")  # noqa: SLF001


class TestBuildProvenance:
    def test_build_delegates(self) -> None:
        repo = BaseRepository(
            pool_factory=_FakePoolFactory(_FakePool()),
            authz=OpenAuthzPolicy(),
            provenance=ProvenanceService(),
        )
        p = repo._build_provenance(  # noqa: SLF001
            tool_name="t",
            tool_parameters={"k": "v"},
            source_table="table",
            source_row={"a": 1},
            fields_derived=["a"],
        )
        assert p.tool_name == "t"
        assert p.source_row == {"a": 1}
        assert p.fields_derived == ["a"]


class TestFetchAll:
    async def test_returns_dict_rows(self) -> None:
        pool = _FakePool()
        repo = BaseRepository(
            pool_factory=_FakePoolFactory(pool),
            authz=OpenAuthzPolicy(),
            provenance=ProvenanceService(),
        )
        rows = await repo._fetch_all("SELECT 1", [])  # noqa: SLF001
        assert rows == [{"a": 1, "b": "x"}, {"a": 2, "b": "y"}]
        assert pool.executed_sql == [("SELECT 1", [])]

    async def test_wraps_driver_error(self) -> None:
        boom = RuntimeError("connection reset by peer")
        pool = _FakePool(raise_on_execute=boom)
        repo = BaseRepository(
            pool_factory=_FakePoolFactory(pool),
            authz=OpenAuthzPolicy(),
            provenance=ProvenanceService(),
        )
        with pytest.raises(DatabaseUnavailable) as exc:
            await repo._fetch_all("SELECT 1", [])  # noqa: SLF001
        assert exc.value.__cause__ is boom
