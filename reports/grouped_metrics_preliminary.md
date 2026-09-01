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
