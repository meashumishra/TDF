# `tdf_grouped` preliminary results (Phase 20)

*2026-09-01. Scoped eval on the new `grouped_metrics` corpus document
(country/year/metric CSV with genuine multi-entity contiguous-row
structure), 8 questions × 6 arms (md, tdf_full, tdf_grouped, tdf_nocaret0,
toon, json) × 3 seeds × 4 budgets (512/1024/2048/4096). Raw data:
`eval/results/raw_grouped_{512,1024,2048,4096}.jsonl`.*

## Data quality caveat (read first)

Budget 512 completed cleanly (144/144). Skip rate then rose sharply and
fast: 1024 → 25%, 2048 → 35%, 4096 → 51%, all `"API failed after
retries"` rather than plain timeouts, and each subsequent budget finished
*faster* despite the worse skip rate — consistent with the NVIDIA endpoint
rate-limiting this session after the much larger run earlier the same day,
not with a new problem in this run's own logic. **Every number below has
n≤24 per arm per budget, often much less after skips** — an order of
magnitude smaller than the main corpus's n≈230-260. Nothing here should be
treated as a confident verdict; it's a first, small look.

## Overall accuracy (8 questions, all types pooled)

| Budget | md | tdf_full | tdf_grouped | tdf_nocaret0 | toon | json |
|---|---|---|---|---|---|---|
| 512 (n=24 each) | 87.5% | 87.5% | 83.3% | **91.7%** | 79.2% | 87.5% |
| 1024 (n=17-19) | 100% | 100% | 100% | 100% | 100% | 100% |
| 2048 (n=13-18) | 82.4% | 92.3% | 92.3% | 88.2% | 83.3% | 81.2% |
| 4096 (n=9-14) | 100% | 78.6% | 91.7% | 100% | 100% | 100% |

No consistent ranking across budgets at this sample size — 1024 is
saturated (every arm perfect, no discriminating power at all), and the
other three budgets each tell a different story. This is exactly the
"don't trust n<30" caution the main final report already applies to thin
cells; it applies doubly here.

## The one mechanistically on-point result

One question directly targets the mechanism this whole feature is about —
a `repeated_cell` question generated because "Argentina" repeats across
consecutive rows: *"For 'record_id'='REC-AAAB', what is 'country'?"*
(gold: `Argentina`). Pooled across all 4 budgets and 3 seeds (up to 12
attempts per arm, fewer where skips hit):

| Arm | Correct | Wrong | Wrong answer given |
|---|---|---|---|
| `tdf_grouped` | 10/10 | 0 | — |
| `md` / `json` | 9/9 each | 0 | — |
| `tdf_nocaret0` | 9/9 | 0 | — |
| `toon` | 8/8 | 0 | — |
| `tdf_full` | 6/9 | **3** | `"Denmark"` every time |

`tdf_full`'s caret-elision produced a real, repeated, consistent wrong
answer ("Denmark" — the 4th country in the sorted list, not adjacent to
Argentina) on exactly the pattern Phase-5's failure analysis and this
feature were built around. `tdf_grouped`'s literal `@ Argentina` header
never failed on this question in any budget or seed collected so far.
This is the single most direct piece of evidence yet that the group-header
mechanism helps the specific row-association failure mode — but it is one
question, and it needs more seeds/questions before it's more than
suggestive.

## What this does and doesn't establish

- **Does not establish** that `tdf_grouped` is an overall accuracy win —
  the pooled 8-question numbers don't show a clean pattern, and budget 512
  (the one clean dataset) has it slightly behind `tdf_full`.
- **Does suggestively support** the mechanism-level hypothesis behind both
  `tdf_grouped` and `tdf_nocaret0`: an opaque `^` marker on a
  caret-elided identifier is a real, reproducible failure mode, and
  keeping the value literal (whether via a group header or anchor
  protection) avoids it on this example.
- **Next step, if this is worth pursuing further**: more questions for
  `grouped_metrics` (currently only 8 — `eval/questions/add_document.py`
  makes this cheap to extend) and a re-run once the endpoint's rate limit
  has reset, ideally with more seeds now that this specific document's
  question set is small and cheap to test repeatedly.

## Addendum: 45 targeted stress questions, partial re-run (2026-09-02)

`eval/questions/add_row_association_stress.py` added 45 more questions of
exactly the same shape (`"what is 'country' where 'record_id' is X"`,
3 per country, sampled from non-first rows within each country's block —
position 0 is trivially correct for every arm regardless of mechanism).
A 5-seed re-run at budget 512 was launched (`EVAL_SEEDS=1,2,3,4,5`) but
the endpoint's failure rate spiked hard partway through (22 → 110 skipped
within 100 attempts) — a single serial call immediately after stopping
the run succeeded in 1.1s, so this looks like sustained-concurrency
throttling, not an outage. **The run was stopped rather than grinding
through hours of near-total failures**; only budget 512 has data, and
only partially (385/1590 rows). Higher budgets (1024/2048/4096) have no
data from this addendum.

What that partial data shows on the 45 stress questions specifically
(n=21-28 per arm, budget 512 only):

| Arm | Correct | Wrong | Nature of failures |
|---|---|---|---|
| `tdf_grouped` | 24/24 | 0 | — |
| `md` / `json` / `toon` | 26/26, 28/28, 25/25 | 0 | — |
| `tdf_full` | 20/21 | 1 | truncated mid-reasoning (near completion-token cap, not a wrong final answer reached) |
| `tdf_nocaret0` | 19/21 | **2** | both `"Denmark"` — genuine wrong answers, NOT truncated |

This is a more nuanced picture than the first (8-question) run gave.
There, `tdf_nocaret0` was perfect (9/9) and only `tdf_full` failed.
Here, with more data, **`tdf_nocaret0` also produces the same "Denmark"
hallucination twice**, even though its whole design keeps the country
column (the group-key column here) literal on every row via anchor
protection rather than caret-eliding it. That means the earlier
hypothesis — "caret-eliding the identifier column is the specific cause"
— is not the full story: `tdf_nocaret0` still applies columnar `!V`
coding and caret-elision to every OTHER column, and something in that
denser (but country-literal) representation is still confusing the model
on 2 of 21 attempts. `tdf_grouped` remains clean at 24/24 in this run,
which is now two independent samples (10/10 then 24/24, 34/34 combined)
with zero failures on this exact question shape — the most consistent
result of any arm so far, though still not enough volume (and no data at
all above budget 512) to call it a settled finding.

**Recommendation:** don't re-run again immediately — the throttling
suggests this session's cumulative request volume today is the actual
constraint, not anything about how the run is configured. If this is
worth finishing, retry the remaining budgets (1024/2048/4096) at a later
time, and consider lowering `EVAL_CONCURRENCY` (this run used 15, same as
every prior run today) to see if a lower sustained rate avoids the
throttle rather than just running into it slower.

## Final, properly-powered result (2026-09-03) — different model, read this section for the actual verdict

**Model change, disclosed:** `openai/gpt-oss-120b` (used for every result
above and every other report in this project) reached end-of-life on its
NVIDIA API endpoint at 2026-09-03T08:00:00Z and is permanently
unavailable — confirmed directly from the API's own error detail
mid-run. This run used `openai/gpt-oss-20b` instead (smaller, same
family). **Not comparable to anything above or in any other report** —
treat this section as a fresh, self-contained result, not a continuation
of the 120b numbers.

Full 53-question set, all 4 arms (md, tdf_full, tdf_grouped, tdf_nocaret0),
5 seeds, budget=2048, **1,060/1,060 completed, zero skips** — the
cleanest, best-powered run this feature has had. Raw data:
`eval/results/raw_grouped_gptoss20b_2048.jsonl`.

### Row association (46 of 53 questions, n=230/arm) — paired diff vs md

| Arm | vs md | 95% CI |
|---|---|---|
| tdf_full | -3.48pp | [-6.09, -1.30] |
| tdf_grouped | -2.61pp | [-4.78, -0.87] |
| tdf_nocaret0 | -1.30pp | [-3.04, +0.00] |

All three CIs exclude (or, for `tdf_nocaret0`, just touch) zero — this is
a real, reproducible deficit for every mechanism relative to md, smaller
in absolute size than the 120b model's earlier (noisier, smaller-n)
"Denmark" hallucinations but the same direction. The ordering
`tdf_nocaret0` > `tdf_grouped` > `tdf_full` (smallest to largest gap vs
md) matches the anchor-protection hypothesis exactly. `tdf_grouped` vs
`tdf_full` directly: +0.87pp, CI [-2.61, +3.91] — the point estimate
favors grouping but this specific comparison is not independently
significant at n=230.

### The rest of the question set (7 of 53 questions, n=35/arm) — a complication

| Arm | Accuracy |
|---|---|
| md | 85.7% |
| tdf_full | 91.4% |
| tdf_grouped | 91.4% |
| tdf_nocaret0 | **77.1%** |

Outside row-association, `tdf_full` and `tdf_grouped` both *beat* md, while
`tdf_nocaret0` is noticeably worse than everything else. n=35 is thin (7
questions x 5 seeds) so this shouldn't be over-read, but it's a real
pattern worth naming: **`tdf_nocaret0`'s blanket column-0 protection may
cost something on question types it wasn't designed for, while
`tdf_grouped` doesn't show that same trade-off** — it matches `tdf_full`'s
strength elsewhere while also narrowing the row-association gap `tdf_full`
has. If that holds up with more data, it's a real point in favor of the
grouping mechanism over blanket anchor protection: same benefit, no
apparent side effect.

### Bottom line

With a clean, fully-powered run: **every TDF mechanism tested still shows
a real row-association deficit vs md** (this is not confounded by
truncation or small-n noise anymore), and grouping/anchor-protection both
measurably narrow it without closing it. Neither `tdf_nocaret0` nor
`tdf_grouped` is a fix — they're both improvements over plain `tdf_full`.
This is consistent with, and sharpens, the broad-corpus finding
(`reports/broad_corpus_accuracy.md`) that row_association specifically
(not TDF's other mechanisms) is where the format's real, reproducible
accuracy cost lives.
