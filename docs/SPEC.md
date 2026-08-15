
## Structural Diffing

TDF provides a structured diff mode (`!DIFF`) that captures changes between two versions of a document. It operates at block granularity for text and cell granularity for tables, removing the noise of standard text diffs (like reflowed paragraphs or page breaks).

- `!DIFF <old-name> -> <new-name>`: Declares the start of a diff document.
- `!= <n>`: `<n>` consecutive structurally-identical blocks were skipped.
- `!~ <region>`: The block at `<region>` was modified. It is followed by `-` lines (old content) and `+` lines (new content), or `~` lines for modified table rows.
- `!+ <region>`: A block was inserted. Followed by `+` lines.
- `!- <region>`: A block was removed. Followed by `-` lines.

For tables, unmodified rows are omitted. Modified rows use `~` followed by tab-separated cells. Cells that changed are rendered as `<old>-><new>`.
