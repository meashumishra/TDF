"""Per-column dictionary encoding for tables.

The phrase dictionary in `optimize.py` only ever saw prose -- `_iter_texts`
yields Para/Quote/Heading/Figure and nothing else. That blindness is expensive:
on a 282k-token World Bank extract the phrase dictionary found *zero*
candidates, because the redundancy in tabular data does not live in sentences.
It lives in columns, where a few hundred distinct values repeat thousands of
times.

This is the standard trick from columnar stores (Parquet/ORC dictionary
encoding), applied to a token budget instead of a byte budget. For a column
whose cardinality is low relative to its height, every cell is replaced by a
short code and the mapping is declared once.

Two measured facts drive the design:

1. Cardinality really is low. On the World Bank table, `Country` has 262
   distinct values across 13,978 rows and `Year` has 64. Dictionary-encoding
   the eligible columns is worth 49,918 tokens, 25.9% of the table body --
   against 2,320 tokens for the phrase dictionary across the *entire* corpus.

2. Codes must be letters, not numbers. Under o200k_base a leading space merges
   into a lowercase code (`" a"`, `" ab"` = 1 token) but never into a digit
   (`" 0"`, `" 12"` = 2 tokens). Using 0..n would therefore cost double.
   `a..z` then `aa..zz` yields 26 + 676 codes, 649 of which are a single token.

Run-length ("ditto") encoding was measured as the alternative and lost on every
table -- 19.6% vs 25.9% on World Bank -- because it can only exploit *adjacent*
repeats, and it degrades to nothing if the table is not sorted on that column.
"""

from __future__ import annotations

import string
from dataclasses import dataclass

from .ir import Doc, Table
from .tokens import count

# A column must be at least this tall before a legend line can pay for itself.
MIN_ROWS = 12
# Cardinality ceiling, as a fraction of column height.
MAX_CARDINALITY_RATIO = 1 / 3
# Values already this cheap cannot be beaten by a code plus its legend entry.
MIN_VALUE_TOKENS = 2
# Margins that keep a marginal column from coming out worse than leaving it alone.
MIN_SAVING = 40
MIN_SAVING_RATIO = 0.10

_ALPHABET = string.ascii_lowercase


def _codes(n: int) -> list[str]:
    """Generate n codes, cheapest first: a..z, then aa..zz."""
    out = list(_ALPHABET[:n])
    if n <= len(_ALPHABET):
        return out
    for a in _ALPHABET:
        for b in _ALPHABET:
            out.append(a + b)
            if len(out) >= n:
                return out
    for a in _ALPHABET:  # pragma: no cover - 17k columns is not a real document
        for b in _ALPHABET:
            for c in _ALPHABET:
                out.append(a + b + c)
                if len(out) >= n:
                    return out
    return out


@dataclass
class ColumnCode:
    """One dictionary-encoded column.

    The table is held by reference rather than by index, because later passes
    (boilerplate removal, tiering) insert and delete blocks and would silently
    invalidate a positional reference.
    """

    table: Table
    column: int
    header: str
    mapping: dict[str, str]  # code -> original value

    @property
    def inverse(self) -> dict[str, str]:
        return {v: k for k, v in self.mapping.items()}


def _eligible(values: list[str], reserved: set[str]) -> dict[str, str] | None:
    """Decide whether coding this column actually saves tokens, and by how much.

    Returns a value->code mapping, or None if it does not pay.
    """
    present = [v for v in values if v]
    if len(present) < MIN_ROWS:
        return None

    distinct = sorted(set(present))
    # A constant column is the `!F` rule's job and it does it for free.
    if len(distinct) < 2:
        return None
    if len(distinct) > max(1, int(len(present) * MAX_CARDINALITY_RATIO)):
        return None

    # A column of already-cheap values (single tokens, short numbers) cannot win.
    if max(count(v) for v in distinct) < MIN_VALUE_TOKENS:
        return None

    # Never emit a code that could be mistaken for a literal value anywhere in
    # the table, otherwise decoding is ambiguous.
    codes = [c for c in _codes(len(distinct) + len(reserved) + 8) if c not in reserved]
    if len(codes) < len(distinct):
        return None
    codes = codes[: len(distinct)]

    before = sum(count(v) for v in present)
    mapping = dict(zip(distinct, codes))
    after = sum(count(mapping[v]) for v in present)
    legend = sum(count(v) + count(mapping[v]) + 1 for v in distinct) + 3

    # Demand a real margin. The estimate ignores separator and quoting effects,
    # so a column predicted to break even can come out slightly *worse*.
    saving = before - (after + legend)
    if saving < MIN_SAVING or saving < before * MIN_SAVING_RATIO:
        return None
    return mapping


def encode_columns(doc: Doc, enabled: bool = True) -> list[ColumnCode]:
    """Replace low-cardinality table columns with short codes.

    Returns the codebooks, which the emitter declares so the model can decode.
    """
    if not enabled:
        return []

    books: list[ColumnCode] = []
    for block in doc.blocks:
        if not isinstance(block, Table) or len(block.rows) < MIN_ROWS:
            continue

        # `Table.cols` is the header; every entry of `rows` is data. Reading the
        # header off rows[0] both mislabels the codebook and leaves the first
        # data row uncoded, so it would show a literal among codes.
        header, body = block.cols, block.rows
        # Any short literal appearing in the table is off-limits as a code.
        reserved = {c.strip() for row in block.rows for c in row if len(c.strip()) <= 3}

        for ci in range(len(header)):
            values = [row[ci] for row in body if ci < len(row)]
            mapping = _eligible(values, reserved)
            if not mapping:
                continue

            for row in body:
                if ci < len(row) and row[ci] in mapping:
                    row[ci] = mapping[row[ci]]

            books.append(
                ColumnCode(
                    table=block,
                    column=ci,
                    header=header[ci] if ci < len(header) else f"col{ci}",
                    mapping={v: k for k, v in mapping.items()},
                )
            )
            reserved |= set(mapping.values())

    return books


def decode_columns(books: list[ColumnCode]) -> None:
    """Invert `encode_columns` in place -- the encoding is fully lossless."""
    for book in books:
        for row in book.table.rows:
            if book.column < len(row) and row[book.column] in book.mapping:
                row[book.column] = book.mapping[row[book.column]]
