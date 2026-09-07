"""Mission section 5B: trie/prefix compression (tdf/prefix.py).

Wires tdf.prefix's detection into tdf/emit.py's _tdf_table and tdf/parse.py's
table reader, opt-in via render_tdf(..., use_prefix=True) -- default False,
so every existing caller and every existing test is completely unaffected
(see test_prefix_off_by_default_never_emits_new_sigils below).

Wire shape (see docs/SPEC.md):

    !T <n>
    !X <idx>:<prefix> ...   -- column <idx> (in the !F/!N index space) has
                               this literal prefix on every row; cells show
                               only the suffix
    !C <columns>            -- the factored column still appears here
    <row>...                -- factored column's cell holds only the suffix

Run: .venv/bin/python -m pytest tests/test_prefix.py -q
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
from tdf.prefix import detect_prefix_columns, factor_shared_prefixes  # noqa: E402
from tdf.validate import validate  # noqa: E402


def _round_trip(doc: Doc, use_prefix: bool = True, use_grouping: bool = False) -> tuple[Doc, str]:
    work = deepcopy(doc)
    books = encode_columns(work)
    wire = render_tdf(work, legend=False, codebooks=books, use_prefix=use_prefix,
                       use_grouping=use_grouping)
    return parse_tdf(wire), wire


def _record_id_rows(n: int) -> list[list[str]]:
    return [[f"REC-{i:04d}", str(2000 + i), str(100 + i)] for i in range(n)]


def test_shared_id_prefix_round_trips_and_uses_x_sigil():
    rows = _record_id_rows(20)
    doc = Doc(blocks=[Table(cols=["record_id", "year", "value"], rows=rows)])
    restored, wire = _round_trip(doc)
    assert "!X " in wire
    assert "0:REC-" in wire
    # The factored column's stored cells are strictly shorter than the
    # original values -- proof the prefix was actually stripped, not just
    # declared alongside untouched data.
    assert "REC-0000" not in wire
    tbl = next(b for b in restored.blocks if isinstance(b, Table))
    assert tbl.rows == doc.blocks[0].rows
    assert tbl.cols == doc.blocks[0].cols


def test_prefix_off_by_default_never_emits_new_sigils():
    rows = _record_id_rows(20)
    doc = Doc(blocks=[Table(cols=["record_id", "year", "value"], rows=rows)])
    wire = render_tdf(deepcopy(doc), legend=False)
    assert "!X" not in wire
    restored = parse_tdf(wire)
    tbl = next(b for b in restored.blocks if isinstance(b, Table))
    assert tbl.rows == doc.blocks[0].rows


def test_declines_when_not_net_positive():
    """Two rows sharing only a 1-character prefix: the !X declaration
    itself costs more than the handful of characters it would save."""
    rows = [["a1", "x"], ["b2", "y"]]
    doc = Doc(blocks=[Table(cols=["code", "val"], rows=rows)])
    cands = detect_prefix_columns(["code", "val"], [r[:] for r in rows])
    assert cands == []
    _, wire = _round_trip(doc)
    assert "!X" not in wire


def test_column_with_any_empty_cell_is_never_a_candidate():
    rows = [["REC-0001", "1"], ["REC-0002", "2"], ["", "3"]]
    cands = detect_prefix_columns(["record_id", "n"], [r[:] for r in rows])
    assert cands == [] or all(c.idx != 0 for c in cands)


def test_quoted_prefix_with_embedded_space_round_trips():
    rows = [[f"Region West {i}", str(i)] for i in range(10)]
    doc = Doc(blocks=[Table(cols=["label", "n"], rows=rows)])
    restored, wire = _round_trip(doc)
    assert "!X " in wire
    tbl = next(b for b in restored.blocks if isinstance(b, Table))
    assert tbl.rows == doc.blocks[0].rows


def test_coexists_with_constant_column_factoring():
    rows = [[f"REC-{i:03d}", "USD", str(i)] for i in range(10)]
    doc = Doc(blocks=[Table(cols=["record_id", "currency", "value"], rows=rows)])
    restored, wire = _round_trip(doc)
    assert "!F " in wire and "currency=USD" in wire
    assert "!X " in wire
    tbl = next(b for b in restored.blocks if isinstance(b, Table))
    assert tbl.rows == doc.blocks[0].rows
    assert tbl.cols == doc.blocks[0].cols


def test_coexists_with_columnar_codebooks():
    statuses = ["Pending Review", "Approved For Payment", "Rejected By Manager"]
    rows = [[f"REC-{i:04d}", statuses[i % 3]] for i in range(80)]
    doc = Doc(blocks=[Table(cols=["record_id", "status"], rows=rows)])
    work = deepcopy(doc)
    books = encode_columns(work)
    assert books, "expected a codebook to fire for this fixture"
    wire = render_tdf(work, legend=False, codebooks=books, use_prefix=True)
    assert "!V status" in wire and "!X " in wire
    restored = parse_tdf(wire)
    tbl = next(b for b in restored.blocks if isinstance(b, Table))
    assert tbl.rows == doc.blocks[0].rows


def test_coexists_with_grouping_skips_group_key_column():
    """Column 0 is the group key AND happens to share a prefix; grouping
    must win it (!N/@ already eliminates its repetition), and !X should
    still fire on the OTHER shared-prefix column (record_id)."""
    rows = []
    for country in ["India", "Indianapolis-adjacent"]:
        for i in range(4):
            rows.append([country, f"REC-{len(rows):04d}", str(i)])
    doc = Doc(blocks=[Table(cols=["country", "record_id", "n"], rows=rows)])
    restored, wire = _round_trip(doc, use_prefix=True, use_grouping=True)
    assert "!N 0:country" in wire
    assert "!X " in wire
    # The group-key column index (0) must never appear as an !X target.
    x_line = next(l for l in wire.splitlines() if l.startswith("!X "))
    targets = [tok.split(":", 1)[0] for tok in x_line[3:].split(" ")]
    assert "0" not in targets
    tbl = next(b for b in restored.blocks if isinstance(b, Table))
    assert tbl.rows == doc.blocks[0].rows
    assert tbl.cols == doc.blocks[0].cols


def test_survives_periodic_header_reemission_every_50_rows_ungrouped():
    rows = _record_id_rows(120)
    doc = Doc(blocks=[Table(cols=["record_id", "year", "value"], rows=rows)])
    restored, wire = _round_trip(doc)
    assert wire.count("!X ") >= 2
    tbl = next(b for b in restored.blocks if isinstance(b, Table))
    assert tbl.rows == doc.blocks[0].rows


def test_survives_periodic_header_reemission_every_50_rows_grouped():
    rows = []
    countries = ["India", "Brazil"]
    for gi, country in enumerate(countries):
        for i in range(60):
            rows.append([country, f"REC-{gi}-{i:03d}", str(i)])
    doc = Doc(blocks=[Table(cols=["country", "record_id", "n"], rows=rows)])
    restored, wire = _round_trip(doc, use_prefix=True, use_grouping=True)
    assert "!N 0:country" in wire
    assert wire.count("!X ") >= 2
    tbl = next(b for b in restored.blocks if isinstance(b, Table))
    assert tbl.rows == doc.blocks[0].rows


def test_grouped_periodic_reemission_also_restores_constant_column():
    """Regression test for a pre-existing gap found while wiring !X:
    _render_grouped_table never re-emitted !F at its own 50-member
    boundary even though docs/SPEC.md always documented that it should
    (parse_tdf's grouped-row reader already knew to skip a periodically
    re-emitted f_line -- this was purely a missing emit-side line)."""
    rows = []
    for i in range(60):
        rows.append(["India", "USD", str(i)])
    doc = Doc(blocks=[Table(cols=["country", "currency", "value"], rows=rows)])
    restored, wire = _round_trip(doc, use_prefix=False, use_grouping=True)
    assert wire.count("!F ") >= 2, "expected !F re-emitted at the 50-member boundary"
    tbl = next(b for b in restored.blocks if isinstance(b, Table))
    assert tbl.rows == doc.blocks[0].rows
    assert tbl.cols == doc.blocks[0].cols


def test_validate_accepts_prefixed_output():
    rows = _record_id_rows(10)
    doc = Doc(blocks=[Table(cols=["record_id", "year", "value"], rows=rows)])
    _, wire = _round_trip(doc)
    result = validate(wire)
    assert result.ok, result.violations


def test_single_row_and_empty_table_do_not_crash():
    doc = Doc(blocks=[Table(cols=["a", "b"], rows=[["REC-1", "x"]])])
    _round_trip(doc)  # must not raise
    empty = Doc(blocks=[Table(cols=["a", "b"], rows=[])])
    _round_trip(empty)  # must not raise


def test_factor_shared_prefixes_mutates_in_place_and_returns_pairs():
    cols = ["record_id", "n"]
    rows = [["REC-01", "1"], ["REC-02", "2"], ["REC-03", "3"]]
    pairs = factor_shared_prefixes(cols, rows)
    assert pairs == [(0, "REC-0")]
    assert rows == [["1", "1"], ["2", "2"], ["3", "3"]]
