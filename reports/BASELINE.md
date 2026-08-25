# Baseline Report (Phase 2) — captured before structural-fidelity changes

*Commit `da1cf42` (+ README/docs edits). Captured 2026-08-24. All later changes
must be diffed against this file.*

## Test suite

`pytest tests/ -q` → **168 passed, 0 failed** (~70–95 s wall).
Known flake source: the hybrid Hypothesis property draws fresh examples when
the hypothesis DB is disabled (`-p no:cacheprovider`); 5 seed-sweeps green
after the GFM-trim exclusion was added. Raw capture: `reports/base_tests.txt`
(note: a stderr deprecation warning can displace the summary line under
`tail -1`; grep `passed` instead).

## Token counts (CLI `stats --json`, o200k_base, legend included)

| Document | Markdown | TDF (legend) | TDF (no legend) | Skeleton |
|---|---|---|---|---|
| runbook.md | 1,355 | 1,011 | 782 | 156 |
| orders.csv | 16,982 | 10,412 | 10,183 | 52 |
| sec_filing.html | 26,587 | 15,204 | 15,173* | 274 |
| kubernetes_docs.html | 36,945 | 28,523 | 28,523* | 733 |

Raw: `reports/base_stats.jsonl` (68 lines). \* no-legend figures for the two
real HTML documents were captured earlier in-session; identical pipeline.

## Round-trip fidelity (`tdf verify --json`, bag-of-words era metric)

| Document | distinct_recall | occurrence_ratio |
|---|---|---|
| orders.csv | 1.000 (1,079 terms) | 1.000 |
| runbook.md | 1.000 (95 terms) | 1.000 |

Raw: `reports/base_verify_*.json`. **Caveat carried forward:** this metric is
order-blind and type-blind (a swapped table row still scores 100%). The
Phase-3 structural framework (`tdf/fidelity_structural.py`, added after this
baseline) supersedes it as primary evidence.

## LLM accuracy

Already landed this session, pre-baseline: see
`eval/results/REPORT.md` — Δ = −6.3pp [−8.8, −3.7] @ −43.1% tokens,
verdict MARGINAL (n=6310, gpt-oss-120b). Not re-measured here.

## Performance

Not yet measured (Phase 12). Observed informally: full suite ~75–95 s;
per-document `stats` ≈ 2–5 s dominated by tokenizer warm-up on first call.

## External dependencies status

NVIDIA endpoint (`integrate.api.nvidia.com`): DOWN at baseline time (probe
timeout 15–240 s). Affects Phase 7 multi-model collection; local Qwen path
remains available for supplementary fills only.