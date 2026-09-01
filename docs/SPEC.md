
## Semantic-tree grouping (`!N`, `@`)

**Experimental, opt-in** — `render_tdf(doc, use_grouping=True)` / not yet exposed on the `tdf convert` CLI. Detection lives in `tdf/tree.py` (mission section 4); this section documents the wire form `tdf/emit.py`/`tdf/parse.py` produce and read when it fires.

When column 0 of a table has repeated values across contiguous runs of rows (e.g. a sorted-by-entity export), stating that value once per run — as a legible, literal group header — can cost fewer tokens than either repeating it per row or caret-eliding it. Caret-elision was the pre-existing option, but Phase-5's failure analysis found that caret-eliding a row's lookup key removes its identity from the wire, which specifically hurts row-association accuracy; a group header keeps the entity as literal text instead.

```
!T 5
!N 0:country
!C year value
@ India
2024 100
2025 120
2026 150
@ Brazil
2020 90
2021 95
```

- `!N <idx>:<name>` declares that column `<idx>` (in the `!C` index space that follows) is a group key. `<idx>` is always `0` in the current implementation — only a leading group column is detected.
- `!C` lists every column **except** the group key — one field narrower than an ungrouped table's `!C` line.
- `@ <value>` opens a group: every row until the next `@` line (or the table's end) belongs to it. The value is quoted the same way a cell is (`_quote`/`_split`) if it contains a space or `"`.
- Member rows are always space-separated, never tab-separated — tab mode has no quoting mechanism, so it has no way to escape a member row whose first field starts with `@` (which would otherwise be indistinguishable from a new group header). A member row's first cell is force-quoted if it starts with `@`, the same defensive pattern `^` collision handling already uses for caret-elision.
- Grouping only fires when it is net token-positive across the *whole* table, including per-group header overhead for every run (singleton runs included) — see `tdf/tree.py`'s `group_savings_report`. A table where it doesn't pay falls back to the existing caret-elision behavior unchanged.
- `!N`/`!C` (and `!F`, if present) are re-emitted at the same 50-row periodic-header boundary as ungrouped tables, followed by a `@` line re-declaring whichever group was active at that point — so a reader who jumps to a re-emitted header still knows which entity the following rows belong to.
- Coexists with `!F` (constant-column factoring, disjoint columns) and `!V` (columnar codebooks, decoded after the group column is reinserted) without special-casing either.

## Structural Diffing

TDF provides a structured diff mode (`!DIFF`) that captures changes between two versions of a document. It operates at block granularity for text and cell granularity for tables, removing the noise of standard text diffs (like reflowed paragraphs or page breaks).

- `!DIFF <old-name> -> <new-name>`: Declares the start of a diff document.
- `!= <n>`: `<n>` consecutive structurally-identical blocks were skipped.
- `!~ <region>`: The block at `<region>` was modified. It is followed by `-` lines (old content) and `+` lines (new content), or `~` lines for modified table rows.
- `!+ <region>`: A block was inserted. Followed by `+` lines.
- `!- <region>`: A block was removed. Followed by `-` lines.

For tables, unmodified rows are omitted. Modified rows use `~` followed by tab-separated cells. Cells that changed are rendered as `<old>-><new>`.

## Key/value escaping (`!K`)

Each `!K` continuation line is `key: value`, split on the first **unescaped** colon. Because values legitimately contain colons (times, URLs, timestamps), the *key* side carries the escaping burden:

- **Emitter:** in keys, `\` → `\\` first, then `:` → `\:`. Keys without colons or backslashes pass through byte-identical.
- **Parser:** scan left to right, skipping any backslash plus the character it quotes; the first colon outside an escape pair is the separator. The key is then decoded (`\\` → `\`, `\:` → `:`). Unknown escapes are preserved verbatim, so legacy keys containing bare backslashes keep parsing exactly as before.
- **Values** are never escaped or decoded: everything after the separator colon is taken verbatim.

Round-trip guarantee: emit followed by parse restores any key exactly — including keys containing colons, backslashes, or both.

## Hybrid mode (`--to hybrid`)

Per-block format arbitration. Each block is emitted in whichever encoding tokenises cheaper: prose stays native Markdown; repetitive tables, KV runs, page marks, elisions and ordered lists drop into their dense sigil forms (the last three *always* — their Markdown shapes do not re-parse as themselves). Two enforced guarantees:

- **Floor:** the output is never larger than ``render_markdown(doc)``. Arbitrated fragments must beat or tie their own Markdown twin; if the fixed-cost legend would break the balance, it is shed and the winning dense fragments remain.
- **Losslessness:** ``parse_tdf`` restores the original blocks from either assembly. To make this hold, ``parse_tdf`` also reads GFM pipe tables (header row, ``---`` delimiter row, data rows, ``\|`` escapes honoured) — so a Markdown-side table still re-types as a Table.

Title spelling follows the assembly (``!H`` when sigils are present, ``#`` when the document stayed pure-Markdown), matching each grammar's own round-trip semantics.
