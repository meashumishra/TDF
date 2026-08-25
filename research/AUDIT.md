# TDF Repository Audit (Phase 1) — Loss Points, Ambiguities, Claim Inventory

*Audited 2026-08-24 against commit series `196bf6a..da1cf42`. This document is
the map required before further modification; every item cites the code that
proves it.*

## Pipeline map (as implemented)

```
Document (.pdf/.docx/.xlsx/.pptx/.html/.csv/.md/.txt)
   ↓  tdf/readers/*            ← READER losses happen here (L1, L2)
Intermediate Representation (tdf/ir.py: Doc → typed blocks)
   ↓  tdf/optimize.py          ← optional transforms (dictionary §n, hygiene);
   ↓                             boilerplate OFF by default (BUG-4 fix)
TDF transformation             ← columnar !V codebooks, ^ elision, !F hoisting,
   ↓                             periodic headers (all inside emit._tdf_table,
   ↓                             reversed unconditionally by parse_tdf)
Emitter (tdf/emit.py)          ← hybrid arbitration lives here too
   ↓
TDF text  ⇄  parse_tdf (tdf/parse.py)   ← GFM pipe tables, KV escaping
   ↓
LLM (consumes text directly)
```

## Loss-point register

| ID | Where | What | Class | Evidence |
|----|-------|------|-------|----------|
| L1 | readers | Link targets (`href`) are never captured — visible text only | READER-LOSS (info destroyed before IR) | `grep href tdf/readers/*` → empty |
| L2 | ir.ListBlock | No nesting: `items: list[str]`; indented sub-lists flatten | READER/IR-LOSS | ir.py:26-28 |
| L3 | emit `_oneline` | Newlines/tabs inside cells, titles, quotes, gists collapse to spaces | FORMAT-NORMALIZED (declared) | emit.py:161-177 |
| L4 | parse line.strip() | Leading/trailing whitespace on any single-line field never survives | FORMAT-NORMALIZED (declared) | fidelity.canonicalize docstring #2 |
| L5 | pipe-table reader | Cell/name whitespace trimmed (GFM behaviour) | FORMAT-NORMALIZED (declared) | parse._split_pipe_row |
| L6 | Quote("") / Para("") / Heading("") / blank list items / blank-named columns / zero-row tables | Degenerate containers have no wire form that re-types identically | FORMAT-AMBIGUITY (documented; assumed away in property suites both existing and hybrid) | test_properties.py:181-195; test_hybrid.py assumes |
| L7 | PageMark/Elision markdown forms | `- **k:** v`, `> *[...]*`, `---\n*Page n*` do not re-type as KV/PageMark/Elision | FORMAT (reason hybrid forces these dense) | emit.render_hybrid force-list |
| L8 | tier() | Index-like regions replaced by `!E` (gist only) | DECLARED LOSSY (opt-in, addressable) | tier.py |
| L9 | skeleton mode | Body dropped by design | DECLARED (navigation format) | emit.render_skeleton |
| L10 | optimize() text hygiene | Number/date normalisation edits strings (reversed nowhere) | FORMAT-NORMALIZED (only when optimized=True) | optimize.clean_text |
| L11 | readers | Footnotes/citations/merged cells/multi-stream PDFs: no IR nodes | READER-GAP (unsupported structures, §8) | ir.py block set |

**Unsupported/partially-supported structures to declare formally (§8):**
nested lists, merged cells, multiline (Alt+Enter) cells (newline collapses),
link targets, footnotes, image binary refs (Figure is description-only),
multi-column PDF layouts beyond the alignment heuristic.

## Ambiguity surfaces (attack surface for §6)

Sigil vocabulary: `!H !D !R !T !F !C !V !K !G !P !E %TDF1`, caret `^`,
section refs `§n`, KV separator `": "`, escape `"!"` prefix, fence backticks,
pipe rows (new). Known-hardened: leading-bang body escaping, sigil-must-be-
followed-by-space, KV colon escaping, variable-length fences, caret-run
lengthening, pipe-delimiter requirement (next-line check). Open questions for
adversarial phase: §n collision with literal `§` user text, `!E` id squatting,
delimiter-row false positives on prose like `| --- |` poetry, CJK width
characters inside cells, RTL text ordering through `_split`.

### Phase-4 outcomes (tests/test_adversarial.py, 194 cases)

| Surface | Verdict |
|---|---|
| Sigil-shaped body text (`!T 5 fake`, `%TDF1 rogue`, ...) | **RESOLVED** — bang-escaped on emit; round-trips as content in both emitters |
| Literal `§N` vs dictionary numbering | **ALREADY HARDENED** — `_reserved_section_refs` scans every expand surface; regression test added (dictionary skips reserved numbers; literal survives) |
| Pipe-led prose + delimiter-lookalike (new risk from GFM reader) | **RESOLVED at two layers** — emitter bang-escapes single-line marker-less fragments starting with `\|`; parser additionally requires a non-empty header cell or ≥1 data row |
| Fullwidth/homoglyph sigils (`！Ｔ`), CJK, Arabic RTL | **SAFE by construction** — sigil detection is ASCII-exact; all round-trip clean |
| Resource bombs (100 KB line, 20k caret run, 5k fence run, 3k blocks) | **BOUNDED** — linear handling, all round-trip exact, worst case < 30 s |
| Malformed/truncated wire (21 shapes) | **DEGRADES SAFELY** — never raises; partial structures returned |
| Known-inherent (documented, not fixed) | KV-followed-by-colon-Para adjacency; empty Para/Quote/Heading/list-item/blank-container wire forms (canonicalize normalizes both sides) |

## Claim inventory (seed for Phase 13)

| Claim (location) | Status |
|---|---|
| "reversible" / round-trip | SUPPORTED for supported shapes (canonicalize-equality, property-tested); PARTIALLY_SUPPORTED overall due to L3-L7 normalization class |
| "100% distinct-content recall" (samples) | PROVEN *as a bag-of-words metric on tested docs* — must never again be cited as semantic/structural proof (brief §0/§3) |
| "tokenizer-independent (<0.5pp)" | SUPPORTED (measured, two tokenizers) |
| "never larger than Markdown" (hybrid) | PROVEN by construction + property test |
| "cuts tokens roughly in half" (intro) | PARTIALLY_SUPPORTED — true for table/boilerplate-heavy only; prose ~2% (README states this) |
| "accuracy preserved" | FALSE as stated anywhere → replaced by measured −6.3pp marginal verdict |
| "production ready" | UNSUPPORTED — no multi-model, no perf bench yet |
