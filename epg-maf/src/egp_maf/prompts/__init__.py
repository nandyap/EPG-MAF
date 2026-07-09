"""Prompt subsystem — bundled prompts + loader.

The runtime :class:`~egp_maf.services.prompt_service.PromptService` lives in
``services/`` because it is a lifecycle-managed service. This package
contains only the static bundle.
"""

from egp_maf.prompts.bundle import KNOWN_PROMPTS, PROMPT_BUNDLE, load_bundle

__all__ = ["KNOWN_PROMPTS", "PROMPT_BUNDLE", "load_bundle"]
