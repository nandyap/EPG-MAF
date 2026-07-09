"""Dependency injection container.

Hand-rolled to avoid a framework dependency. The container:

- Owns application-wide singletons (:class:`Settings`, factories, services).
- Manages an async ``startup`` / ``shutdown`` lifecycle for resources that
  need to open (Postgres pool, Cosmos client) and warm (PromptService).
- Resolves dependencies by attribute access — no runtime magic; every
  binding is declared explicitly in :meth:`Container.build`.

The container is deliberately *not* auto-wiring or reflective. Everything
is explicit so a reader can trace every dependency by ``grep``.
"""

from egp_maf.di.container import Container, build_container

__all__ = ["Container", "build_container"]
