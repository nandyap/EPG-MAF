"""Integration tests.

Marked ``integration`` — they require external services running locally:
- Postgres (``docker run --rm -p 5432:5432 -e POSTGRES_PASSWORD=egp postgres:16``)
- Cosmos emulator (``docker run --rm -p 8081:8081 mcr.microsoft.com/cosmosdb/linux/azure-cosmos-emulator``)

Run with:

    pytest -m integration
"""
