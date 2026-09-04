# TDF Accuracy-Per-Token Eval: Pre-registration

## Post-hoc additions (disclosed)

- **`hybrid` arm added after unblinding** (0.2.1): per-block Markdown/TDF
  arbitration. Registered in `eval/formats/encode.py` so its cells can be
  collected by the standard runner, but it has **no rows in the first run's
  results** and its future numbers are **exploratory** — they are not part
  of the decision rules below, which were applied to the original eight arms
  only. The pre-registered verdict stands as published.
- **`tdf_nocaret0` arm added after unblinding** (Phase-5 remediation
  candidate): identical to `tdf_full` except caret-elision never touches
  column 0 (the row anchor). Motivated by the failure analysis — the dominant
  loss cluster (row_association : encoded_away, n=30) traces to lookup keys
  caret-collapsed out of the wire. Exploratory like `hybrid`; a positive
  result must additionally survive the token-cost comparison (the anchor
  column is paid for literally).
- **`tdf_grouped` arm added after both the v1 and v2 unblinded runs**
  (mission section 4, Phase 19): a repeated column-0 value is stated once
  per contiguous run via a `!N`/`@` group header (`docs/SPEC.md`) instead of
  per-row repetition or caret-elision, whenever `tdf/tree.py`'s token
  economics say it's net positive. Exploratory like `hybrid`/`tdf_nocaret0`
  — **no accuracy data exists for it yet at all** (not run in v1 or v2); any
  future numbers are not part of the decision rules below.
  **Registered but currently untestable on this corpus**: verified that
  grouping fires on NONE of the 5 existing documents. `co2_data` looked
  like the natural fit (its raw data repeats a country across many
  consecutive rows, matching the mission's own worked example), but
  `eval/corpus/perturb.py` trims it to the first 100 rows, which for a
  country-then-year-sorted dataset means every row is "Afghanistan" — a
  single distinct value, i.e. a whole-table constant that `!F` already
  claims before grouping detection ever runs (correctly: `!F` is strictly
  cheaper than a group header for a column with only one value). The other
  4 documents have no naturally repeating leading-entity column at all.
  Getting real accuracy data for this arm requires either a new corpus
  document with genuine multi-entity contiguous-row structure, or a
  reshaped (not just re-trimmed) view of `co2_data` that preserves several
  countries -- not done here, since `eval/corpus/expand.py`'s own policy
  is that existing perturbed inputs are never regenerated, to preserve
  comparability with the v1/v2 benchmark inputs.

## Model notes (read before interpreting any `seed` in the raw data)

- **`openai/gpt-oss-120b` reached end-of-life on its NVIDIA API endpoint at
  2026-09-03T08:00:00Z** and is permanently unavailable there. Every
  result through the v2 budget re-run and the broad-corpus run used this
  model; none of it is reproducible against it anymore, though the
  numbers remain historically accurate for what they measured. Evaluation
  work from Phase 23 onward uses `openai/gpt-oss-20b` (smaller, same
  family) — results are labeled by model in every report and are never
  pooled across the two.
- **`seed` is a request hint on this endpoint, not a reproducibility
  guarantee.** Phase 23's determinism investigation
  (`reports/determinism_investigation.md`) made 10-20 back-to-back calls
  with byte-identical parameters (same prompt, same model, `temperature=0`,
  fixed `seed`) and got genuinely different completion lengths and
  reasoning content every time — confirmed directly, not inferred.
  Truncation-before-reaching-an-answer is consequently a real, measured
  contributor to wrong answers even at generous completion budgets,
  independent of anything TDF-specific. Any interpretation of `seed`-level
  variance in this project's raw data should account for this: two rows
  with the same `seed` are not guaranteed to reflect the same underlying
  generation, and a rerun with the same seed is not guaranteed to
  reproduce a prior run's exact completions.
- `client.py`'s `generate()` captures `finish_reason` and
  `used_reasoning_fallback` per call as of Phase 23 — use these (present
  in every result row from that point on) to distinguish a genuine wrong
  answer from a truncated-before-conclusion one, rather than inferring it
  from `pred` text or a token-count proxy.

## Decision Rules

Let Δ = (TDF accuracy) − (Markdown accuracy), measured as a paired difference with a 95% bootstrap CI.

| Outcome | Decision |
|---|---|
| CI lower bound ≥ −1pp | TDF is accuracy-neutral. Publish the frontier. Proceed with the roadmap. |
| CI spans −1pp to −4pp | Marginal. Ship only the hybrid emitter (Markdown for prose, TDF for tables) and re-test. |
| CI upper bound < −4pp | The format costs real accuracy. Compression claims must carry the accuracy penalty in the README, prominently. |
| Any single ablation recovers ≥3pp | That mechanism is disabled by default regardless of its compression contribution. |

Explicitly: a mechanism that saves 8% tokens and costs 4pp accuracy gets deleted. This threshold will not be renegotiated after seeing results.

## Adversarial question families (must be included)

The eval set must include explicit stress tests for:

- Row association
- Column association
- Negation
- Numeric comparison
- Multi-hop table reasoning
- Cross-reference resolution across tables/sections
- Dictionary phrase resolution (`§n`)
- Column-code resolution (`!V`)
- Repeated-cell resolution (`^`)
- Ordering (first/last, sequence-sensitive)
- Exact identifiers
- Leading-zero numbers
