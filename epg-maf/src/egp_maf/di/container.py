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

from egp_maf.config.settings import Settings, get_settings
from egp_maf.infrastructure.compass_client import LlmClientFactory
from egp_maf.infrastructure.cosmos_client import CosmosClientFactory
from egp_maf.infrastructure.db_pool import DbPoolFactory
from egp_maf.logging.setup import configure_logging, get_logger
from egp_maf.services.authz import AllowlistAuthzPolicy, AuthzPolicy
from egp_maf.services.prompt_service import PromptService
from egp_maf.services.provenance import ProvenanceService
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
    provenance_service = ProvenanceService()

    allowlist_path = (
        Path(resolved_settings.authz_allowlist_path)
        if resolved_settings.authz_allowlist_path
        else None
    )
    authz_policy: AuthzPolicy = AllowlistAuthzPolicy(allowlist_path)

    # Router LLMs — defaults are safe stubs; W05 replaces with real ones.
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
    workflow_runtime = WorkflowRuntime(
        settings=resolved_settings,
        chat_router_llm=resolved_chat_router,
        orch_router_llm=resolved_orch_router,
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
        workflow_runtime=workflow_runtime,
    )
