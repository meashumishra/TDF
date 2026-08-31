# Phase 13: Reasoning-Aware Optimizer Audit

*Audited 2026-08-27 against commit `c9d1e35`. Scope: mission §3-9 (Context IR
through Reasoning-Aware Optimizer) as implemented in `tdf/ir.py`,
`tdf/optimize.py`, `tdf/tier.py`, `tdf/columnar.py`, `tdf/selector.py`,
`tdf/context_service.py`, `tdf/fidelity.py`, `tdf/fidelity_structural.py`.
Every verdict below cites the code (or the grep that found nothing).*

## Summary verdict

The mission's central ask in §7 — every transformation exposing
`tokens_before / tokens_after / token_savings / structural_risk /
semantic_risk / reasoning_risk`, combined via `score = token_savings -
λ1*structural_risk - λ2*semantic_risk - λ3*reasoning_risk` — **does not
exist**. A repo-wide grep for `structural_risk`, `semantic_risk`,
`reasoning_risk`, `lambda1`/`λ1`, and `token_savings` returns zero hits
outside this audit.

What exists instead are two different, non-equivalent substitutes:

1. **Hard-coded, failure-driven heuristic gates inside individual
   transforms** — real risk-awareness, but as compile-time constants tuned
   after a specific measured failure, never computed per-instance and never
   surfaced to a caller.
2. **`selector.py`'s `optimize_context`** — reasoning-aware only at the
   granularity of *whole representations* (Markdown vs Hybrid vs Skeleton),
   with a single categorical risk string, not a scored, per-transformation
   decision.

Neither is what §7 specifies. The protective effect §7 wants has partly been
achieved by (1) — see the anchor-protection example below — but without the
observability the mission requires: nobody can currently ask "what was the
structural/semantic/reasoning risk of this specific transformation on this
specific document," only "did the total token count go down."

## Section-by-section

### §3 Context IR — MOSTLY IMPLEMENTED, flat not hierarchical

`tdf/ir.py` covers Document/Heading/Para/Table/List/Code/Quote (`Doc`,
`Heading`, `Para`, `Table`, `ListBlock`, `Code`, `Quote`) plus KV, Figure,
PageMark, Elision — beyond what the mission listed. Table rows/cols enforce
a rectangular grid (`Table.__post_init__`, ir.py:38-48), so Row/Column/Cell
concepts exist implicitly.

Missing as first-class concepts: **Entity, Identifier, Reference, Metric,
Timestamp**. Every cell and text field is an untyped `str` — there is no
semantic tag distinguishing "this string is a date" from "this string is a
row identifier" from "this string is prose." This absence is *why* §8's
protected-information categories can't be enforced generically (see below):
there is nothing to check membership against.

Hierarchy is also flatter than the mission's parent/child model: `Doc.blocks`
is a single flat list; nesting is implied only by `Heading.level` integers,
not by actual parent/child pointers or nested children lists. `ListBlock`
cannot nest (`items: list[str]`, flagged already in `research/AUDIT.md` as
loss point L2). Provenance is per-document (`Doc.source`), not per-block —
`PageMark` blocks interleave page boundaries into the flat list rather than
tagging each block with its origin page.

### §4 Semantic Tree — MISSING

The mission's worked example (`India | 2024 | 100` / `2025 120` / `2026 150`
→ nested under one `India` parent) has no implementation. `Table` carries a
`group: str = ""` field (ir.py:36) that looks like it was meant for exactly
this, but it is dead: no reader ever sets it and no emitter ever reads it
(`grep -n "\.group\b" tdf/*.py` returns only unrelated `re.Match.group()`
calls). `drop_constant_columns` (optimize.py:167-195) factors a column that
is constant across *every* row in the table — it does not detect or nest
runs where a key column repeats for a contiguous block of rows before
changing (the actual "inheritance compression" scenario in the mission's
example). This is a genuine, currently-unaddressed gap, not a
partially-covered one.

### §5 Language Compression — split verdict per sub-item

- **A. Frequency detection — IMPLEMENTED.** `build_dictionary` +
  `repair.repair_candidates` do maximal-repeat phrase mining over the whole
  document (optimize.py:375-479).
- **B. Trie/prefix compression — MISSING.** No shared-prefix factoring of
  identifier-like strings (the `customer_id`/`customer_name`/... example)
  anywhere in the codebase; grep for `trie`/`prefix_compress`/
  `shared_prefix` returns nothing relevant.
- **C. Phrase dictionary — IMPLEMENTED, and exceeds the ask.** Two
  mechanisms cover this: the prose-level `§n` dictionary above, and
  `tdf/columnar.py`'s per-column value dictionary encoding, which the
  module's own docstring reports finding *zero* prose-dictionary candidates
  on a 282k-token tabular extract while column dictionary-encoding saved
  25.9% of that table's body — i.e. the two mechanisms cover disjoint
  redundancy classes and both are needed.
- **D. Template extraction — MISSING.** No detection of parameterized
  templates with typed slots ("Revenue in {country} increased to {value}").
  The phrase dictionary only substitutes exact, fixed multi-word spans; nothing
  detects that many sentences share a fill-in-the-blank shape.

### §6 Structural Compression — split verdict per sub-item

- **Parent/context factoring — PARTIAL.** Only whole-column constants
  (`drop_constant_columns`); no factoring of a value shared by a contiguous
  *group* of rows (would require §4's semantic tree first).
- **Repeated subtree detection — MISSING.** `tdf/diff.py` finds structural
  deltas *between two document versions*, which is a different problem from
  detecting a repeated substructure *within one document*.
- **Constant-column factoring — IMPLEMENTED.** `drop_constant_columns`,
  including the original-column-index fix from the independent audit's
  BUG-1 (optimize.py:173-177).
- **Repeated record factoring — PARTIAL, and the one confirmed fix here is
  UNSHIPPED.** `elide_repeats` (optimize.py:198) collapses a cell identical
  to the one directly above it, column by column, with **no anchor
  protection anywhere** — and this is what `tdf/emit.py:267`'s `_tdf_table`
  actually calls, meaning every real `tdf convert` / `render_tdf` output
  today can caret-elide column 0 exactly as freely as any other column.
  `elide_repeats_keep_anchor` (optimize.py:216), which protects column 0
  after Phase-5 failure analysis showed caret-eliding a lookup key caused
  the dominant row_association accuracy loss, is **never called from the
  default emission path at all** — its only caller is
  `eval/formats/encode.py`'s `encode_tdf_nocaret0`, an exploratory eval arm
  that monkeypatches it in via `unittest.mock` purely to *measure* the idea.
  Worse: that arm has **zero rows in the v1 accuracy run**
  (`eval/results/archive_v1_256tok/raw.jsonl` has 789 rows each for md,
  json, toon, tdf_full, tdf_hoist, tdf_nodict, tdf_nocodes, tdf_nocaret,
  hybrid — and none for tdf_nocaret0). So the fix is not just under-
  generalized past column 0 (the original version of this finding); it was
  **never shipped, and never empirically validated** — it is a plausible,
  well-motivated idea supported by real failure analysis of the *problem*,
  but the *remediation* itself has no accuracy evidence behind it yet. The
  v2 budget re-run launched alongside this audit (§14) includes
  `tdf_nocaret0` in its arm set and will produce the first real measurement;
  shipping this into the default pipeline should wait for that result
  rather than happening on the strength of the reasoning alone. A table
  whose primary key lives in a column other than 0 gets no equivalent
  candidate protection either way; nothing detects "which column is the
  identifier" generically (traces back to §3's missing Identifier type).
- **Inheritance compression — MISSING.** Same gap as §4.
- **Safe reference sharing — IMPLEMENTED.** `§n` phrase references and `!V`
  column codebooks are both declared, reversible reference schemes.

### §7 Reasoning-Aware Optimizer — the central gap

Already summarized above. Concretely, here is everything in the codebase
that plays a role resembling this section, and why none of it satisfies it:

| Mechanism | Risk-awareness it actually has | What it's missing vs. §7 |
|---|---|---|
| `elide_repeats_keep_anchor` (optimize.py:216) | Column-0 protection motivated by a *measured* accuracy failure (the underlying row_association loss is real) | Not wired into the default pipeline at all (`emit._tdf_table` calls plain `elide_repeats`); its own accuracy impact has never been measured (zero rows in the v1 run); fixed rule even if shipped, not a computed score; doesn't generalize past column 0; exposes no risk number |
| `tier.is_index_like` (tier.py:44-46) | `MIN_TOKENS=120`, `MAX_DENSITY=0.6` gate elision to genuinely index-like spans | Two hand-picked constants, not a risk score; no reasoning_risk component at all (an index block could still be reasoning-relevant) |
| `build_dictionary` acceptance (`repair.select`, optimize.py:448-454) | `min_occurrences`, `min_phrase_tokens` thresholds bound how aggressively phrases get pulled out | Purely a token-accounting threshold (see the `saving = ...` arithmetic in the docstring) — no structural/semantic/reasoning risk term at all |
| `selector.select_representation` (selector.py:41-112) | Picks Markdown/Hybrid/Skeleton by literally rendering and measuring each; skeleton labeled `"high"` risk because bodies are dropped | One categorical string for the *whole document*, not per-transformation; no λ weights; no breakdown into structural/semantic/reasoning components |
| Accuracy-per-token harness (`eval/`, README ablations) | The only place actual reasoning_risk gets measured — e.g. "removing `§n`, `!V` or `^` recovers ≤0.1pp each" | Post-hoc, experiment-only; not consulted by `optimize.py` at compile time; no feedback loop wiring a measured ablation delta back into a threshold |

None of these compose into the mission's objective function. The system
today is "apply a fixed set of transforms whose thresholds were each hand-
tuned against a specific past failure," not "score every transform's
risk/reward for this document and decide." The former has produced some
real safety (the anchor fix), but it's not inspectable or tunable the way
§7 asks, and it can't answer "would this specific compression on this
specific document be safe" for anything the hand-tuned rules didn't already
anticipate.

### §8 Protected Information — safe today mostly by construction, not by policy

No explicit classifier exists for *any* of the mission's listed categories
(IDs, numbers, dates, units, names, URLs, paths, DB keys, legal clauses,
negations, conditions). What protects them today:

- **Numbers** — genuinely protected: `normalize_cell` explicitly refuses to
  guess trailing-zero precision (optimize.py:108-118), citing the
  independent audit's BUG-3.
- **Row identifiers** — **not protected in the shipped default pipeline at
  all**; the column-0 anchor protection exists in the codebase but is only
  reachable through an unshipped, unmeasured eval arm (see §6 above).
- **Column identifiers (headers)** — incidentally safe: no current pass
  ever rewrites header text lossily.
- **Dates, units, URLs, file paths, DB keys, legal clauses, negations,
  conditions** — no dedicated handling anywhere. They are safe today only
  as a side effect of every implemented transform being either exact/
  reversible (dictionary and columnar substitution are both exact-text) or
  gated by an orthogonal structural signal (column-wide equality, sentence
  density) that happens not to fire on ordinary prose containing them.
  **There is no regression test asserting a negation-bearing sentence, a
  URL, or a file path survives every transform unchanged** — per mission
  rule #9 ("every discovered failure becomes a regression test"), this is
  an audit gap to close with tests before it's a confirmed bug, not after.

### §9 Fidelity — the best-aligned section of the mission

`tdf/fidelity.py` (bag-of-words/content) and `tdf/fidelity_structural.py`
(ordering_accuracy, table_cell_accuracy, heading_accuracy, code_exact_accuracy
— Phase 3) together already implement exactly the split the mission asks
for: a content metric that can't distinguish `Alice|100,Bob|200` from
`Alice|200,Bob|100`, plus a structural metric that can. No "reasoning
fidelity" or a metric literally named "relationship fidelity" exists, but
the substance — per-aspect rates with explicit denominators — is present
under the fidelity_structural.py naming.

### §10 Query-Aware Compression — MISSING, consciously deferred

Not implemented, and `research/opportunities.md`'s "Deliberately not
recommended (yet)" section explicitly argues for deferring it until the
accuracy harness lands. This matches the mission's own framing of query-
awareness as an *optional* later phase, so it reads as a disclosed decision
rather than an oversight.

### §11 Lazy Context — well implemented, matches spec closely

`tier.py` + `context_service.py` give every elided region a stable id
(`x1..xN`), a kind (`"index"`), an exact token count (`tdf.tokens.count`,
not an estimate), a gist, and an expansion mechanism (`expand_region`/
`tdf expand-elided`). This is the mission's §11 checklist item-for-item and
is independently flagged in `research/opportunities.md` as the highest
novelty-per-effort opportunity, already built.

### §15 LLM Usage — compliant

`grep` for `openai|anthropic|requests.post|api_key|chat.completions` across
`tdf/*.py` returns one hit, a code comment (`optimize.py:34`, discussing the
identifier `api_key_secret` as a regex example) — not an actual call. The
core encoder path makes zero LLM calls; the only LLM usage in the repo lives
in `eval/` (QA grading), which is optional and outside the compiler.

## Recommendation for next iteration

Priority order, cheapest-and-most-load-bearing first:

1. **DONE — §8 test gap closed.** `tests/test_protected_information.py`
   (Phase 14) now runs negation, URLs, file paths, dates, leading-zero and
   near-duplicate IDs, conditional clauses, and column headers through the
   full default pipeline and asserts character-exact survival. Writing that
   suite is also what surfaced the correction to recommendation #2 below —
   its first draft assumed column 0 was protected and failed to catch that
   the real default path isn't, until the test was pointed at column 0
   directly.
2. **Ship or explicitly shelve the already-written anchor fix — do not
   generalize it before either.** Correction to the original version of
   this recommendation: `elide_repeats_keep_anchor` is not "real and
   measured-necessary, just under-generalized" — it is **not called from
   the default pipeline at all** (`tdf/emit.py`'s `_tdf_table` calls plain
   `elide_repeats`; the only caller of the anchor-protecting version is
   `eval/formats/encode.py`'s exploratory `tdf_nocaret0` arm, reached via a
   `unittest.mock` patch), and that arm **has zero measured accuracy rows**
   in the v1 run. So today, column 0 gets caret-elided in real `tdf
   convert` output exactly like every other column — the Phase-5 fix exists
   in the codebase but has never shipped or been validated. The §14 budget
   re-run launched alongside this audit includes `tdf_nocaret0` and will
   produce the first real accuracy measurement; the correct next step is to
   read that result and then either (a) wire `elide_repeats_keep_anchor`
   into `_tdf_table` by default if it doesn't cost accuracy elsewhere, or
   (b) document it as a validated-but-rejected idea if it does. Generalizing
   protection past column 0 (the heuristic idea from the original version of
   this recommendation — lowest-cardinality-relative-to-height, or a column
   name matching `id|key|code`) is real follow-up work, but it is premature
   until the column-0 version is even shipped and measured.
3. **Build §7 as a thin, additive layer, not a rewrite.** Don't replace the
   existing hand-tuned gates — wrap each existing transform with a function
   that reports `(tokens_before, tokens_after, token_savings)` (trivial,
   already computable from `tdf.tokens.count` before/after) and a
   *placeholder* risk breakdown seeded from the already-known failure modes
   (e.g., caret-elision on a non-anchor column = nonzero reasoning_risk,
   citing the exact Phase-5 finding that motivated the anchor fix). Getting
   the reporting shape in place first is what makes the λ-weighted score
   tunable later, and it's what the mission's §7 output contract actually
   asks for even before the weights are tuned.
4. **Semantic Tree (§4) and inheritance compression (§6) are the largest
   unimplemented piece of the original spec** and should be scoped as their
   own phase — they're a precondition for "parent/context factoring" beyond
   whole-column constants, not a small addition to `optimize.py`.
5. **Trie/prefix compression (§5B) and template extraction (§5D)** are
   real gaps but lower priority than the above: the existing phrase
   dictionary and columnar encoding already capture most of the same
   redundancy in the corpus profiles seen so far (columnar.py's own
   evidence: 25.9% of a table body from column dictionary-encoding alone).
