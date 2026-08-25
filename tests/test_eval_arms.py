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


@pytest.fixture(scope="module")
def sales_report():
    pkl = ROOT / "eval/corpus/perturbed/sales_report.pkl"
    if not pkl.exists():
        pytest.skip("run python -m eval.corpus.perturb first")
    with open(pkl, "rb") as f:
        return pickle.load(f)


def test_registry_contains_all_nine_arms():
    assert set(ARMS) == {
        "md", "json", "toon",
        "tdf_full", "tdf_hoist", "tdf_nodict", "tdf_nocodes", "tdf_nocaret",
        "hybrid",
    }


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