"""Hand-rolled dependency-injection container.

Design rules (Engineering Plan §3.4):
- No global singletons except ``Settings`` itself (which is cached).
- Explicit constructor injection — everything a service needs is passed in.
- Async lifecycle — resources that need opening/closing use the container's
  startup/shutdown methods.

The container is intentionally simple. Bindings live in :func:`build_container`
and every attribute is typed for IDE autocompletion.
"""

from __future__ import annotations

from pathlib import Path

from egp_maf.agents.registry import (
    SpecialistRegistry,
    build_specialist_registry,
)
from egp_maf.auth.audit import AuditEventEmitter, LoggingAuditSink
from egp_maf.auth.authenticator import Authenticator, build_authenticator
from egp_maf.config.settings import Settings, get_settings
from egp_maf.telemetry import (
    MetricEmitter,
    NullMetricEmitter,
    OtelMetricEmitter,
    TelemetryProvider,
    build_telemetry_provider,
    get_current_trace_and_span_ids,
)
from egp_maf.infrastructure.compass_client import LlmClientFactory
from egp_maf.infrastructure.cosmos_client import CosmosClientFactory
from egp_maf.infrastructure.db_pool import DbPoolFactory
from egp_maf.logging.setup import configure_logging, get_logger
from egp_maf.services.authz import AllowlistAuthzPolicy, AuthzPolicy
from egp_maf.services.prompt_service import PromptService
from egp_maf.services.provenance import ProvenanceService
from egp_maf.services.repositories import (
    FamilyHistoryRepository,
    GenomicVariantsRepository,
    PGXRepository,
    PhenotypeRepository,
    PRSRepository,
)
from egp_maf.services.thread_state import ThreadStateProvider
from egp_maf.workflow.decisions import ChatRouterDecision, SpecialistDispatchSet
from egp_maf.workflow.router_llm import (
    OrchRouterLlm,
    RouterLlm,
    StubOrchRouterLlm,
    StubRouterLlm,
)
from egp_maf.workflow.runtime import WorkflowRuntime

_logger = get_logger(__name__)


class Container:
    """Application-wide dependency container.

    Attributes are singletons. Construct via :func:`build_container` — never
    directly.

    Lifecycle:

        container = build_container()
        await container.startup()
        try:
            ...
        finally:
            await container.shutdown()
    """

    def __init__(
        self,
        *,
        settings: Settings,
        db_pool_factory: DbPoolFactory,
        cosmos_client_factory: CosmosClientFactory,
        llm_client_factory: LlmClientFactory,
        prompt_service: PromptService,
        thread_state_provider: ThreadStateProvider,
        provenance_service: ProvenanceService,
        authz_policy: AuthzPolicy,
        audit_emitter: AuditEventEmitter,
        authenticator: Authenticator,
        telemetry_provider: TelemetryProvider,
        metric_emitter: MetricEmitter,
        specialist_registry: SpecialistRegistry,
        workflow_runtime: WorkflowRuntime,
    ) -> None:
        self.settings = settings
        self.db_pool_factory = db_pool_factory
        self.cosmos_client_factory = cosmos_client_factory
        self.llm_client_factory = llm_client_factory
        self.prompt_service = prompt_service
        self.thread_state_provider = thread_state_provider
        self.provenance_service = provenance_service
        self.authz_policy = authz_policy
        self.audit_emitter = audit_emitter
        self.authenticator = authenticator
        self.telemetry_provider = telemetry_provider
        self.metric_emitter = metric_emitter
        self.specialist_registry = specialist_registry
        self.workflow_runtime = workflow_runtime

        self._started: bool = False

    # ── Lifecycle ────────────────────────────────────────────────────
    async def startup(self) -> None:
        """Open all resources. Idempotent.

        Order matters:
        1. Cosmos client — cheap to construct, needed by ThreadStateProvider.
        2. Postgres pool — takes ~2s to warm ``min_size`` connections.
        3. PromptService — Foundry fetch has a bounded timeout; falls back
           to bundle on failure.
        """
        if self._started:
            return

        _logger.info("container.startup.begin", env=self.settings.env)

        try:
            await self.cosmos_client_factory.open()
            _logger.info("container.startup.cosmos_open")

            await self.db_pool_factory.open()
            _logger.info(
                "container.startup.db_pool_open",
                min_size=self.settings.postgres_pool_min_size,
                max_size=self.settings.postgres_pool_max_size,
            )

            await self.prompt_service.warm()
            _logger.info(
                "container.startup.prompts_warm",
                fallback_count=self.prompt_service.fallback_count,
                source=self.settings.prompts_source.value,
            )

            self._started = True
            _logger.info("container.startup.complete")
        except Exception:
            _logger.exception("container.startup.failed")
            # Best-effort partial shutdown so we don't leak handles.
            await self.shutdown()
            raise

    async def shutdown(self) -> None:
        """Close all resources in reverse dependency order. Idempotent."""
        _logger.info("container.shutdown.begin")
        # Postgres and Cosmos own network sockets — close them first.
        try:
            await self.db_pool_factory.close()
        except Exception:  # noqa: BLE001 — never fail shutdown
            _logger.exception("container.shutdown.db_pool_failed")
        try:
            await self.cosmos_client_factory.close()
        except Exception:  # noqa: BLE001
            _logger.exception("container.shutdown.cosmos_failed")
        self._started = False
        _logger.info("container.shutdown.complete")

    # ── Introspection ────────────────────────────────────────────────
    @property
    def is_started(self) -> bool:
        return self._started


def build_container(
    settings: Settings | None = None,
    *,
    chat_router_llm: RouterLlm | None = None,
    orch_router_llm: OrchRouterLlm | None = None,
) -> Container:
    """Wire the application container.

    Bindings are declared here — one place to trace every dependency.

    The two router-LLM keyword arguments are the seam for W05: the caller
    (production main / tests) passes real Compass-backed implementations.
    When omitted, the container is wired with harmless stubs so that
    integration tests (and W04 smoke runs) can exercise the workflow
    without an LLM. The stubs emit a single ``end`` decision, which
    means the orchestration loop exits immediately without any specialist
    dispatch — useful as a health check, not as a workflow simulation.
    """
    resolved_settings = settings or get_settings()
    configure_logging(resolved_settings)

    db_pool_factory = DbPoolFactory(resolved_settings)
    cosmos_client_factory = CosmosClientFactory(resolved_settings)
    llm_client_factory = LlmClientFactory(resolved_settings)
    prompt_service = PromptService(resolved_settings)
    thread_state_provider = ThreadStateProvider(cosmos_client_factory, resolved_settings)

    # W08: Telemetry bootstraps early so every downstream constructor
    # that wants a tracer/meter gets a live one. The provider is not
    # installed as the OTEL global yet; ``install_globally`` runs on
    # startup so unit tests can build their own without polluting the
    # process-wide state.
    telemetry_provider = build_telemetry_provider(resolved_settings)
    metric_emitter: MetricEmitter = OtelMetricEmitter(
        telemetry_provider.meter_provider.get_meter("egp_maf")
    )

    # W08: :class:`ProvenanceService` now populates ``trace_id`` /
    # ``span_id`` on every :class:`DBProvenance` when a span is active
    # (Design §20.6). The context provider is non-throwing and safe to
    # call from any thread.
    provenance_service = ProvenanceService(
        otel_context_provider=get_current_trace_and_span_ids,
    )

    allowlist_path = (
        Path(resolved_settings.authz_allowlist_path)
        if resolved_settings.authz_allowlist_path
        else None
    )
    # W07: shared audit emitter fans out authz.granted / authz.denied /
    # auth.* events to the ``egp_maf.audit`` logger (routed to LAW in
    # prod).
    audit_emitter = AuditEventEmitter(sink=LoggingAuditSink())
    authz_policy: AuthzPolicy = AllowlistAuthzPolicy(
        allowlist_path, audit=audit_emitter
    )

    # W07: Authenticator maps a bearer token onto a ClinicianContext.
    # ``build_authenticator`` picks the stub when EGP_AUTH_STUB_ENABLED is
    # true (dev + tests) or the real Entra-backed one otherwise.
    authenticator: Authenticator = build_authenticator(
        resolved_settings, audit=audit_emitter
    )

    # Router LLMs — defaults are safe stubs; production supplies real ones.
    resolved_chat_router: RouterLlm = chat_router_llm or StubRouterLlm(
        ChatRouterDecision(
            needs_clinical_data=False,
            reason="default stub — no clinical data needed",
            reset_agents=[],
        )
    )
    resolved_orch_router: OrchRouterLlm = orch_router_llm or StubOrchRouterLlm(
        [SpecialistDispatchSet(specialists=[], reason="default stub — immediate end")]
    )

    # Specialists (W05). Each is bound to the shared Repository +
    # ProvenanceService and to a MAF-backed :class:`SpecialistLlm`.
    # ``prompt_service.warm()`` must have been called before the
    # container is used; ``build_specialist_registry`` accesses prompts
    # lazily.
    prs_repo = PRSRepository(
        pool_factory=db_pool_factory,
        authz=authz_policy,
        provenance=provenance_service,
    )
    genomic_variants_repo = GenomicVariantsRepository(
        pool_factory=db_pool_factory,
        authz=authz_policy,
        provenance=provenance_service,
    )
    family_history_repo = FamilyHistoryRepository(
        pool_factory=db_pool_factory,
        authz=authz_policy,
        provenance=provenance_service,
    )
    pgx_repo = PGXRepository(
        pool_factory=db_pool_factory,
        authz=authz_policy,
        provenance=provenance_service,
    )
    phenotype_repo = PhenotypeRepository(
        pool_factory=db_pool_factory,
        authz=authz_policy,
        provenance=provenance_service,
    )
    specialist_registry = build_specialist_registry(
        prs_repo=prs_repo,
        genomic_variants_repo=genomic_variants_repo,
        family_history_repo=family_history_repo,
        pgx_repo=pgx_repo,
        phenotype_repo=phenotype_repo,
        llm_client_factory=llm_client_factory,
        prompt_service=prompt_service,
        provenance_service=provenance_service,
    )

    workflow_runtime = WorkflowRuntime(
        settings=resolved_settings,
        chat_router_llm=resolved_chat_router,
        orch_router_llm=resolved_orch_router,
        specialist_registry=specialist_registry,
    )

    return Container(
        settings=resolved_settings,
        db_pool_factory=db_pool_factory,
        cosmos_client_factory=cosmos_client_factory,
        llm_client_factory=llm_client_factory,
        prompt_service=prompt_service,
        thread_state_provider=thread_state_provider,
        provenance_service=provenance_service,
        authz_policy=authz_policy,
        audit_emitter=audit_emitter,
        authenticator=authenticator,
        telemetry_provider=telemetry_provider,
        metric_emitter=metric_emitter,
        specialist_registry=specialist_registry,
        workflow_runtime=workflow_runtime,
    )
