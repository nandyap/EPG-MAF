"""Structured logging configuration."""

from egp_maf.logging.setup import configure_logging, get_logger

__all__ = ["configure_logging", "get_logger"]

# NOTE: ``egp_maf.logging.flow_trace`` is deliberately NOT imported here.
# It imports ``get_logger`` from this module, so re-exporting it would
# create a circular import at package init.
