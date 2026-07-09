"""Infrastructure adapters — connection pools and external client factories.

- :mod:`db_pool` — async psycopg 3 pool factory + open/close helpers.
- :mod:`compass_client` — MAF ``OpenAIChatClient`` factory per agent.
- :mod:`cosmos_client` — Cosmos DB async client factory.
"""

from egp_maf.infrastructure.compass_client import LlmClientFactory
from egp_maf.infrastructure.cosmos_client import CosmosClientFactory
from egp_maf.infrastructure.db_pool import DbPoolFactory

__all__ = ["CosmosClientFactory", "DbPoolFactory", "LlmClientFactory"]
