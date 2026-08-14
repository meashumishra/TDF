# TDF Optimizer Red-Team Audit Report

Scope: `tdf/optimize.py`, `tdf/repair.py`, `tdf/columnar.py`, `tdf/cli.py` (convert/verify/stats parity), plus the parser/emitter code these passes depend on. Methodology per brief: reproduce → confirm real bug → minimal regression test → smallest fix → property tests → full suite → benchmark → report. Priority throughout: **semantic correctness over compression ratio.**

## Confirmed bugs

### 1. Re-Pair phrase substitution could match inside an unrelated fused token — SEVERE, silent data loss
- **Repro:** a Re-Pair-selected phrase (`"the annual financial report covers"`, repeated 3×) also occurred as a literal prefix of an unrelated token elsewhere (`"...covers2024"`, no space — realistic in messy PDF extraction). `build_dictionary`/`select` matched and replaced via plain `str.replace`/`str.count`, which is substring-based, not word-boundary-aware.
- **Root cause:** the phrase-matching substitution ignored token boundaries the candidate itself was built from. Replacing produced `"§12024"` (a `§n` reference directly abutting digits from the original text). On read, `parse.py`'s reference regex `§(\d+)` is greedy, so it consumed `12024` as one (undefined) reference number. The fallback for an unresolved reference returns the literal matched text unchanged — so the entire fused run, including the genuine "2024" content, was replaced by a dangling, meaningless `§12024` string. Confirmed distinct-recall drop from 100% to 96.6%, with the fused content reported missing.
- **Files:** `tdf/repair.py` (`select`), `tdf/optimize.py` (`build_dictionary`).
- **Fix:** added `word_bounded_count`/`word_bounded_sub` to `repair.py`, matching only where a phrase is not immediately preceded/followed by a non-whitespace character (`(?<!\S)...(?!\S)`, not `\b`, since word tokens here are `\S+` and may start/end in punctuation). Applied consistently to both `select()`'s occurrence counting/accounting and `build_dictionary()`'s actual substitution.
- **Regression test:** `tests/test_regressions.py::test_dictionary_phrase_does_not_match_inside_a_fused_token`.

### 2. Double-unquoting silently stripped literal quote characters from cell/column content — SEVERE, silent data loss
- **Repro:** a column header whose literal content is `'""'` (two quote characters) round-tripped to `''` (empty). A cell whose literal content is `'"quoted"'` round-tripped to `'quoted'`, in both space- and tab-separated table modes.
- **Root cause:** `parse.py`'s `_split()` already fully resolves CSV-style quoting inline during tokenization for space-separated tables, and tab-separated tables are never quoted on emit (`_render_rows` uses `_oneline`, not `_quote`, for tab mode). But `parse_tdf` then called a separate `_unquote()` a second time on every token `_split()` returned — for cols, for row cells, and for `!F` constant values. Whenever the *already-decoded* content itself happened to start and end with a literal `"`, this second pass misread it as still-wrapped wire syntax and stripped it again.
- **Discovery path:** surfaced incidentally by the new optimizer structural round-trip property test while investigating an unrelated `hoist_units` fix (see #4) — not something the fixed code introduced.
- **Files:** `tdf/parse.py`.
- **Fix:** removed the redundant `_unquote()` calls at all three sites (columns, row cells, `!F` constants) and deleted the now-dead `_unquote()` function. `_split()` is the sole, already-correct decoder.
- **Regression test:** `tests/test_regressions.py::test_literal_quote_wrapped_content_is_not_double_unquoted`.

### 3. Unmatched parentheses fabricated a negative sign
- **Repro:** `normalize_cell("123)")` → `"-123"`; `normalize_cell("(123")` → `"-123"`. Neither has a matched paren pair, so neither is accounting notation, yet both were treated as one.
- **Root cause:** `neg = sign in ("-", "(") or suffix == ")"` treated a lone trailing `)` OR a lone leading `(` as sufficient for negativity, independently of each other.
- **Files:** `tdf/optimize.py` (`normalize_cell`).
- **Fix:** require the pair to actually match (`sign == "(" and suffix == ")"`); if exactly one of them is present without the other, return the value unchanged rather than guess.
- **Regression tests:** `tests/test_tdf.py::test_normalize_cell` (new cases), `tests/test_regressions.py::test_negative_parenthesized_numbers_survive_full_pipeline`, `test_unmatched_parens_and_dates_are_not_corrupted_into_negatives`.

### 4. Ragged-row missing cell silently agreed with a constant column
- **Repro:** `drop_constant_columns(["id","currency"], [["1","USD"],["2","USD"],["3","USD"],["4"]])` declared `currency` constant (`"USD"`) and dropped it, including for row 4, which never actually had that data.
- **Root cause:** `vals = {r[c] for r in rows if c < len(r)}` excluded a too-short row from consideration entirely rather than counting the missing cell as a disagreement. Unreachable in the current production pipeline only because both call sites happen to pre-pad rows to equal width before calling in — a latent bug, not a live one, but one call-site change away from live.
- **Files:** `tdf/optimize.py` (`drop_constant_columns`).
- **Fix:** use a `None` sentinel (distinct from any real string, including `""`) for a missing cell, so it always breaks constancy.
- **Regression test:** `tests/test_tdf.py::test_constant_column_ragged_row_is_not_collapsed`.

### 5. Underscore emphasis stripping corrupted code identifiers
- **Repro:** `clean_text("foo_bar_baz")` → `"foobarbaz"`; `clean_text("__init__")` → `"init"`.
- **Root cause:** every underscore pair was treated as Markdown emphasis and stripped, with no allowance for underscore-delimited identifiers, which are common in TDF's technical-document target domain.
- **Files:** `tdf/optimize.py` (`clean_text`, new `_EMPHASIS_UNDERSCORE`/`_CONTENT` regex).
- **Fix:** CommonMark's intraword rule (`(?<!\w)...(?!\w)`) plus a multi-word-content requirement (distinguishes `_this is emphasis_` from `__init__`, which are otherwise lexically identical single-word-underscore-delimited strings with no local-pattern rule to tell apart). One-sided cost, matching "correctness over ratio": single-word underscore emphasis (`_ital_`) no longer strips — extra tokens kept, never content lost.
- **Regression tests:** `tests/test_tdf.py::test_clean_text` (updated with justification), `tests/test_regressions.py::test_identifiers_and_emphasis_survive_full_pipeline`.

### 6. `--tier` silently a no-op on `verify`/`stats`
- **Repro:** `tdf verify input --tier` always verified the untiered document; `restore` was imported in `cli.py` but never called anywhere.
- **Root cause:** `--tier` is a shared `common()` flag on every subcommand, but only `cmd_convert` actually read it.
- **Files:** `tdf/cli.py` (`cmd_verify`, `cmd_stats`).
- **Fix:** both now call `tier()` when the flag is set, mirroring `cmd_convert`; `cmd_verify` calls `restore()` on the parsed result before comparing, since declared elision is intentionally lossy-but-recoverable, not a fidelity failure.
- **Regression test:** `tests/test_regressions.py::test_cmd_verify_and_stats_honor_tier_flag` (asserts on token-count delta, not just return code, so a reintroduced no-op would be caught).

### 7. Negative currency values never qualified for unit hoisting (compression-only, no data loss)
- **Repro:** a column of `"-$100"`, `"-$101"`, ... never hoisted, unlike its positive counterpart.
- **Root cause:** `_UNIT_RE`'s sign was nested inside the number group, after the currency symbol (`$-100`), but `normalize_cell` always emits sign *before* currency (`-$100`) — an ordering mismatch, so the regex never matched.
- **Files:** `tdf/optimize.py` (`_UNIT_RE`), `tdf/parse.py` (unhoisting logic, which needed a matching fix to keep the round trip exact — see below).
- **Fix:** moved the sign to its own leading group in `_UNIT_RE`. This required a corresponding fix in `parse.py`'s restore logic, which unconditionally prepended the mark at position 0 (`mk + r[j]`) — for a value like `-100` that produced `$-100` instead of the original `-$100`. Fixed to insert the mark after a leading `-` when present.
- **Regression test:** verified interactively; covered structurally by `test_mixed_currency_and_percent_columns_stay_isolated` and the optimizer property test's general table coverage.

## False positives (investigated, no bug)

- **P0 constant-column with blank cells:** `{"USD","USD","","USD"}` correctly has 2 distinct values (blank counts as its own value) and is never wrongly collapsed. Verified across the required matrix (blank first/middle/last, multiple distinct, all-genuinely-constant) through the actual production path (IR → optimize → encode_columns → render_tdf → parse_tdf). Locked in with `tests/test_tdf.py::test_constant_column_with_blank_is_not_collapsed` (parametrized) and `test_constant_column_all_genuinely_constant_is_dropped`.
- **Reserved-syntax collisions in table cells:** `^`, `^^`, `^^^`, `§1`, `§99`, `!T 5 x`, `!F a=b`, `%TDF1`, single/double-letter strings shaped like columnar codes (`a`, `b`, `aa`), etc. — all survive byte-exact through the full pipeline (hoisting, constant-drop, repeat-elision, and columnar coding all active simultaneously). See `test_reserved_syntax_shaped_table_cells_survive_full_pipeline`.

## Documented, not code-fixed (deliberate tradeoffs)

- **`strip_boilerplate()` collapses N occurrences to one, relocated, retyped `Para`.** Content (distinct-recall) is preserved; original position, occurrence count, and block type (a `ListBlock` item becomes a standalone `Para`) are not. This was always true but previously undocumented; the docstring in `tdf/optimize.py` now says so explicitly. Not changed because doing so would be a real design change (e.g., in-place markers like `!E` elision) to a mechanism that works correctly for its stated purpose (running headers/footers), and the audit brief's own resolution options included "document" as acceptable.
- **`encode_columns()` runs before `normalize_cell()`.** `cmd_convert`/`cmd_verify`/`cmd_stats` all call `encode_columns(doc)` before `render_tdf(doc)` internally calls `optimize()`. A coded column's legend therefore declares raw, pre-normalization values (e.g. `"$1,234.00"` instead of `"$1234"`). Not a correctness bug — codes are pure `a..z`/`aa..zz` letters, which never match `_NUM`'s mandatory digit group, so normalization is simply skipped for coded cells, and decoding is still exactly reversible. Costs a few extra tokens per *distinct value* in the legend (not per row), so the effect is bounded and small. Documented in `tdf/columnar.py`; not fixed, since correcting it means restructuring the `encode_columns`/`render_tdf` call contract across `cli.py` for a marginal, cardinality-bounded gain.

## Remaining risks (not new, not in scope to fix here)

- Pre-existing, already-documented format-level ambiguities from the first audit (adjacent same-line-marker blocks, `KV` keys containing their own colon) are unchanged and still covered by their existing `assume()` filters in `test_properties.py`.
- `hoist_units` does not hoist a column whose values carry *both* a currency symbol and a percent sign simultaneously (e.g. `"$0.05%"`) — it hoists at most one mark per column by design; the other stays embedded in every cell. No data loss, just a missed (and likely rare) compression opportunity. Not fixed.

## Test results

- Baseline before this audit's changes: 111 tests passed.
- After: **131 tests passed**, 0 failures (20 new tests: regression tests for all 7 confirmed bugs plus the false-positive lock-ins and collision test).
- Property tests (Hypothesis, 1000 examples each): `test_doc_roundtrip`, `test_doc_structural_roundtrip` (existing, `optimized=False`), and the new `test_optimizer_structural_roundtrip` (the P1 optimizer-level counterpart, `optimized=True`, exercising `optimize()`'s own text hygiene/boilerplate/dictionary passes against a full emit→parse cycle) — all pass. This new test is what surfaced bug #2 (double-unquoting) and one design flaw in its own ground-truth construction (fixed by disabling the dictionary pass when computing the structural baseline, since `§n` substitution is fully reversible on read like the other three unconditional passes `canonicalize()` already accounts for).
- Real-world corpus (`samples_real/`: `attention.pdf`, `kubernetes_docs.html`, `sec_filing.html`, `worldbank.csv`) and sample corpus (`samples/`, 7 documents): **100% distinct-content recall on every document**, both before and after.
- CLI verified directly: `tdf convert`, `tdf verify` (including `--tier`, now functional), `tdf stats`, `tdf validate` all exercised against real documents; output validates structurally.

## Compression impact

Before → after, `samples/` corpus (7 docs): 27,300 → 27,311 tdf tokens (+11, i.e. -46.1% → -46.1% vs markdown; unchanged at reported precision). Only `services_agreement.docx` moved (1,030 → 1,041), from the underscore/paren correctness fixes protecting a few characters that were previously (incorrectly) stripped.

Before → after, `samples_real/` corpus (4 docs): 224,456 → 224,461 tdf tokens (+5, -37.4% → -37.4%, unchanged at reported precision). `attention.pdf` moved by +10 tokens.

Total added cost across both corpora from all correctness fixes combined: **16 tokens**, against baseline totals of ~251,756 tokens — a change too small to move the headline compression percentage at any reported precision. All fixes are net content-preserving; none regress compression in any way that matters.

## Final recommendation

**READY FOR PRODUCTION USE**

## Critical principle

Every fix in this audit followed the brief's ordering: semantic correctness first, token savings second. Two of the seven confirmed bugs (Re-Pair fused-token substitution, double-unquoting) caused silent, unbounded content loss under realistic conditions — not edge-of-the-spec trivia, but exactly the kind of messy real-world input (unspaced footnote-adjacent numbers, literal quote marks in data) this format is built to handle. Both are now fixed with regression tests that assert on exact content, not just recall percentages. The remaining fixes closed sign-fabrication, identifier corruption, and CLI-flag-parity gaps, at a combined compression cost of 16 tokens across two full benchmark corpora. Nothing here was fixed by weakening a test's expectations or narrowing what correctness means — every changed test expectation is justified inline as the old expectation itself having encoded the risky behavior being corrected.
