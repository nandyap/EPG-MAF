"""Tests for :mod:`egp_maf.auth.claims`."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from egp_maf.auth.claims import (
    ClaimsMappingError,
    ClinicianTokenClaims,
    claims_to_context,
    decode_token_bytes_to_claims,
)
from egp_maf.state.clinician_context import ClinicianContext

pytestmark = pytest.mark.unit


class TestDecodeTokenBytesToClaims:
    def test_happy_path(self) -> None:
        raw = {
            "oid": "clinician-1",
            "tid": "tenant-1",
            "roles": ["Clinician"],
            "exp": 1_800_000_000,
            "iss": "https://sts.windows.net/tenant/",
            "aud": "api://egp",
        }
        claims = decode_token_bytes_to_claims(raw)
        assert claims.oid == "clinician-1"
        assert claims.tid == "tenant-1"
        assert claims.roles == ["Clinician"]
        assert claims.exp == 1_800_000_000
        assert claims.raw["iss"] == "https://sts.windows.net/tenant/"

    def test_missing_optional_fields_ok(self) -> None:
        claims = decode_token_bytes_to_claims({"oid": "c", "tid": "t"})
        assert claims.roles == []
        assert claims.exp is None

    def test_missing_required_oid_raises(self) -> None:
        with pytest.raises(ClaimsMappingError):
            decode_token_bytes_to_claims({"tid": "t"})

    def test_missing_required_tid_raises(self) -> None:
        with pytest.raises(ClaimsMappingError):
            decode_token_bytes_to_claims({"oid": "c"})


class TestClaimsToContext:
    def test_populates_all_fields(self) -> None:
        claims = ClinicianTokenClaims(
            oid="c-1", tid="t-1", roles=["Clinician"], exp=1_800_000_000
        )
        ctx = claims_to_context(claims)
        assert isinstance(ctx, ClinicianContext)
        assert ctx.clinician_id == "c-1"
        assert ctx.tenant_id == "t-1"
        assert ctx.roles == frozenset({"Clinician"})
        assert ctx.token_expires_at == datetime.fromtimestamp(
            1_800_000_000, tz=timezone.utc
        )

    def test_null_exp_ok(self) -> None:
        claims = ClinicianTokenClaims(oid="c", tid="t", roles=["Clinician"])
        ctx = claims_to_context(claims)
        assert ctx.token_expires_at is None

    def test_malformed_exp_raises(self) -> None:
        # Extremely large value that OSError-fires on Windows.
        claims = ClinicianTokenClaims(
            oid="c", tid="t", roles=["Clinician"], exp=10**18
        )
        with pytest.raises(ClaimsMappingError):
            claims_to_context(claims)
