"""Phase 19: semantic-tree wire encoding (!N / '@' group headers).

Follow-up to tdf/tree.py (Phase 17, detection-only) and the Phase 13 audit's
corrected recommendation #4: wires tdf.tree's grouping detection into
tdf/emit.py's _tdf_table and tdf/parse.py's table reader, opt-in via
render_tdf(..., use_grouping=True) -- default False, so every existing
caller and every existing test is completely unaffected (see
test_grouping_off_by_default_never_emits_new_sigils below).

Wire shape (see docs/SPEC.md for the full grammar):

    !T <n>
    !N <idx>:<name>        -- column <idx> (in the !C index space) is a
                               group key stated once per contiguous run
    !C <member columns>    -- every column EXCEPT the group key
    @ <value>              -- group header: all following member rows
                               belong to this group until the next '@' line
    <member row>...        -- one fewer field than a non-grouped row

Run: .venv/bin/python -m pytest tests/test_tree_wire.py -q
"""

from __future__ import annotations

import sys
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tdf.columnar import encode_columns  # noqa: E402
from tdf.emit import render_tdf  # noqa: E402
from tdf.ir import Doc, Table  # noqa: E402
from tdf.parse import parse_tdf  # noqa: E402
from tdf.validate import validate  # noqa: E402


def _round_trip(doc: Doc, use_grouping: bool = True) -> tuple[Doc, str]:
    work = deepcopy(doc)
    books = encode_columns(work)
    wire = render_tdf(work, legend=False, codebooks=books, use_grouping=use_grouping)
    return parse_tdf(wire), wire


def test_missions_own_worked_example_round_trips_and_uses_group_headers():
    doc = Doc(title="Report", blocks=[Table(
        cols=["country", "year", "value"],
        rows=[["India", "2024", "100"], ["India", "2025", "120"],
              ["India", "2026", "150"], ["Brazil", "2020", "90"],
              ["Brazil", "2021", "95"]],
    )])
    restored, wire = _round_trip(doc)
    tbl = next(b for b in restored.blocks if isinstance(b, Table))
    assert tbl.cols == doc.blocks[0].cols
    assert tbl.rows == doc.blocks[0].rows
    assert "!N 0:country" in wire
    assert "@ India" in wire and "@ Brazil" in wire
    # The whole point: the group key is stated ONCE per run, not per row.
    assert wire.count("India") == 1 and wire.count("Brazil") == 1


def test_grouping_off_by_default_never_emits_new_sigils():
    """render_tdf's default (use_grouping=False) must be byte-for-byte
    unaffected by this feature existing at all."""
    doc = Doc(blocks=[Table(
        cols=["country", "year", "value"],
        rows=[["India", "2024", "100"], ["India", "2025", "120"],
              ["India", "2026", "150"]],
    )])
    work = deepcopy(doc)
    books = encode_columns(work)
    wire = render_tdf(work, legend=False, codebooks=books)  # default
    assert "!N" not in wire
    assert "@ " not in wire


def test_declines_when_not_net_positive_and_falls_back_to_caret():
    """Break-even economics (tdf/tree.py's own discipline): grouping must
    not fire, and the existing caret-elision path must still handle the
    repeat, exactly as it does with use_grouping=False."""
    doc = Doc(blocks=[Table(
        cols=["country", "handle", "note"],
        rows=[["United States", "@potus", "first"],
              ["United States", "@vp", "second"],
              ["France", "@president", "only"]],
    )])
    restored, wire = _round_trip(doc)
    assert "!N" not in wire
    assert "^" in wire  # caret still does its job
    tbl = next(b for b in restored.blocks if isinstance(b, Table))
    assert tbl.rows == doc.blocks[0].rows


def test_member_row_starting_with_at_sign_is_force_quoted():
    """A member row's first cell literally starting with '@' must not be
    misread as a new group-header line."""
    doc = Doc(blocks=[Table(
        cols=["country", "handle", "note"],
        rows=[["United States of America", "@potus", "first person"],
              ["United States of America", "@vp", "second person"],
              ["United States of America", "@speaker", "third person"],
              ["France", "@president", "only person"]],
    )])
    restored, wire = _round_trip(doc)
    assert "!N 0:country" in wire  # grouping DID fire this time
    assert '"@potus"' in wire
    tbl = next(b for b in restored.blocks if isinstance(b, Table))
    assert tbl.rows == doc.blocks[0].rows


def test_group_value_containing_a_space_is_quoted():
    doc = Doc(blocks=[Table(
        cols=["country", "handle", "note"],
        rows=[["United States of America", "a", "first person here"],
              ["United States of America", "b", "second person here"],
              ["United States of America", "c", "third person here"],
              ["France", "d", "only person here today"]],
    )])
    restored, wire = _round_trip(doc)
    assert '@ "United States of America"' in wire
    tbl = next(b for b in restored.blocks if isinstance(b, Table))
    assert tbl.rows == doc.blocks[0].rows


def test_survives_periodic_header_reemission_every_50_rows():
    countries = ["India", "Brazil", "Japan", "Egypt"]
    rows = [[countries[i % 4], str(2000 + i), str(100 + i)] for i in range(120)]
    rows.sort(key=lambda r: r[0])
    doc = Doc(blocks=[Table(cols=["country", "year", "value"], rows=rows)])
    restored, wire = _round_trip(doc)
    tbl = next(b for b in restored.blocks if isinstance(b, Table))
    assert tbl.rows == doc.blocks[0].rows
    # 4 groups + re-anchoring '@' lines injected at the 50/100-row boundaries.
    assert wire.count("!N 0:country") >= 2
    assert sum(1 for l in wire.splitlines() if l.startswith("@ ")) > 4


def test_coexists_with_constant_column_factoring():
    """!F (whole-table constant) and !N (per-group key) target disjoint
    columns and must both fire and both reverse correctly together."""
    rows = []
    for country, region in [("India", "APAC"), ("Brazil", "LATAM")]:
        for y in range(3):
            rows.append([country, str(2020 + y), region, "USD"])
    doc = Doc(blocks=[Table(cols=["country", "year", "region", "currency"], rows=rows)])
    restored, wire = _round_trip(doc)
    assert "!F " in wire and "currency=USD" in wire
    assert "!N 0:country" in wire
    tbl = next(b for b in restored.blocks if isinstance(b, Table))
    assert tbl.rows == doc.blocks[0].rows
    assert tbl.cols == doc.blocks[0].cols


def test_coexists_with_columnar_codebooks():
    statuses = ["Pending Review", "Approved For Payment", "Rejected By Manager"]
    rows = []
    for country in ["Argentina", "Botswana"]:
        for i in range(40):
            rows.append([country, str(2000 + i), statuses[i % 3]])
    doc = Doc(blocks=[Table(cols=["country", "year", "status"], rows=rows)])
    work = deepcopy(doc)
    books = encode_columns(work)
    assert books, "expected a codebook to fire for this fixture"
    wire = render_tdf(work, legend=False, codebooks=books, use_grouping=True)
    assert "!V status" in wire and "!N 0:country" in wire
    restored = parse_tdf(wire)
    tbl = next(b for b in restored.blocks if isinstance(b, Table))
    assert tbl.rows == doc.blocks[0].rows


def test_validate_accepts_grouped_output():
    doc = Doc(blocks=[Table(
        cols=["country", "year", "value"],
        rows=[["India", "2024", "100"], ["India", "2025", "120"],
              ["India", "2026", "150"], ["Brazil", "2020", "90"],
              ["Brazil", "2021", "95"]],
    )])
    work = deepcopy(doc)
    books = encode_columns(work)
    wire = render_tdf(work, legend=True, codebooks=books, use_grouping=True)
    v = validate(wire)
    assert v.ok, getattr(v, "violations", v)


def test_single_row_and_empty_table_do_not_crash():
    for rows in ([], [["India", "2024", "100"]]):
        doc = Doc(blocks=[Table(cols=["country", "year", "value"], rows=rows)])
        restored, wire = _round_trip(doc)
        tbl = next(b for b in restored.blocks if isinstance(b, Table))
        assert tbl.rows == rows
