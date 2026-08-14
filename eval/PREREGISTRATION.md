# TDF Accuracy-Per-Token Eval: Pre-registration

## Decision Rules

Let Δ = (TDF accuracy) − (Markdown accuracy), measured as a paired difference with a 95% bootstrap CI.

| Outcome | Decision |
|---|---|
| CI lower bound ≥ −1pp | TDF is accuracy-neutral. Publish the frontier. Proceed with the roadmap. |
| CI spans −1pp to −4pp | Marginal. Ship only the hybrid emitter (Markdown for prose, TDF for tables) and re-test. |
| CI upper bound < −4pp | The format costs real accuracy. Compression claims must carry the accuracy penalty in the README, prominently. |
| Any single ablation recovers ≥3pp | That mechanism is disabled by default regardless of its compression contribution. |

Explicitly: a mechanism that saves 8% tokens and costs 4pp accuracy gets deleted. This threshold will not be renegotiated after seeing results.
