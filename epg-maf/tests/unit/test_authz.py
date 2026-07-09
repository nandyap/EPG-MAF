"""Unit tests for :mod:`egp_maf.services.authz`."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from egp_maf.errors import AccessDenied, ConfigurationError
from egp_maf.services.authz import AllowlistAuthzPolicy
from egp_maf.state.clinician_context import ClinicianContext
from tests.support.authz_doubles import ClosedAuthzPolicy, OpenAuthzPolicy


def _make_ctx(clinician_id: str = "c1", roles: set[str] | None = None) -> ClinicianContext:
    return ClinicianContext(
        clinician_id=clinician_id,
        tenant_id="t1",
        roles=frozenset(roles or {"Clinician"}),
    )


def _write_allowlist(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


class TestNoAllowlistDeniesEveryone:
    def test_can_read_denies_when_no_file_configured(self) -> None:
        policy = AllowlistAuthzPolicy(allowlist_path=None)
        assert policy.can_read(_make_ctx(), "P001") is False

    def test_system_context_is_still_allowed(self) -> None:
        policy = AllowlistAuthzPolicy(allowlist_path=None)
        assert policy.can_read(ClinicianContext.system(), "P001") is True

    def test_enforce_read_raises(self) -> None:
        policy = AllowlistAuthzPolicy(allowlist_path=None)
        with pytest.raises(AccessDenied):
            policy.enforce_read(_make_ctx(), "P001")


class TestAllowlistFile:
    def test_missing_file_raises(self, tmp_path: Path) -> None:
        missing = tmp_path / "nope.json"
        with pytest.raises(ConfigurationError):
            AllowlistAuthzPolicy(allowlist_path=missing)

    def test_invalid_json_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "allow.json"
        path.write_text("{not valid json", encoding="utf-8")
        with pytest.raises(ConfigurationError):
            AllowlistAuthzPolicy(allowlist_path=path)

    def test_unknown_version_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "allow.json"
        _write_allowlist(path, {"version": 999, "clinicians": {}})
        with pytest.raises(ConfigurationError):
            AllowlistAuthzPolicy(allowlist_path=path)

    def test_allow_and_deny_paths(self, tmp_path: Path) -> None:
        path = tmp_path / "allow.json"
        _write_allowlist(
            path,
            {
                "version": 1,
                "clinicians": {
                    "c1": ["P001", "P002"],
                    "c2": ["P003"],
                },
                "admins": [],
            },
        )
        policy = AllowlistAuthzPolicy(allowlist_path=path)

        assert policy.can_read(_make_ctx("c1"), "P001") is True
        assert policy.can_read(_make_ctx("c1"), "P002") is True
        assert policy.can_read(_make_ctx("c1"), "P003") is False
        assert policy.can_read(_make_ctx("c2"), "P003") is True
        assert policy.can_read(_make_ctx("c999"), "P001") is False

    def test_admin_bypasses_patient_check(self, tmp_path: Path) -> None:
        path = tmp_path / "allow.json"
        _write_allowlist(
            path,
            {"version": 1, "clinicians": {}, "admins": ["adm1"]},
        )
        policy = AllowlistAuthzPolicy(allowlist_path=path)
        assert policy.can_read(_make_ctx("adm1"), "P-anywhere") is True

    def test_enforce_read_emits_typed_error(self, tmp_path: Path) -> None:
        path = tmp_path / "allow.json"
        _write_allowlist(
            path,
            {"version": 1, "clinicians": {}, "admins": []},
        )
        policy = AllowlistAuthzPolicy(allowlist_path=path)
        with pytest.raises(AccessDenied) as exc:
            policy.enforce_read(_make_ctx("c1"), "P001")
        assert exc.value.error_code == "access_denied"
        assert exc.value.http_status == 403


class TestHotReload:
    def test_reload_on_mtime_change(self, tmp_path: Path) -> None:
        path = tmp_path / "allow.json"
        _write_allowlist(
            path,
            {"version": 1, "clinicians": {"c1": ["P001"]}, "admins": []},
        )
        policy = AllowlistAuthzPolicy(allowlist_path=path)
        assert policy.can_read(_make_ctx("c1"), "P001") is True
        assert policy.can_read(_make_ctx("c1"), "P002") is False

        # Update the file. Must advance mtime — sleep 1s so a filesystem with
        # 1-second mtime resolution shows a difference.
        time.sleep(1.1)
        _write_allowlist(
            path,
            {"version": 1, "clinicians": {"c1": ["P001", "P002"]}, "admins": []},
        )
        assert policy.can_read(_make_ctx("c1"), "P002") is True


class TestOpenAndClosedPolicies:
    def test_open_allows_everything(self) -> None:
        p = OpenAuthzPolicy()
        assert p.can_read(_make_ctx(), "P001") is True
        p.enforce_read(_make_ctx(), "P001")  # does not raise

    def test_closed_denies_everything(self) -> None:
        p = ClosedAuthzPolicy()
        assert p.can_read(_make_ctx(), "P001") is False
        with pytest.raises(AccessDenied):
            p.enforce_read(_make_ctx(), "P001")
