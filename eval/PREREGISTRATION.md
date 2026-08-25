# TDF Accuracy-Per-Token Eval: Pre-registration

## Post-hoc additions (disclosed)

- **`hybrid` arm added after unblinding** (0.2.1): per-block Markdown/TDF
  arbitration. Registered in `eval/formats/encode.py` so its cells can be
  collected by the standard runner, but it has **no rows in the first run's
  results** and its future numbers are **exploratory** — they are not part
  of the decision rules below, which were applied to the original eight arms
  only. The pre-registered verdict stands as published.

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
