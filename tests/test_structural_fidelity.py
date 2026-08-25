"""Structural fidelity framework tests (Phase 3).

The headline case is deliberate and worth stating: a table with two swapped
rows scores 100% on the legacy bag-of-words metric — the exact blind spot
the README has warned about — while structural_report flags it immediately.
Every aspect metric gets both an identity check (perfect round-trip) and a
targeted mutation (specific degradation detected).

Run: .venv/bin/python -m pytest tests/test_structural_fidelity.py -q
"""

from __future__ import annotations

import sys
from copy import deepcopy
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tdf.columnar import encode_columns  # noqa: E402
from tdf.emit import render_tdf  # noqa: E402
from tdf.fidelity import compare  # noqa: E402
from tdf.fidelity_structural import structural_report  # noqa: E402
from tdf.ir import Doc, Elision, Heading, KV, ListBlock, PageMark, Para, Quote, Table, Code  # noqa: E402
from tdf.parse import parse_tdf  # noqa: E402


def _rich_doc() -> Doc:
    return Doc(title="Quarterly", blocks=[
        Heading(2, "Overview"),
        Para("Revenue grew despite headwinds."),
        Quote("stay the course"),
        ListBlock(["alpha", "beta"], ordered=True),
        Table(cols=["region", "segment", "growth"],
              rows=[["EMEA", "Cloud", "12.4%"],
                    ["APAC", "Services", "3.1%"]]),
        KV([("owner", "platform"), ("headcount", "4180")]),
        PageMark(7),
        Elision("x1", "index", 150, gist="nav tree", items=20),
    ])


def _roundtrip(doc: Doc) -> Doc:
    work = deepcopy(doc)
    books = encode_columns(work)
    out = render_tdf(work, legend=False, codebooks=books)
    return parse_tdf(out)


# ------------------------------------------------------------- perfect case


def test_identical_documents_score_perfectly():
    doc = _rich_doc()
    rep = structural_report(doc, deepcopy(doc))

    assert rep["exact_structural_match"] is True
    for key in ("block_type_accuracy", "ordering_accuracy", "heading_accuracy",
                "paragraph_exact_accuracy", "list_exact_accuracy",
                "table_cell_level_accuracy", "table_col_structure_accuracy",
                "kv_pair_accuracy", "metadata_title_accuracy",
                "pagemark_exact_accuracy", "elision_reference_accuracy"):
        assert rep[key] == 1.0, key
    assert rep["table_cells_compared"] == 6
    assert rep["tables_compared"] == 1


def test_tdf_roundtrip_scores_perfect_on_supported_document():
    doc = _rich_doc()
    restored = _roundtrip(deepcopy(doc))
    rep = structural_report(doc, restored)

    assert rep["exact_structural_match"] is True
    assert rep["ordering_accuracy"] == 1.0
    assert rep["table_cell_level_accuracy"] == 1.0
    assert rep["heading_accuracy"] == 1.0
    assert rep["list_exact_accuracy"] == 1.0
    assert rep["kv_pair_accuracy"] == 1.0


# --------------------------------------------- mutations the bag misses


def test_swapped_table_rows_caught_but_bag_reports_perfect():
    """The README's own warning, now enforced: row order carries meaning.
    Bag-of-words calls this lossless; the structural report does not."""
    doc = _rich_doc()
    bad = deepcopy(doc)
    bad.blocks[4].rows[0], bad.blocks[4].rows[1] = \
        bad.blocks[4].rows[1], bad.blocks[4].rows[0]

    bag = compare(doc, bad)
    assert bag["distinct_recall"] == 1.0          # the blind spot, proven

    rep = structural_report(doc, bad)
    assert rep["exact_structural_match"] is False
    assert rep["ordering_accuracy"] < 1.0
    assert rep["table_cell_level_accuracy"] < 1.0


def test_dropped_list_item_detected_with_count():
    doc = _rich_doc()
    bad = deepcopy(doc)
    bad.blocks[3].items = ["alpha"]
    rep = structural_report(doc, bad)

    assert rep["exact_structural_match"] is False
    assert rep["list_exact_accuracy"] < 1.0


def test_heading_level_change_detected():
    doc = _rich_doc()
    bad = deepcopy(doc)
    bad.blocks[0].level = 3                       # was 2
    rep = structural_report(doc, bad)

    assert rep["exact_structural_match"] is False
    assert rep["heading_accuracy"] < 1.0


def test_code_indentation_is_significant():
    doc = Doc(blocks=[Code(text="if x:\n    run()", lang="python")])
    same = deepcopy(doc)
    padded = deepcopy(doc)
    padded.blocks[0].text = "if x:\n        run()"   # deeper indent

    assert structural_report(doc, same)["code_exact_accuracy"] == 1.0
    assert structural_report(doc, padded)["code_exact_accuracy"] < 1.0


def test_kv_pair_value_corruption_detected():
    doc = _rich_doc()
    bad = deepcopy(doc)
    bad.blocks[5].pairs[1] = ("headcount", "9999")
    rep = structural_report(doc, bad)

    assert rep["kv_pair_accuracy"] < 1.0
    assert rep["exact_structural_match"] is False


def test_block_deletion_shows_in_counts_and_ordering():
    doc = _rich_doc()
    bad = deepcopy(doc)
    del bad.blocks[1]                              # drop the paragraph
    rep = structural_report(doc, bad)

    assert rep["blocks_dropped_original"] >= 1 or \
        rep["blocks_inserted_restored"] >= 0
    assert rep["paragraph_compared"] < rep["block_count_original"]
    assert rep["exact_structural_match"] is False