"""Cosmos DB for NoSQL async client factory.

The client is opened at startup and closed at shutdown by the DI container.
Consumers ``get_container(database, container)`` — the factory does not hold
a fixed container reference so it can serve multiple containers if needed
(the session container is the only one in Phase 1).

Authentication precedence (Design §19.6):
1. ``COSMOS_USE_MANAGED_IDENTITY=true`` — use ``DefaultAzureCredential``.
2. ``COSMOS_KEY`` set — use the account key (allowed for local emulator only
   in prod, this must be rejected by policy).
3. Otherwise raise :class:`ConfigurationError`.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from egp_maf.config.settings import Settings
from egp_maf.errors import ConfigurationError, CosmosUnavailable

if TYPE_CHECKING:  # pragma: no cover
    from azure.cosmos.aio import ContainerProxy, CosmosClient

_logger = logging.getLogger(__name__)


class CosmosClientFactory:
    """Constructs and lifecycle-manages the Cosmos async client."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client: "CosmosClient | None" = None
        self._credential: object | None = None  # DefaultAzureCredential (needs closing)

    async def open(self) -> None:
        """Open the client. Idempotent."""
        if self._client is not None:
            return

        from azure.cosmos.aio import CosmosClient  # type: ignore[import-untyped]

        s = self._settings
        try:
            if s.cosmos_use_managed_identity:
                from azure.identity.aio import (  # type: ignore[import-untyped]
                    DefaultAzureCredential,
                )

                self._credential = DefaultAzureCredential()
                self._client = CosmosClient(url=s.cosmos_endpoint, credential=self._credential)
            elif s.cosmos_key is not None:
                self._client = CosmosClient(
                    url=s.cosmos_endpoint,
                    credential=s.cosmos_key.get_secret_value(),
                )
            else:
                raise ConfigurationError(
                    "Cosmos credentials missing: set COSMOS_KEY or "
                    "COSMOS_USE_MANAGED_IDENTITY=true."
                )
        except ConfigurationError:
            raise
        except Exception as exc:  # pragma: no cover — exercised in integration
            raise CosmosUnavailable(
                f"Failed to open Cosmos client for {s.cosmos_endpoint}"
            ) from exc

    async def close(self) -> None:
        """Close the client and any owned credential. Idempotent."""
        if self._client is not None:
            await self._client.close()
            self._client = None
        if self._credential is not None:
            close = getattr(self._credential, "close", None)
            if callable(close):
                await close()
            self._credential = None

    # ── Access ───────────────────────────────────────────────────────
    @property
    def client(self) -> "CosmosClient":
        """Return the opened client."""
        if self._client is None:
            raise CosmosUnavailable(
                "Cosmos client has not been opened. Call CosmosClientFactory.open() first."
            )
        return self._client

    async def get_container(
        self,
        database: str | None = None,
        container: str | None = None,
    ) -> "ContainerProxy":
        """Return a container proxy. Defaults to the session container."""
        s = self._settings
        db_name = database or s.cosmos_database
        cont_name = container or s.cosmos_container
        db = self.client.get_database_client(db_name)
        return db.get_container_client(cont_name)
