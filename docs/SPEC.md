
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
