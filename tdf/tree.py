"""Phase 17: semantic-tree grouping detection (mission section 4).

Mission section 4's worked example:

    India | 2024 | 100
    India | 2025 | 120
    India | 2026 | 150

should be representable as a tree with the repeated entity stated once:

    India
      2024 100
      2025 120
      2026 150

This module is deliberately DETECTION-ONLY -- see validation/
reasoning_optimizer_audit.md's corrected recommendation #4. Wiring a new
group-header wire sigil into tdf/emit.py's `_tdf_table` is a separable,
larger piece of work: that function already coordinates unit hoisting,
constant-column factoring, `!F` index remapping, tab-vs-space separator
selection, and periodic header re-emission every 50 rows (all specific to
the existing grammar), and none of those interactions should be worked out
under time pressure alongside a brand-new sigil. What ships here instead is
the deterministic, independently-testable piece the mission's own section
16 implementation order lists as a separate step from "tree compression":
finding *where* grouping would help and *whether it actually pays for
itself*, expressed as a TransformReport (tdf/reasoning.py) so it composes
with the rest of the reasoning-aware reporting layer.

Why this is lower reasoning_risk than caret-elision even though both state
a repeated value once instead of per-row: a group header keeps the entity
as literal, legible text (e.g. an "India" line), not an opaque symbol like
`^` that requires the reader to scan upward for context. Phase-5's failure
analysis specifically implicated the OPACITY of `^` on identifier columns,
not the general idea of stating a repeated value once -- see optimize.py's
`elide_repeats_keep_anchor` docstring and reports/FAILURE_ANALYSIS.md.

Scope for this version: only column 0 is considered as a candidate group
key, matching the mission's own example and keeping detection unambiguous.
Multi-column or non-leading group keys are future work.
"""

from __future__ import annotations

from dataclasses import dataclass

from .reasoning import TransformReport
from .tokens import count

MARKER_TOKENS = 1  # estimated cost of one group-header line's own sigil/prefix


@dataclass
class GroupRun:
    """A maximal run of consecutive rows sharing the same column-0 value."""

    value: str
    start: int  # inclusive row index into the ORIGINAL rows list
    end: int    # exclusive


def detect_group_runs(rows: list[list[str]]) -> list[GroupRun]:
    """Partition rows into maximal consecutive runs on column 0.

    Every row belongs to exactly one run (singleton runs included), so
    `sum(r.end - r.start for r in runs) == len(rows)` always holds -- this
    mirrors elide_repeats' own non-overlapping-run walk (optimize.py:198),
    just grouping instead of caret-marking.
    """
    if not rows:
        return []
    runs: list[GroupRun] = []
    start = 0
    current = rows[0][0] if rows[0] else ""
    for i in range(1, len(rows)):
        v = rows[i][0] if rows[i] else ""
        if v != current:
            runs.append(GroupRun(current, start, i))
            start, current = i, v
    runs.append(GroupRun(current, start, len(rows)))
    return runs


def group_savings_report(cols: list[str], rows: list[list[str]]) -> TransformReport | None:
    """Would grouping on column 0 pay for itself on this table?

    Returns None when there is nothing to propose: fewer than 2 columns
    (nothing left to nest under the key), no run of length >= 2 (grouping
    every row as its own singleton group only adds header overhead, never
    saves anything), or the net token accounting is not positive.
    """
    if len(cols) < 2 or not rows:
        return None

    runs = detect_group_runs(rows)
    if not any(r.end - r.start >= 2 for r in runs):
        return None

    tokens_before = sum(count(row[0]) if row else 0 for row in rows)
    tokens_after = sum(count(r.value) + MARKER_TOKENS for r in runs)
    token_savings = tokens_before - tokens_after
    if token_savings <= 0:
        return None

    grouped_rows = sum(1 for r in runs if r.end - r.start >= 2)
    return TransformReport(
        name=f"semantic_tree_grouping:{cols[0]}",
        tokens_before=tokens_before, tokens_after=tokens_after,
        token_savings=token_savings,
        structural_risk=0.0, semantic_risk=0.0, reasoning_risk=0.05,
        note=(f"{len(runs)} run(s) on column '{cols[0]}', {grouped_rows} "
              f"of them length >= 2 -- entity stays literal in a group "
              f"header, unlike caret-elision's opaque marker"),
        evidence=("detection-only: no wire encoding exists yet to measure "
                  "an actual accuracy delta (see tdf/tree.py module docstring)"),
    )
