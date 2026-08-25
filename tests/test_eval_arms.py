"""The eval harness's encoding registry stays lossless as arms evolve.

Every arm in ARMS must (a) exist, (b) return a non-empty string for a real
corpus document, and (c) -- for TDF-family arms that assert it internally --
round-trip without distinct-content loss. Guards against an arm being added
that silently degrades content before any model ever sees it.

Run: .venv/bin/python -m pytest tests/test_eval_arms.py -q
"""

from __future__ import annotations

import pickle
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from eval.formats.encode import ARMS  # noqa: E402
from tdf.ir import Doc, Table  # noqa: E402


@pytest.fixture(scope="module")
def sales_report():
    pkl = ROOT / "eval/corpus/perturbed/sales_report.pkl"
    if not pkl.exists():
        pytest.skip("run python -m eval.corpus.perturb first")
    with open(pkl, "rb") as f:
        return pickle.load(f)


def test_registry_contains_all_ten_arms():
    assert set(ARMS) == {
        "md", "json", "toon",
        "tdf_full", "tdf_hoist", "tdf_nodict", "tdf_nocodes", "tdf_nocaret",
        "tdf_nocaret0", "hybrid",
    }


def test_nocaret0_arm_keeps_row_anchor_literal():
    """The Phase-5 remediation: caret-elision skips column 0 entirely, so a
    repeated lookup KEY stays on the wire while interior columns compress."""
    from copy import deepcopy

    doc = Doc(blocks=[Table(
        cols=["region", "segment", "growth"],
        rows=[["EMEA", "Cloud", "12.4%"],
              ["EMEA", "Services", "3.1%"],
              ["APAC", "Cloud", "9.9%"]],
    )])

    full = ARMS["tdf_full"](deepcopy(doc))
    keep = ARMS["tdf_nocaret0"](deepcopy(doc))

    # Baseline behaviour unchanged: second EMEA collapses to ^.
    assert "\n^ " in full or full.split("!C")[1].count("^") >= 1
    # The arm keeps every anchor literal -- no bare ^ anywhere in col 0.
    body = [l for l in keep.splitlines()
            if l.strip() and not l.startswith(("!", "#"))]
    assert sum(1 for l in body if l.split(" ")[0] == "EMEA") == 2
    assert "^" not in "".join(l.split(" ")[0] for l in body)

    # Both arms stay lossless (internal _assert_lossless already ran; assert
    # parse-side typing too).
    from tdf.parse import parse_tdf
    for wire in (full, keep):
        tbl = next(b for b in parse_tdf(wire).blocks if hasattr(b, "cols"))
        assert tbl.cols == ["region", "segment", "growth"]
        assert [r[0] for r in tbl.rows] == ["EMEA", "EMEA", "APAC"]


def test_hybrid_arm_is_registered_and_lossless(sales_report):
    """The post-hoc hybrid arm must behave like its siblings: real encoding,
    non-empty output, and the internal _assert_lossless guard passing."""
    from copy import deepcopy

    out = ARMS["hybrid"](deepcopy(sales_report))
    assert isinstance(out, str) and out.strip()
    # Floor guarantee on a REAL document, not just synthetic ones:
    from tdf.emit import render_markdown
    from tdf.tokens import count
    md = render_markdown(deepcopy(sales_report))
    assert count(out) <= count(md), (
        f"hybrid broke its floor on sales_report: "
        f"{count(out)} > {count(md)}"
    )


def test_every_arm_encodes_the_real_document(sales_report):
    from copy import deepcopy

    for name, fn in ARMS.items():
        out = fn(deepcopy(sales_report))
        assert isinstance(out, str) and out.strip(), f"arm {name} empty"