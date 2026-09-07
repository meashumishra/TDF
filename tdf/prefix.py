"""Mission section 5B: trie/prefix compression.

The mission's worked example is a set of sibling identifiers that share a
literal prefix (``customer_id``, ``customer_name``, ...); the real-world
case this module actually targets is a column of sequential IDs
(``REC-AAAA``, ``REC-AAAB``, ``REC-AAAC``, ...) -- exactly the shape seen
in the ``grouped_metrics`` eval corpus. Rather than build a general trie
structure, this factors the single longest common literal prefix shared by
every value in a column, states it once via a ``!X`` header line
(``docs/SPEC.md``), and stores only each row's suffix in the body -- the
same "declare once, reference per row" shape as ``!F`` (whole-column
constants) and ``!N``/``@`` (semantic-tree grouping), just for a *partial*
per-cell constant instead of a whole-cell one.

Wired in as opt-in (``render_tdf(doc, use_prefix=True)``, ``tdf convert
--use-prefix``) rather than a default-pipeline change, matching this
project's own established practice for every new accuracy-affecting
mechanism (semantic-tree grouping went through the same opt-in ->
eval-arm -> measure -> decide sequence, tdf/tree.py, and the shelved
``tdf_nocaret0`` anchor fix shows why that sequence matters) -- prefix
factoring is exact-text and reversible like ``!F``/``!V``, but it still
introduces one more layer of indirection between the model and a literal
identifier value, exactly the kind of change Phase 5's failure analysis
found costs row-association/exact-identifier accuracy. No accuracy data
exists for it yet.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from .reasoning import TransformReport
from .tokens import count

MARKER_TOKENS = 1  # estimated cost of one column's own "idx:" declaration syntax


@dataclass
class PrefixCandidate:
    idx: int
    prefix: str
    token_savings: int


def _column_values(rows: list[list[str]], idx: int) -> list[str]:
    return [r[idx] if idx < len(r) else "" for r in rows]


def _candidate_for_column(
    rows: list[list[str]], idx: int, min_prefix: int,
) -> PrefixCandidate | None:
    """Would factoring column idx's shared prefix pay for itself?

    Requires every row to have a non-empty value: an empty cell is a
    trivial prefix of everything, so its presence either collapses the
    whole-column LCP to nothing or needs an "empty means absent, not
    empty-suffix" encoding this format doesn't have. Real ID-like columns
    -- the mechanism's actual target -- are complete this way in practice;
    a column with genuine gaps just isn't a candidate.
    """
    values = _column_values(rows, idx)
    if not values or any(v == "" for v in values):
        return None
    prefix = os.path.commonprefix(values)
    if len(prefix) < min_prefix:
        return None
    tokens_before = sum(count(v) for v in values)
    suffixes = [v[len(prefix):] for v in values]
    tokens_after = sum(count(s) for s in suffixes) + count(prefix) + MARKER_TOKENS
    savings = tokens_before - tokens_after
    if savings <= 0:
        return None
    return PrefixCandidate(idx=idx, prefix=prefix, token_savings=savings)


def detect_prefix_columns(
    cols: list[str], rows: list[list[str]], skip_idx: int | None = None,
    min_prefix: int = 2,
) -> list[PrefixCandidate]:
    """Every column (in column order) whose shared prefix clears the
    net-token-positive bar. `skip_idx` excludes one column -- used to keep
    prefix factoring off the semantic-tree group key when grouping is also
    active, since !N/@ already eliminates that column's repetition more
    completely than prefix-sharing could add on top."""
    out = []
    for idx in range(len(cols)):
        if idx == skip_idx:
            continue
        cand = _candidate_for_column(rows, idx, min_prefix)
        if cand is not None:
            out.append(cand)
    return out


def factor_shared_prefixes(
    cols: list[str], rows: list[list[str]], skip_idx: int | None = None,
    min_prefix: int = 2,
) -> list[tuple[int, str]]:
    """Mutates `rows` in place, replacing each factored column's cell with
    its suffix. Returns the (column_index, prefix) pairs that were
    factored, in column order -- empty if none cleared the bar."""
    candidates = detect_prefix_columns(cols, rows, skip_idx, min_prefix)
    for cand in candidates:
        n = len(cand.prefix)
        for r in rows:
            if cand.idx < len(r):
                r[cand.idx] = r[cand.idx][n:]
    return [(c.idx, c.prefix) for c in candidates]


def prefix_savings_reports(
    cols: list[str], rows: list[list[str]], skip_idx: int | None = None,
    min_prefix: int = 2,
) -> list[TransformReport]:
    """Non-mutating: one TransformReport per column that would be factored,
    for the reasoning-aware reporting layer (tdf/reasoning.py, mission
    section 7)."""
    reports = []
    for cand in detect_prefix_columns(cols, rows, skip_idx, min_prefix):
        values = _column_values(rows, cand.idx)
        tokens_before = sum(count(v) for v in values)
        name = cols[cand.idx] if cand.idx < len(cols) else f"col{cand.idx}"
        reports.append(TransformReport(
            name=f"prefix_factoring:{name}",
            tokens_before=tokens_before,
            tokens_after=tokens_before - cand.token_savings,
            token_savings=cand.token_savings,
            structural_risk=0.0, semantic_risk=0.0, reasoning_risk=0.05,
            note=(f"column '{name}' shares a {len(cand.prefix)}-char literal "
                  f"prefix {cand.prefix!r} across all {len(rows)} rows"),
            evidence=("wire-encoded via !X; exact-text and reversible, same "
                      "class as !F/!V -- but still adds one layer of "
                      "indirection over a literal identifier value, and has "
                      "no accuracy data yet (opt-in, see tdf/prefix.py "
                      "module docstring)"),
        ))
    return reports
