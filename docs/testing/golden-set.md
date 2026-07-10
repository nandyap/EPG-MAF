# Golden question set

> Delivered by **W10 (Testing, Evaluation & Load)** — F12.1.
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
| `id` | str | Unique across the whole set. Prefixed by domain + a shortlabel (`prs.001.happy_path`). |
| `domain` | str | One of `prs`, `genomic_variants`, `pgx`, `phenotype`, `family_history`, `multi`. |
| `question` | str | The clinician's plain-text question. |
| `patient_id` | str | The seeded patient the question is asked against. |
| `expected_tool_calls` | list[`GoldenToolCall`] | Permutation-tolerant expected tool invocations. Each carries `tool_name`, `tool_parameters`, optional `depends_on`. |
| `expected_output_keys` | list[str] | Dotted-path keys the final slot payload must carry (`output`, `output.results`, …). Values not compared here. |
| `tags` | list[str] | `happy_path`, `edge_case`, `empty_result`, `privacy`, `multi_domain`, `dispatch_mode_parity`, `wide_fanout`, `external`. |
| `bix_reviewed` | bool | BIX SME sign-off flag. Seed items ship `false`; approvals land in a separate PR. |
| `bix_reviewer` / `bix_review_date` | str | Set when `bix_reviewed=true`. |

## 3. Coverage

The bundled seed set carries 8 items covering:

- Every domain × happy path (5).
- Empty-result edge case (`prs.002.empty`).
- Privacy case that hits the family-history privacy strip
  (`fh.001.privacy_strip`).
- Two multi-domain items pinning dispatch-mode parity
  (`multi.001.prs_and_gv`, `multi.002.all_domains`).

Target for **BIX-signed-off set** is 30–50 items — the seed set is the
scaffolding; BIX curation lands in a follow-up PR that flips
`bix_reviewed` to `true` per item.

## 4. Loading

```python
from egp_maf.evals import load_golden_set

# Bundled only:
items = load_golden_set()

# Bundled + private extras (BIX-curated large set):
items = load_golden_set(external_path=Path("/data/egp-golden-private/"))

# External only (unit tests):
items = load_golden_set(
    external_path=tmp_path, include_bundled=False
)
```

Duplicate ids across bundled + external raise ``ValueError`` — every
item is unique end-to-end.

## 5. Scoring

Two scorers evaluate each item:

- :class:`ToolCallScorer` — deterministic. Set-similarity over
  expected vs. actual `tool_name` + parameter superset check.
  ``depends_on`` enforces ordering only where it matters. Extras
  are logged but do not fail unless ``strict_extras=True``.
- :class:`InterpretationJudgeScorer` — LLM-as-judge over the
  natural-language interpretation. W10 ships :class:`StubJudge`
  (deterministic needle-based); Foundry Evaluations (W11) wires the
  real judge.

Both return the shared :class:`ScorerResult` envelope
(`passed`, `score`, `reason`).

## 6. Adding an item

1. Draft the item under `src/egp_maf/evals/golden_set/<domain>.json`
   (append to `seed.json` or add a new file — loader unions all
   `*.json` files it finds).
2. Every field must satisfy `GoldenItem.model_validate` — run the
   unit test `test_golden.py` to confirm.
3. Send the PR to BIX for review. On approval, set
   ``bix_reviewed: true`` + reviewer + date in a follow-up PR.
4. If the item pins a new tool call, add the tool name to the domain
   specialist's `_TOOL_SOURCE_TABLE` if it isn't already there
   (so provenance attaches correctly).

## 7. See also

- Solution Design §27 (test strategy) + §27.2 (golden set)
- Engineering Plan §E12 (F12.1)
- [`evals/golden.py`](../../epg-maf/src/egp_maf/evals/golden.py)
- [`evals/scorers.py`](../../epg-maf/src/egp_maf/evals/scorers.py)
- Foundry Evaluations wiring (W11 — Cutover)
