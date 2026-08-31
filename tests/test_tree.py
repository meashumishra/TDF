"""Phase 17: semantic-tree grouping detection tests.

Covers tdf/tree.py -- detection-only, no wire encoding exists yet (see the
module docstring for why). These tests confirm the detector finds real
grouping opportunities and, just as importantly, stays silent when
grouping would not pay for itself, matching every other transform in this
codebase's "only fire when net positive" discipline.

Run: .venv/bin/python -m pytest tests/test_tree.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tdf.tree import GroupRun, detect_group_runs, group_savings_report  # noqa: E402


def test_detect_group_runs_on_missions_own_example():
    rows = [
        ["India", "2024", "100"],
        ["India", "2025", "120"],
        ["India", "2026", "150"],
        ["Brazil", "2020", "90"],
        ["Brazil", "2021", "95"],
    ]
    runs = detect_group_runs(rows)
    assert runs == [
        GroupRun("India", 0, 3),
        GroupRun("Brazil", 3, 5),
    ]


def test_every_row_belongs_to_exactly_one_run():
    rows = [["A", "1"], ["A", "2"], ["B", "3"], ["A", "4"], ["A", "5"], ["A", "6"]]
    runs = detect_group_runs(rows)
    assert sum(r.end - r.start for r in runs) == len(rows)
    # Non-contiguous repeats of "A" are NOT merged into one run -- the
    # second "A" block starts a new run distinct from the first.
    assert [r.value for r in runs] == ["A", "B", "A"]


def test_empty_rows_produce_no_runs():
    assert detect_group_runs([]) == []


def test_savings_report_fires_on_grouped_data():
    cols = ["country", "year", "value"]
    rows = [
        ["India", "2024", "100"], ["India", "2025", "120"], ["India", "2026", "150"],
        ["Brazil", "2020", "90"], ["Brazil", "2021", "95"],
    ]
    r = group_savings_report(cols, rows)
    assert r is not None
    assert r.token_savings > 0
    assert r.structural_risk == 0.0 and r.semantic_risk == 0.0
    assert r.reasoning_risk < 0.5  # literal group header, not an opaque marker


def test_savings_report_silent_when_no_row_repeats():
    """Every value in column 0 is distinct -- grouping would only add
    header overhead per singleton run, never save anything."""
    cols = ["id", "value"]
    rows = [["A1", "1"], ["A2", "2"], ["A3", "3"]]
    assert group_savings_report(cols, rows) is None


def test_savings_report_silent_on_single_column_table():
    """Nothing left to nest under the key if the key is the only column."""
    cols = ["country"]
    rows = [["India"], ["India"], ["Brazil"]]
    assert group_savings_report(cols, rows) is None


def test_savings_report_silent_at_exact_break_even():
    """A single length-2 run of a 1-token key: 2 tokens before (one per
    row) vs 1 token (stated once) + MARKER_TOKENS(1) after = exactly 0 net
    savings. Confirms the "<= 0 means silent" boundary is enforced, not
    just "< 0" -- a break-even transform is not worth the wire complexity
    it would add, so it must not fire."""
    cols = ["id", "v"]
    rows = [["X", "1"], ["X", "2"]]
    assert group_savings_report(cols, rows) is None

    # Three repeats of the same 1-token key tips the balance: 3 tokens
    # before vs 1 + 1 after = net +1, so it DOES fire.
    rows3 = [["X", "1"], ["X", "2"], ["X", "3"]]
    r = group_savings_report(cols, rows3)
    assert r is not None
    assert r.token_savings == 1
