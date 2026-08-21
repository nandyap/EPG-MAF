"""Operator tooling that ships inside the container image.

``scripts/`` is excluded by ``.dockerignore``, so anything an operator
needs to run against a live deployment lives here instead and is
available as ``python -m egp_maf.tools.<name>``.
"""
