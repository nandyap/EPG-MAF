"""Derive strict-JSON-Schema-safe variants of the extraction models.

OpenAI Structured Outputs (and Compass, which follows the same contract)
rejects any schema containing a free-form object::

    Invalid schema for response_format 'GenomicVariantsResultList':
    In context=('properties', 'tool_parameters'), 'additionalProperties'
    is required to be supplied and to be false.

In our result models the only free-form objects come from
:class:`~egp_maf.state.provenance.DBProvenance` — ``tool_parameters`` and
``source_row`` are both ``dict[str, Any]``, which cannot be expressed in
strict mode.

The LLM must never populate provenance anyway. It is constructed at query
time by the Repository (ADR-005) and attached to the extracted results
afterwards by
:func:`~egp_maf.agents.base.attach_provenance_to_results`. Asking the
model for it would be both impossible to validate and a correctness risk:
provenance is an audit record of what the database returned, not
something an LLM should author.

So for the extraction call we hand the model a variant of the schema with
every ``provenance`` field removed, then validate its reply back into the
real model — where ``provenance`` defaults to an empty list and is filled
in by the caller.

The prototype sidestepped this by using ``method="function_calling"``
(non-strict). ADR-021 flagged that MAF parity here needed verifying; this
module is that verification.
"""

from __future__ import annotations

from types import UnionType
from typing import Any, Union, get_args, get_origin

from pydantic import BaseModel, ConfigDict, create_model

# Fields the LLM must never author, because the database is their source
# of truth and a model copying them is a fabrication risk:
#
# - ``provenance``   — built at query time by the Repository (ADR-005) and
#                      attached afterwards by
#                      ``agents.base.attach_provenance_to_results``.
# - ``raw_annotations`` — the catch-all from ``parse_annotations_json``
#                      (ADR-006). Python parses it deterministically; the
#                      LLM's job is to *interpret* the typed fields, never
#                      to reproduce the raw blob. The authoritative copy
#                      survives in ``DBProvenance.source_row``.
#
# Both are also ``dict[str, Any]``, which strict mode cannot express — so
# excluding them is what makes the schema valid as well as what makes it
# correct.
#
# - ``interpretation_model`` / ``summary_model`` — these name *which model*
#   wrote the neighbouring prose. Only the process knows that;
#   ``SpecialistBase._attribute_model`` stamps it from settings. Leaving
#   them in the schema let the model answer the question about itself, and
#   it did: a family-history interpretation shipped labelled ``manual``
#   (observed 2026-08-26), i.e. model-generated text presented as
#   human-authored, inside the audit panel. ``_attribute_model`` could not
#   correct it because it only writes when the field is still ``None``, so
#   the model's answer won. Nothing failed — the attribution was simply
#   false. Stripped here, the field arrives ``None`` and the process fills
#   it in.
_EXCLUDED_FIELDS = frozenset(
    {
        "provenance",
        "raw_annotations",
        "interpretation_model",
        "summary_model",
    }
)

# Cache: one derived model per source model, keyed by the class itself.
_CACHE: dict[type[BaseModel], type[BaseModel]] = {}


def strict_extraction_schema(model: type[BaseModel]) -> type[BaseModel]:
    """Return a provenance-free, strict-mode-safe variant of ``model``.

    Nested models are rebuilt recursively. Models with nothing to strip
    are still rebuilt so ``extra='forbid'`` (which emits
    ``additionalProperties: false``) applies consistently throughout the
    tree.
    """
    cached = _CACHE.get(model)
    if cached is not None:
        return cached

    fields: dict[str, Any] = {}
    for name, field in model.model_fields.items():
        if name in _EXCLUDED_FIELDS:
            continue
        fields[name] = (_rewrite(field.annotation), field)

    derived = create_model(  # type: ignore[call-overload]
        f"{model.__name__}Extraction",
        __config__=ConfigDict(extra="forbid"),
        **fields,
    )
    derived.__doc__ = model.__doc__
    _CACHE[model] = derived
    return derived


def _rewrite(annotation: Any) -> Any:
    """Recursively replace nested models with their derived variants."""
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return strict_extraction_schema(annotation)

    origin = get_origin(annotation)
    if origin is None:
        return annotation

    args = get_args(annotation)
    if not args:
        return annotation

    rewritten = tuple(_rewrite(a) for a in args)
    if rewritten == args:
        return annotation

    # Unions need rebuilding through ``typing.Union``: both ``X | None``
    # (``types.UnionType``) and ``Optional[X]`` report an origin that is
    # not subscriptable, so the generic path below would silently return
    # the original annotation and leave the nested model unrewritten.
    if origin is Union or origin is UnionType:
        return Union[rewritten]  # noqa: UP007

    try:
        return annotation.copy_with(rewritten)  # typing generics
    except AttributeError:
        try:
            return origin[rewritten]
        except TypeError:  # pragma: no cover — exotic generics
            return annotation
