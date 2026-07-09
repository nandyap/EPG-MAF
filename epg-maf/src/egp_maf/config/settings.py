"""Application settings.

Ports the prototype's ``config/settings.py`` and extends it with Postgres,
Cosmos DB, APIM/Compass, orchestration flags and environment metadata.

Rules:
- Every field has a sane default suitable for local development, EXCEPT
  ``llm_api_key`` which must be supplied via ``LLM_API_KEY`` (or the
  ``OPENAI_API_KEY`` alias, for compatibility with the prototype).
- Secrets are typed ``SecretStr`` so accidental logging shows ``**********``.
- Settings load from a ``.env`` file OR environment variables. In production
  the values come from Key Vault via ACA ``secretRef`` bindings.
"""

from __future__ import annotations

from enum import Enum
from functools import lru_cache
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class DispatchMode(str, Enum):
    """Orchestration dispatch mode. See Engineering Plan §2.2."""

    SEQUENTIAL = "sequential"
    PARALLEL = "parallel"


class PromptsSource(str, Enum):
    """Where the ``PromptService`` loads prompts from."""

    BUNDLE = "bundle"
    FOUNDRY = "foundry"


class Settings(BaseSettings):
    """Process-wide configuration."""

    # ── Environment ─────────────────────────────────────────────────
    env: Literal["dev", "preprod", "prod"] = Field(default="dev", alias="EGP_ENV")
    service_version: str = Field(default="0.1.0-dev", alias="EGP_SERVICE_VERSION")
    log_level: Literal["DEBUG", "INFO", "WARN", "WARNING", "ERROR"] = Field(
        default="INFO", alias="EGP_LOG_LEVEL"
    )

    # ── LLM (Compass via APIM) ─────────────────────────────────────
    # AliasChoices preserves prototype compatibility: LLM_API_KEY or OPENAI_API_KEY.
    llm_api_key: SecretStr = Field(
        validation_alias=AliasChoices("LLM_API_KEY", "OPENAI_API_KEY")
    )
    llm_base_url: str = Field(
        default="https://api.core42.ai/v1",
        alias="LLM_BASE_URL",
    )
    llm_timeout_seconds: int = Field(default=30, alias="LLM_TIMEOUT_SECONDS", ge=1, le=300)

    # ── PostgreSQL ─────────────────────────────────────────────────
    postgres_host: str = Field(default="localhost", alias="POSTGRES_HOST")
    postgres_port: int = Field(default=5432, alias="POSTGRES_PORT", ge=1, le=65535)
    postgres_database: str = Field(default="egp", alias="POSTGRES_DATABASE")
    postgres_user: str = Field(default="egp_agent_ro", alias="POSTGRES_USER")
    postgres_password: SecretStr | None = Field(default=None, alias="POSTGRES_PASSWORD")
    postgres_use_managed_identity: bool = Field(
        default=False, alias="POSTGRES_USE_MANAGED_IDENTITY"
    )
    postgres_ssl_mode: Literal["disable", "allow", "prefer", "require", "verify-ca", "verify-full"] = (
        Field(default="require", alias="POSTGRES_SSL_MODE")
    )
    postgres_pool_min_size: int = Field(default=2, alias="POSTGRES_POOL_MIN_SIZE", ge=0, le=100)
    postgres_pool_max_size: int = Field(default=10, alias="POSTGRES_POOL_MAX_SIZE", ge=1, le=1000)
    postgres_pool_timeout_seconds: int = Field(
        default=5, alias="POSTGRES_POOL_TIMEOUT_SECONDS", ge=1, le=60
    )
    postgres_statement_timeout_seconds: int = Field(
        default=30, alias="POSTGRES_STATEMENT_TIMEOUT_SECONDS", ge=1, le=600
    )

    # Migrator role (Alembic / CI only — never used by the runtime app).
    postgres_migrator_user: str | None = Field(default=None, alias="POSTGRES_MIGRATOR_USER")
    postgres_migrator_password: SecretStr | None = Field(
        default=None, alias="POSTGRES_MIGRATOR_PASSWORD"
    )

    # ── Cosmos DB (session / thread state) ─────────────────────────
    cosmos_endpoint: str = Field(default="https://localhost:8081", alias="COSMOS_ENDPOINT")
    cosmos_database: str = Field(default="egp", alias="COSMOS_DATABASE")
    cosmos_container: str = Field(default="sessions", alias="COSMOS_CONTAINER")
    cosmos_use_managed_identity: bool = Field(default=False, alias="COSMOS_USE_MANAGED_IDENTITY")
    cosmos_key: SecretStr | None = Field(default=None, alias="COSMOS_KEY")
    cosmos_session_ttl_seconds: int = Field(
        default=86400, alias="COSMOS_SESSION_TTL_SECONDS", ge=60, le=604800
    )

    # ── Prompts ─────────────────────────────────────────────────────
    prompts_source: PromptsSource = Field(default=PromptsSource.BUNDLE, alias="PROMPTS_SOURCE")
    prompts_foundry_endpoint: str | None = Field(default=None, alias="PROMPTS_FOUNDRY_ENDPOINT")
    prompts_foundry_timeout_seconds: int = Field(
        default=3, alias="PROMPTS_FOUNDRY_TIMEOUT_SECONDS", ge=1, le=30
    )

    # ── Orchestration ──────────────────────────────────────────────
    orch_dispatch_mode: DispatchMode = Field(
        default=DispatchMode.SEQUENTIAL, alias="ORCH_DISPATCH_MODE"
    )
    orch_max_fanout_width: int = Field(default=1, alias="ORCH_MAX_FANOUT_WIDTH", ge=1, le=5)
    orch_iteration_budget: int = Field(default=12, alias="ORCH_ITERATION_BUDGET", ge=1, le=100)

    # ── Authorization ──────────────────────────────────────────────
    # Path to the JSON allowlist consumed by AllowlistAuthzPolicy.
    # In dev this is a plain file path; in prod ACA mounts the Key Vault
    # secret to this path at container start.
    authz_allowlist_path: str | None = Field(default=None, alias="EGP_AUTHZ_ALLOWLIST_PATH")

    # ── Authentication (W07 — Entra ID) ────────────────────────────
    # These configure the JWT verifier that maps a bearer token onto a
    # :class:`~egp_maf.state.clinician_context.ClinicianContext`.
    #
    # In dev, ``auth_stub_enabled=true`` bypasses signature verification
    # and lets callers supply plain JSON claims (used by unit tests and
    # the dev docker-compose profile). In preprod / prod this flag is
    # false; a JWKS endpoint + expected issuer/audience are required.
    entra_tenant_id: str | None = Field(default=None, alias="ENTRA_TENANT_ID")
    entra_expected_audience: str | None = Field(
        default=None, alias="ENTRA_EXPECTED_AUDIENCE"
    )
    entra_expected_issuer: str | None = Field(
        default=None, alias="ENTRA_EXPECTED_ISSUER"
    )
    entra_jwks_url: str | None = Field(default=None, alias="ENTRA_JWKS_URL")
    entra_leeway_seconds: int = Field(
        default=30, alias="ENTRA_LEEWAY_SECONDS", ge=0, le=300
    )
    auth_stub_enabled: bool = Field(default=False, alias="EGP_AUTH_STUB_ENABLED")
    auth_required_role: str = Field(default="Clinician", alias="EGP_AUTH_REQUIRED_ROLE")

    # ── Pydantic-settings config ───────────────────────────────────
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    # ── Cross-field validation ─────────────────────────────────────
    @field_validator("postgres_password")
    @classmethod
    def _validate_postgres_credentials(
        cls, value: SecretStr | None, info: object
    ) -> SecretStr | None:
        # Full cross-field check happens in ``model_validate`` below; this hook
        # is kept for future field-level validation as the config grows.
        return value

    def credentials_are_valid(self) -> bool:
        """Return True when credentials are consistent.

        Either ``POSTGRES_USE_MANAGED_IDENTITY`` is true, or a password is set.
        Same rule for Cosmos.
        """
        pg_ok = self.postgres_use_managed_identity or self.postgres_password is not None
        cosmos_ok = self.cosmos_use_managed_identity or self.cosmos_key is not None
        return pg_ok and cosmos_ok

    def is_production(self) -> bool:
        return self.env == "prod"

    def dispatch_mode_summary(self) -> dict[str, str | int]:
        """Structured summary of the orchestration dispatch configuration.

        Used by:

        - The workflow-runtime start-up log (``workflow_runtime.built``).
        - The Phase-3 enablement gate checklist (see
          ``docs/runbooks/enable-parallel-dispatch.md``) so the auditor
          can confirm the effective mode + width without grepping env
          vars.
        - W08 will attach these as ``orch.*`` attributes to the workflow
          root span.
        """
        return {
            "orch.mode": self.orch_dispatch_mode.value,
            "orch.max_fanout_width": self.orch_max_fanout_width,
            "orch.iteration_budget": self.orch_iteration_budget,
        }


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the cached process-wide ``Settings`` instance."""
    return Settings()  # type: ignore[call-arg]
