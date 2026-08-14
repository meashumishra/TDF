# Phase 3: Specification Validation

TDF Syntax (derived from emit/parse):
- Block separators: double newline `\n\n`
- Line prefixes:
  - `!H[1-6] `: Headings
  - `!P `: Paragraphs
  - `!Q `: Quotes
  - `!L `: Lists (ordered)
  - `!U `: Unordered lists
  - `!T <cols> <rows>`: Table definitions
  - `!D <count>`: Dictionary blocks (Re-Pair compression)
  - `!V`: Codebook values
  - `!E`: Elision markers
- Dictionary tokens in text: `§<index> `
- Escaping: `\` prefixes literal instances of `§`, `!`, and newline sequences inside cells.

Tests required for edge cases:
- Empty tables/columns.
- Unicode, emoji, nested dictionary references.
- Extremely long words.
