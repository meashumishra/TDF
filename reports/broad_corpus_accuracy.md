# Broad-corpus accuracy: the SEC-filing bias was real (Phase 22)

*2026-09-03. `openai/gpt-oss-120b`, 1 seed, budget=2048, 5 arms (md, tdf_full,
toon, json, tdf_nocaret0). 18 of 19 readable corpus documents, 421 questions
x 5 arms = 2105 attempted, 2082 completed (`pride_prose` excluded — see
Limitations). Raw data:
`eval/results/raw_broad_2048_combined.jsonl`. Every prior accuracy report in
this project (v1, v2, `TDF-R_FINAL_REPORT.md`) ran on the same 5-document,
263-question corpus where one SEC filing supplied 86-89% of all questions —
this is the first run against the full, family-diverse corpus.*

## Headline: the accuracy gap depends heavily on which average you read

| Average | md | tdf_full | Δ |
|---|---|---|---|
| **Micro** (every question weighted equally — what every prior report measured) | 65.1% | 57.0% | **-8.2pp** [CI -11.8, -4.6] |
| **Macro** (every document weighted equally, then averaged) | 77.9% | 78.3% | **+0.4pp** |

Both numbers come from the exact same 2,082 completions. The micro average is
what you get when one document (`sec_filing`, 227 of 519 questions — 54.3%)
dominates the pool. The macro average is what you get when it doesn't. **The
"-8-13pp, TDF costs real accuracy" conclusion in every prior report is not
wrong about `sec_filing` — it is wrong as a claim about TDF in general.**

## Accuracy by document family (tdf_full vs md)

| Family | tdf_full | md | Δ |
|---|---|---|---|
| code_documentation | 100.0% | 100.0% | 0.0pp |
| kubernetes_docs | 95.0% | 95.0% | 0.0pp |
| md_readmes | 91.7% | 92.3% | -0.6pp |
| grouped_metrics | 94.3% | 98.1% | -3.8pp |
| prose_books | 57.1% | 60.0% | -2.9pp |
| **legacy** (co2_data, k8s_deployment, **sec_filing**, operating_review, sales_report) | 40.2% | 50.6% | **-10.4pp** |
| legal_policy (github_terms) | 80.0% | 90.0% | **-10.0pp** |
| rfc_technical | 75.0% | 85.0% | **-10.0pp** |
| logs_synthetic (access_log) | 60.0% | 70.0% | -10.0pp |

Two distinct clusters, not a spectrum: **near-parity** (k8s docs, READMEs,
code docs, grouped_metrics — 0 to -3.8pp) and **a real ~10pp gap** (SEC
filing, legal text, RFCs, logs). Nothing in between. This is not "TDF is
mostly fine with occasional noise" — it's two different regimes, and the
old corpus happened to sample almost exclusively from the second one.

**What's different about the losing cluster?** Financial tables, legal
prose, RFC specification text, and log lines are all dense with exact
numbers, dates, section references, and identifiers that a wrong-by-one
answer fails outright — closer to the `exact_identifier`/`numeric_comparison`
question types this project's whole "protected information" audit (Phase 14)
was worried about. The winning cluster (k8s docs, READMEs, code docs) is
comprehension-style prose and structured API references where an
approximately-right answer often still scores correct. This is a hypothesis
from the pattern, not something this run isolated directly — the qtype
breakdown in the raw data would need its own pass to confirm it.

## What this changes

- **The README's "Known limitations" framing needs to change** from "TDF
  costs real accuracy" (stated as if it's a property of the format) to
  "TDF's accuracy cost is concentrated in specific document types — dense
  numeric/legal/spec text — and near-zero on structured technical docs and
  prose." See the README diff alongside this report.
- **The `sec_filing`-dominance caveat every report has carried since v1 was
  right to flag, but undersold**: it wasn't just "headline numbers lean
  toward financial content," it was "headline numbers are a different
  regime than most of the corpus."
- **This does not overturn any single-document finding.** `sec_filing`
  specifically still shows a real, reproduced accuracy cost — that finding
  stands. What changes is generalizing FROM `sec_filing` TO "TDF" as a
  format claim.

## Limitations

- **`pride_prose` excluded entirely, not just from this run.** Every
  representation (md, json, toon, tdf_full) is ~159K tokens for this
  document — `tdf_full` saves only 0.5% vs md (158,370 vs 159,156 tokens),
  since a compression mechanism built for tabular/structured redundancy has
  nothing to exploit in continuous prose. All arms hit `HTTP 400: Bad
  Request` uniformly, consistent with exceeding `gpt-oss-120b`'s context
  window regardless of format. This is a real, disclosed constraint on
  testing full-novel-length documents with this model — not a TDF-specific
  failure, since every format failed identically.
- **1 seed, not 3** (matching this project's `v2` re-run's tradeoff of
  seeds for breadth) — wider CIs than a 3-seed run would give, though the
  micro-vs-macro divergence is large enough (8.6pp apart) that it is not
  seed-count-sensitive.
- **Per-document macro contributions are uneven in sample size.** Several
  `legacy`-family documents have only 4-6 questions each (`co2_data`,
  `k8s_deployment`, `operating_review`), so their individual contributions
  to the macro average are noisy. The macro/micro divergence itself doesn't
  depend on these thin cells — `sec_filing` alone (227 questions, one
  macro-average data point among 18) is what's suppressed by macro
  averaging, and that suppression is the whole point being demonstrated.
- **`toon`/`json` were included for reference, not analyzed in depth here**
  — both track close to `md` on both averages, consistent with prior runs.
- **A late transient network failure** (DNS resolution error, not a rate
  limit) wiped out 5 documents' data in the first pass of this run; a
  second, scoped pass filled in 4 of them (excluding `pride_prose`, per
  above). Nothing about the failure or the fill-in affected which
  documents ended up in the final combined dataset beyond that exclusion.

## Addendum: the qtype breakdown turns the ~10pp gap into a mechanism claim

Splitting the "losing cluster" (legacy/legal_policy/rfc_technical/
logs_synthetic) and "winning cluster" (kubernetes_docs/code_documentation/
md_readmes/grouped_metrics) by question type shows the losing cluster's gap
is not spread evenly across question types — it is concentrated almost
entirely in relationship-tracking questions:

| qtype | md | tdf_full | Δ | n |
|---|---|---|---|---|
| **row_association** | 83.9% | 50.0% | **-33.9pp** | 56 |
| **multi_hop_table** | 56.2% | 26.7% | **-29.5pp** | 15-16 |
| **cross_reference** | 83.3% | 66.7% | **-16.6pp** | 18 |
| column_association | 92.3% | 86.5% | -5.8pp | 52 |
| exact_identifier | 70.0% | 70.0% | 0.0pp | 10 |
| deref_code | 66.7% | 66.7% | 0.0pp | 3 |
| negation | 27.3% | 30.3% | +3.0pp | 33 |
| deref_dict | 25.0% | 75.0% | +50.0pp | 4 (thin) |
| numeric_comparison | 5.3% | 10.8% | +5.5pp | 37-38 |
| ordering | 11.3% | 9.4% | -1.9pp | 53 |

In the winning cluster, every question type is within a few points of
parity (`tdf_full` even beats `md` on `cross_reference`, 100% vs 90%,
n=10). **The entire ~10pp family-level gap traces to three
relationship-tracking question types** — exactly the row/entity-identity
failure mode Phase-5's original failure analysis found and every
subsequent mitigation (`tdf_nocaret0`'s anchor protection, the semantic-
tree grouping work) has targeted. This is not "TDF makes comprehension
worse in general" — it's "TDF's caret-elision and columnar coding make it
harder to track which row a value came from," a much narrower and more
actionable claim.

**Caveat that must be attached to this table**: `numeric_comparison` and
`ordering` are nearly floor-level for BOTH formats (5-11%), which is not
plausibly a real capability gap — inspecting failures shows the auto-
generated `ordering` questions frequently ask about "this table" in
documents (chiefly `sec_filing`) containing many tables, without
specifying which one, so the question is often genuinely ambiguous rather
than hard. Since both formats fail near-identically, this doesn't affect
the row_association/multi_hop_table/cross_reference finding above (which
IS a real, reproduced TDF-vs-md gap), but the raw floor-level numbers for
these two types should not be read as "TDF and md are both bad at
counting" — they're more likely "these specific auto-generated questions
are underspecified," a pre-existing corpus-quality issue orthogonal to
format.

## Recommendation

The qtype breakdown above is itself the answer to what was previously an
open recommendation here — it turns "these families lose ~10pp" into a
testable mechanism claim. The next useful step is narrower than another
broad eval: get real accuracy data for the semantic-tree grouping arm
(`tdf_grouped`) specifically on `row_association`/`multi_hop_table`
questions, since this addendum just confirmed that's precisely the
failure mode it was built to address, and the only measurement so far
(`reports/grouped_metrics_preliminary.md`) used a document without
`sec_filing`-style density. Fixing the `ordering`/`numeric_comparison`
question-ambiguity issue in `eval/questions/generate.py` (specify which
table when a document has several) would also be a legitimate, low-effort
corpus-quality fix independent of anything TDF-specific.
