# PHI-safety CI — F12.7

> Delivered by **W10 (Testing, Evaluation & Load)**.
> Applies to code under `epg-maf/src/egp_maf/evals/phi_detector.py`
> and the unit test in
> `epg-maf/tests/unit/evals/test_phi_detector.py`.

## 1. Two layers of defence

W08 delivered the **runtime** guard:
:func:`egp_maf.telemetry.phi_safe.safe_set_attribute` refuses to
attach any name in :data:`FORBIDDEN_ATTRIBUTES` to a span.

W10 adds the **CI-gate** guard:
:func:`egp_maf.evals.phi_detector.detect_phi_in_export` scans an
arbitrary exported blob (log line, span-JSON dump, response body) for
the same forbidden names. Findings fail the build.

Together they cover both the *emit* path (W08) and the *export* path
(W10). A developer who bypasses `safe_set_attribute` still gets
caught before the exported artefact reaches an ops workspace.

## 2. Detector contract

```python
from egp_maf.evals import detect_phi_in_export

result = detect_phi_in_export(blob)
result.raise_if_findings()   # AssertionError on any hit
```

- Grep-style: one regex compiled once from
  :data:`FORBIDDEN_ATTRIBUTES`; longest alternative matches first so
  ``messages.content`` beats ``message.content``.
- Callers can override the forbidden set (`forbidden=[...]`) for
  bespoke lists.
- Each finding carries the attribute name + a context window
  (default 40 chars) so the CI job can point developers at the leak.

## 3. Scope

**In scope for the detector:**

- Log lines exported from `logging.setup`.
- Span attributes JSON dumped from the OTEL in-memory exporter after
  running the golden set.
- Client-facing response bodies produced by
  :func:`egp_maf.resilience.format_error_response`.

**Out of scope (by design):**

- Internal Pydantic models like :class:`DBProvenance` whose
  ``source_row`` field IS the row body (post-hashing) — the record
  itself is the audit trail. It is stored in Cosmos, never exported
  to spans / logs.

## 4. CI wiring

The `.github/workflows/phi.yml` job (lands with W11) runs:

```yaml
- run: python -m pytest -m "not integration and not chaos" -q
  # includes tests/unit/evals which covers both the detector unit
  # tests AND the runtime hygiene checks over representative exports.
```

And in a separate step:

```yaml
- run: |
    python -c "
    from pathlib import Path
    from egp_maf.evals import detect_phi_in_export
    for path in Path('logs').glob('*.jsonl'):
        blob = path.read_text()
        detect_phi_in_export(blob).raise_if_findings()
    "
```

## 5. Adding a new forbidden name

- Add to :data:`FORBIDDEN_ATTRIBUTES` in
  [`telemetry/attributes.py`](../../epg-maf/src/egp_maf/telemetry/attributes.py).
- The detector picks it up automatically (regex rebuilt at import).
- Update W08's spans doc so dashboards know the new name is banned.

## 6. See also

- W08 PHI-safety: [`docs/observability/spans.md`](../observability/spans.md)
- Engineering Plan §E12 (F12.7)
- Solution Design §10.4 (family-history privacy) + §27.6 (PHI CI)
