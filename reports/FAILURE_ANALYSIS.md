# Failure Analysis (Phase 5) — Why TDF loses accuracy vs Markdown

*Derived from eval/results/raw.jsonl (n=6,310) via scripts/analyze_failures.py;
full categorized records in eval/results/failures.json (82 paired TDF-losses).*

## ⚠️ Methodology confound found during this analysis (dominant)

**85% of the TDF-loss bucket (70/82) are predictions truncated at the
256-token completion cap.** gpt-oss-120b is a reasoning model: it spends
completion tokens thinking before answering, and 73% of ALL runs hit the cap
(tdf_full: 710/789 = 90%; md: 597/788 = 76%). A truncated prediction is an
artifact of the budget, not evidence about the representation — harder
representations get less thinking room, so the v1 accuracy comparison
measures *representation difficulty × budget adequacy*, not representation
quality alone.

**Consequence:** the −6.3pp headline stands AS MEASURED under v1, but is
CONFOUNDED. After separating truncated runs, only **12 losses remain
potentially attributable to the representation** (≈1.5pp) — plus 55
comprehension failures where content was recoverable and the model answered
wrongly anyway. A budget-adequate re-run (v2) is required before verdict
language ("marginal" or otherwise) can be trusted. Taxonomy below reflects
the ORIGINAL v1 attribution, preserved per §29; truncation-separated numbers
live in the regenerated failures.json (`reasoning_truncated: 70`).

## Headline

Of 788 matched triples, TDF-full loses **82** and wins **45** against Markdown
(net −37). The loss bucket decomposes as:

| Root cause | Count | Share |
|---|---|---|
| **encoded_away** — gold string absent from the wire | **42** | **51%** |
| other_wrong — model reasoned wrong on present content | 34 | 41% |
| scorer_strict — gold contained in pred but rejected | 5 | 6% |
| deref_leak — raw code letter emitted instead of value | 1 | 1% |

## Top failure clusters

| # | Cluster (qtype : cause) | n |
|---|---|---|
| 1 | row_association : encoded_away | **30** |
| 2 | row_association : other_wrong | 13 |
| 3 | column_association : other_wrong | 8 |
| 4 | multi_hop_table : encoded_away | 6 |
| 5 | exact_identifier : scorer_strict | 4 |
| 6 | negation : other_wrong | 4 |
| 7 | repeated_cell : other_wrong | 4 |
| 8 | ordering : encoded_away | 3 |
| 9 | repeated_cell : encoded_away | 3 |
| 10 | cross_reference : other_wrong | 3 |

TDF *wins* net on negation (+10) and dictionary resolution (+4) — density helps
where redundancy hurt comprehension in the first place.

## Mechanism of the dominant cluster (worked example)

Q: *"In the table, what is 'c2' where 'c1' is '0.75% Notes due 2713'?"*
Gold: `"—"`. Model: `"We need to locate table where c1 is \"0.75% Notes due
2713\". Search in document."`

The lookup KEY itself (`0.75% Notes due 2713`) was **caret-elided** — it
duplicated a value in the row above, so `_tdf_table` replaced it with `^`. The
wire no longer contains the row's identity anchor, the model cannot locate the
row, and it leaks meta-text instead of an answer. The gold em-dash placeholder
was additionally normalised away. This is §17's "removed constant columns /
caret references" category, confirmed with named evidence rather than theory.

## Quantified remediation candidate (for §19 ablation)

Never caret-elide the **first column** (the conventional primary-key / row
anchor), or cap caret-chain depth at k rows. The 30 row_association losses
represent **≈3.8 pp of tdf_full arm accuracy** (30/789); recovering even half
shifts the paired CI upper bound from −3.7 toward ≈ −2.5 — potentially moving
the verdict band. **Hypothesis only**: must be re-run under the same harness,
not assumed.

Secondary findings: `scorer_strict` (5×, all exact_identifier) flags possible
matcher false-negatives worth manual review; em-dash/placeholder golds need an
explicit normalisation rule.

## What this does NOT claim

No change to the published verdict; no fix assumed until ablated (§19); single
model, SEC-heavy corpus caveat stands (see REPORT.md).