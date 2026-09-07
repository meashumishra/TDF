# Determinism investigation: solving the budget-vs-accuracy inversion (Phase 23)

*2026-09-04. The v2 budget re-run (`reports/TDF-R_FINAL_REPORT.md`) found
accuracy on the main corpus got WORSE as completion budget rose from 512
to 4096, even though a truncation proxy showed cap-hits genuinely falling
from ~53% to ~5% over the same range — an unexplained finding flagged as
the single biggest open question from that report. That report's own
"What should TDF-R become next" section proposed exactly this
experiment: "a same-prompt repeated-sampling experiment to separate
'more budget hurts' from 'the provider isn't deterministic under load'."*

*`openai/gpt-oss-120b` (the model the original finding was measured on)
reached end-of-life on NVIDIA's API on 2026-09-03 and is gone (see
README). This investigation uses `openai/gpt-oss-20b` instead — it
cannot re-verify the original 120b numbers, but it can test whether the
SAME underlying mechanism (provider non-determinism) is real and
plausible as an explanation, which is the actual question that matters.*

## Method

Raw, uncached HTTP calls (bypassing `client.py`'s cache entirely) to the
exact same endpoint used by every eval run in this project, with
**identical parameters on every call**: same prompt (a real
`grouped_metrics` row-association question through `tdf_full`), same
model, `temperature=0`, `seed=1`. If the endpoint were truly
deterministic under these settings, every call should return byte-
identical output. It does not.

## Finding 1: reasoning length varies randomly, every call, despite fixed seed+temperature

10 consecutive identical calls at `max_tokens=2048`:

| Call | completion_tokens | reasoning length (chars) | finish_reason | content |
|---|---|---|---|---|
| 1 | 166 | 453 | stop | Kenya |
| 2 | 175 | 493 | stop | Kenya |
| 3 | 264 | 817 | stop | Kenya |
| 4 | 205 | 602 | stop | Kenya |
| 5 | 175 | 493 | stop | Kenya |
| 6 | 345 | 1269 | stop | Kenya |
| 7 | 253 | 948 | stop | Kenya |
| 8 | 226 | 729 | stop | Kenya |
| 9 | 318 | 1053 | stop | Kenya |
| 10 | 184 | 629 | stop | Kenya |
| 11 | — | — | (client read timeout at 60s) | — |

`completion_tokens` ranges from 166 to 345 — more than 2x variance — for
the identical request, all 10 landing on the correct final answer this
time, but taking genuinely different reasoning paths to get there
(`reasoning_content` is different text each time, not just different
length — spot-checked, not merely re-wrapped). The 11th call didn't even
return within 60 seconds, consistent with an even-longer, unbounded
reasoning trace on that attempt. **`temperature=0` + a fixed `seed` does
not guarantee deterministic generation on this endpoint.** This is not
speculation; it's measured directly, with nothing else varying between
calls.

## Finding 2: this alone doesn't need a "budget hurts reasoning" story — it's already sufficient noise

A separate 20-call run at `max_tokens=2048` (client.py's actual content-
extraction path, not the diagnostic path above) found 19/20 calls
returned `"Kenya"` and 1/20 returned an empty string. Re-running with
full diagnostics (Finding 1's table) shows why: that single empty
response almost certainly landed in the tail of the same reasoning-
length distribution shown above — a call whose reasoning ran long enough
to exhaust the budget before ever emitting a final answer, exactly like
the 64-token case below, just at the tail of the distribution rather than
the median.

A parallel run at `max_tokens=64` made the mechanism unambiguous: **all
20 identical calls** returned `content: null`, `finish_reason: "length"`,
with `reasoning_content` showing genuinely different partial reasoning
each time, cut off mid-search before reaching an answer. At a small
enough budget, this endpoint's variable-length reasoning reliably
exceeds it.

## What this does and doesn't explain about the original inversion

**Directly supported**: the "provider isn't deterministic under load"
hypothesis from the original report's own proposed experiment. Confirmed
here in the strongest form possible — not "different seeds give different
answers" (expected), but "the identical seed, temperature, and prompt
give different generation lengths and different reasoning content every
time." Any eval methodology that treats `seed=N` as a guarantee of
reproducibility on this endpoint is building on a false assumption — a
disclosure that applies to every prior run in this project, not just the
budget re-run.

**Confirmed with data already in hand** (no new API calls — this is
recommendation #2 below, done immediately rather than deferred):
correlating `completion_tokens` with `correct` on the full `gpt-oss-20b`
`grouped_metrics` run (1,060 rows, 4 arms) shows wrong answers are
**bimodal, not uniformly longer**:

| Arm | correct avg tokens | wrong avg tokens |
|---|---|---|
| md | 1.7 (n=260) | 2.0 (n=5) |
| tdf_full | 41.7 (n=254) | 1.2 (n=11) |
| tdf_grouped | 33.4 (n=256) | 909.4 (n=9) |
| tdf_nocaret0 | 25.6 (n=254) | 1.5 (n=11) |

`tdf_grouped`'s wrong-answer average is dragged entirely by 4 of its 9
wrong rows sitting at exactly 2045 completion_tokens (three tokens shy of
the 2048 ceiling) with `pred` reading `"We need to parse the document.
The question: ..."` — the raw, unfinished reasoning trace, never reaching
a conclusion. The other 5 wrong rows are 1-2 tokens: quick, confident,
wrong short answers (`'none'`, `'a'`, a wrong country name), unrelated to
reasoning length at all. **These are two distinct failure modes, not one
"longer reasoning = wrong answer" spectrum**: truncation-before-conclusion
(guaranteed wrong, budget-dependent, and the mechanism Finding 1 explains
directly) and short confident mistakes (a genuine comprehension error,
budget-independent). `tdf_full`/`tdf_nocaret0` show almost no truncation
in this sample (their wrong answers are all short mistakes) — `tdf_grouped`
happening to hit truncation 4/9 times here, on n=9, could easily be a
small-sample artifact rather than a property of grouping specifically;
this data doesn't have the power to say more than "truncation is a real,
observed contributor to wrong answers even at budget=2048, for at least
one arm."

This sharpens, but doesn't fully close, the original inversion question.
It confirms truncation-before-conclusion is a real, non-zero contributor
to wrong answers even at a budget (2048) the original report treated as
adequate — directly consistent with Finding 1's random reasoning-length
variance occasionally exceeding even a generous budget. It does NOT show
that LARGER budgets cause MORE of the short-confident-mistake failure
mode, which is what would be needed to fully explain why accuracy at
4096 tokens was worse than at 512 in the original (120b) report. That
remains the one piece this investigation did not settle.

## Recommendation

1. **DONE.** Treat `seed` as a request hint, not a reproducibility
   guarantee, for any future eval work against this endpoint — stated
   explicitly in `eval/PREREGISTRATION.md`'s "Model notes" section.
2. **DONE.** `client.py`'s `generate()` now captures `finish_reason` and
   `used_reasoning_fallback` on every call (Phase 23), letting a run
   distinguish "wrong answer" from "truncated before reaching one"
   directly on every row instead of inferring it after the fact.
3. **DONE (Phase 24) — answered: no.** See the addendum below. A real
   multi-budget run with `finish_reason` captured shows that, once the
   comparison is restricted to questions that actually complete (removing
   a skip-driven selection effect the run itself surfaced), accuracy does
   NOT decline with budget. The original 120b inversion is not explained
   by "more budget causes more genuine mistakes."

## Addendum (Phase 24): the budget-accuracy inversion does not replicate on gpt-oss-20b, once skip-selection is controlled for

*2026-09-07. Multi-budget run: `openai/gpt-oss-20b`, budgets
512/1024/2048/4096, 1 seed, `md`+`tdf_full` arms only, the original
263-question 5-document corpus (same corpus as the v2 120b re-run, for
comparability). 526 tasks/budget. Raw data:
`eval/results/raw_v3_{512,1024,2048,4096}.jsonl`.*

**First finding, unplanned: timeout-skip rate rises sharply with
budget**, independent of the accuracy question this run was designed to
answer:

| Budget | Completed | Skipped (60s HTTP read-timeout) |
|---|---|---|
| 512 | 526/526 | 0% |
| 1024 | 526/526 | 0% |
| 2048 | 469/526 | 10.8% |
| 4096 | 369/526 | **29.8%** |

Every skip logged as `"The read operation timed out"` — not a rate limit
or a 4xx/5xx. This is a direct, mechanical consequence of Finding 1
above (reasoning length varies randomly and unboundedly): a larger
`max_tokens` budget gives a long reasoning trace more room to run before
hitting the completion cap, and a growing share of those traces exceed
the 60-second wall-clock timeout before either finishing or hitting the
cap. **This means naively comparing raw accuracy across budgets is
comparing different, budget-dependent populations of questions** — the
4096 dataset systematically excludes whichever questions provoke the
longest reasoning, which is not a random sample.

**Controlling for this**: restricting to the 356 (of 526) questions that
completed (non-skipped) at *all four* budgets — a fixed, identical
question set at every budget — and comparing accuracy on that matched
set directly:

| Arm | n | 512 | 1024 | 2048 | 4096 | truncated@512 | truncated@4096 |
|---|---|---|---|---|---|---|---|
| md | 184 | 59.2% | 54.3% | 57.1% | 58.7% | 108 | 0 |
| tdf_full | 172 | 43.6% | 40.1% | 39.5% | 40.1% | 103 | 0 |

Paired 512-vs-4096 diff on this matched set: md **-0.5pp** [CI -6.0,
+4.9], tdf_full **-3.5pp** [CI -8.7, +1.7]. Both CIs span zero — **no
statistically significant accuracy change across an 8x budget range**,
for either arm, once the same questions are compared at every budget.
`truncated` (finish_reason=`"length"`) count drops from 103-108 at
budget=512 to 0 at budget=4096 as expected (bigger budget genuinely
resolves truncation), and `short_wrong` (a completed, wrong answer) rises
by almost exactly the same amount each arm loses in `truncated` — i.e.
**a truncation failure is being converted into a completed-but-wrong
failure as budget rises, not adding a new failure on top of a question
the model would otherwise have gotten right.** Net accuracy is flat
because the conversion is (within noise) accuracy-neutral: some
of those newly-completed answers are right, some are wrong, in roughly
the same proportion the arm gets right/wrong everywhere else.

**Conclusion: the original 120b report's "accuracy falls as budget
rises" finding does not replicate here.** On `gpt-oss-20b`, over the same
corpus and budget range, real (non-skipped, matched) accuracy is flat.
This does not prove the 120b finding was wrong on its own terms — that
model is permanently unavailable to re-test directly — but it removes
"larger budgets cause more genuine mistakes" as a plausible *general*
mechanism, since it fails to reproduce on a same-family, differently-
sized model under the same methodology. The likelier explanation for the
120b inversion, combining this with Finding 1 above, is some mixture of
(a) provider-level non-determinism/noise inflating variance run-to-run
at a level this project's single-seed budget re-runs weren't powered to
distinguish from a real trend, and (b) something specific to `gpt-oss-
120b` or that exact run that a 20b re-run on a different day cannot
recover. This closes the open item from Phase 23 to the extent it can be
closed without the original model.

**Limitation carried forward**: the matched-set analysis is itself only
as good as its n (184/172) and 1 seed — not powered to rule out a small
(~2-3pp) true effect, only a large one. It also cannot speak to `gpt-oss-
120b` directly. Anyone re-opening this question should budget for the
timeout-skip effect discovered here: a naive multi-budget comparison on
this endpoint needs either a matched-question design (as done here) or a
much longer `LLM_HTTP_TIMEOUT_SEC` at high budgets, or its accuracy
numbers will conflate a real effect with a skip-driven selection
artifact.
