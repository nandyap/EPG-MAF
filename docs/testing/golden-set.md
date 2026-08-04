# Golden question set

> Delivered by **W10 (Testing, Evaluation & Load)** — F12.1.
> Extended by **Slice 3** (scope guardrail items) and **Slice 4** (full
> 43-item PDF translation + substring scorers + harness).
> Applies to code under `epg-maf/src/egp_maf/evals/golden.py` and the
> bundled JSON in `epg-maf/src/egp_maf/evals/golden_set/`.

## 1. Purpose

The golden set is the source-of-truth for regression + pre-release
evaluation. Every clinician-visible answer path is exercised by at
least one item; every deploy runs the whole set through Foundry
Evaluations (F12.4) and a failing item blocks prod promotion.

## 2. Item schema

Each item is a :class:`GoldenItem` (Pydantic model, `extra="forbid"`):

| Field | Type | Purpose |
|---|---|---|
| `id` | str | Unique across the whole set. `golden.{g,s,r}<n>.<shortlabel>` for the PDF-derived items. |
| `domain` | str | One of `prs`, `genomic_variants`, `pgx`, `phenotype`, `family_history`, `multi`, `scope_guard`. |
| `question` | str | The clinician's plain-text question — verbatim from the PDF where applicable. |
| `patient_id` | str | The seeded patient the question is asked against. |
| `expected_tool_calls` | list[`GoldenToolCall`] | Permutation-tolerant expected tool invocations. |
| `expected_output_keys` | list[str] | Dotted-path keys the final slot payload must carry. |
| `expected_refusal_substrings` | list[str] | **Slice 3.** Case-insensitive substrings the reply MUST contain (for `scope_guard` refusal items). |
| `expected_fact_substrings` | list[str] | **Slice 4.** Case-insensitive substrings the reply MUST contain (for content items). |
| `forbidden_substrings` | list[str] | **Slice 4.** Case-**sensitive** substrings the reply MUST NOT contain. Zero-tolerance; used for PHI. |
| `expected_fail_reason` | str \| None | **Slice 4.** When set, a failing content scorer is treated as expected-fail (typically `awaiting-compass`). |
| `tags` | list[str] | Controlled vocabulary — see `test_golden_shape.py::_ALLOWED_TAGS`. |
| `bix_reviewed` | bool | BIX SME sign-off flag. Every item ships `false` until BIX signs. |

## 3. Coverage (post-Slice 4)

The bundled set carries **55 items** across 7 files:

| File | Items | PDF section |
|---|---|---|
| `seed.json` | 8 | pre-existing dev seed |
| `scope_guard.json` | 9 | Guardrail G1–G9 |
| `prs_scenarios.json` | 4 | Golden S1–S4 |
| `variant_scenarios.json` | 3 | Golden S5–S7 |
| `family_history_scenarios.json` | 3 | Golden S8–S10 |
| `pgx_scenarios.json` | 4 | Golden S11–S14 |
| `random_patient.json` | 24 | Random R1–R24 |

Every item from the customer's `docs/golden_dataset_prompts.pdf`
(G1–G9 + S1–S14 + R1–R24 = **47 PDF items**) is covered, verified
by `test_golden_shape.py::test_all_pdf_golden_items_present`.

## 4. Loading

```python
from egp_maf.evals import load_golden_set

# Bundled only (default):
items = load_golden_set()

# Bundled + private extras (larger BIX-curated set):
items = load_golden_set(external_path=Path("/data/egp-golden-private/"))
```

Duplicate ids across bundled + external raise ``ValueError`` — every
item is unique end-to-end.

## 5. Scoring

Slice 4 ships **four** deterministic scorers alongside the LLM-judge:

| Scorer | Purpose | Runs today? |
|---|---|---|
| :class:`ToolCallScorer` | Set-similarity over expected vs. actual `tool_name` + params. | Yes, when the item lists expected tools. |
| :class:`RefusalShapeScorer` | Refusal-item assertions: expected substrings present, `agents_completed` empty; and cohort-allowed assertions: no refusal wording leaked. | **Yes — Gaps 1 & 2 measurable today.** |
| :class:`FactSubstringScorer` | Case-insensitive presence of every `expected_fact_substrings` entry. Partial-credit score. | Content items pass once Compass key arrives. |
| :class:`ForbiddenSubstringScorer` | Zero-tolerance case-**sensitive** check for PHI leakage. | **Yes for shape** — real PHI check runs once Compass produces narratives. |
| :class:`InterpretationJudgeScorer` | LLM-as-judge over the natural-language interpretation. | Deferred until Foundry access (W11 wiring). |

All return the shared :class:`ScorerResult` envelope
(`passed`, `score`, `reason`).

## 6. Expected-fail policy

Items whose passing requires the real Compass LLM to synthesise a
narrative are tagged `awaiting-compass` and carry an
`expected_fail_reason` string. The harness (`evals/harness.py`) treats
a failing content scorer on such items as an **expected fail** rather
than a red-bar failure. This keeps CI green today while making it
obvious what will start passing once the LLM key arrives.

Shape scorers (`RefusalShapeScorer`) still run — Gap 1 and Gap 2 are
fully green today.

## 7. Running the harness

```python
from fastapi.testclient import TestClient
from egp_maf.api import create_app
from egp_maf.di.container import build_container
from egp_maf.evals import load_golden_set
from egp_maf.evals.harness import run_golden_item

container = build_container()
client = TestClient(create_app(container))
for item in load_golden_set():
    result = run_golden_item(client, item, token=my_bearer)
    print(f"{item.id}: passed={result.passed} expected_fail={result.expected_fail}")
```

## 8. Adding an item

1. Drop it into an existing `<category>.json` or add a new file — the
   loader unions all `*.json` files it finds.
2. Every field must satisfy `GoldenItem.model_validate`.
3. Any new tag must be added to `_ALLOWED_TAGS` in
   `tests/unit/evals/test_golden_shape.py`.
4. Send the PR to BIX for review. On approval, flip `bix_reviewed`
   to `true` + set `bix_reviewer` + `bix_review_date` in a follow-up
   PR.

## 9. See also

- Solution Design §27 (test strategy) + §27.2 (golden set)
- Engineering Plan §E12 (F12.1)
- [`evals/golden.py`](../../epg-maf/src/egp_maf/evals/golden.py)
- [`evals/scorers.py`](../../epg-maf/src/egp_maf/evals/scorers.py)
- [`evals/harness.py`](../../epg-maf/src/egp_maf/evals/harness.py)
- [`security/scope_guard.py`](../../epg-maf/src/egp_maf/security/scope_guard.py) (Slice 3 — Gap 1 defence)
- Foundry Evaluations wiring (W11 — Cutover)
