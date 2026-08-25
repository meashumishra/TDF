"""Phase 10 selector tests: representation choice must be measured, honest,
and safe (skeleton only by explicit request).

Run: .venv/bin/python -m pytest tests/test_selector.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tdf.ir import Doc, Heading, Para, Table  # noqa: E402
from tdf.selector import optimize_context, select_representation  # noqa: E402
from tdf.tokens import count  # noqa: E402


def _table_heavy() -> Doc:
    rows = [["EMEA", "Cloud", f"{1000+i}.50", "12.4%"] for i in range(80)]
    return Doc(title="Sales", blocks=[
        Heading(2, "By region"),
        Para("One short intro sentence."),
        Table(cols=["region", "segment", "amount", "growth"], rows=rows),
    ])


def _prose_only() -> Doc:
    return Doc(title="Essay", blocks=[
        Para("Prose paragraph one. It has sentences and no tables at all."),
        Para("Prose paragraph two. Still just words on the page."),
    ])


# ------------------------------------------------------------------ hybrid


def test_table_heavy_document_selects_hybrid_with_real_savings():
    res = select_representation(_table_heavy())
    assert res["representation"] == "hybrid"
    assert res["estimated_savings_pct"] > 10
    assert res["encoded_tokens"] < res["original_tokens"]
    assert res["risk"] == "low"
    assert "floor" in res["reason"] or "arbitration" in res["reason"]


def test_floor_holds_in_the_selector_itself():
    for doc in (_table_heavy(), _prose_only()):
        res = select_representation(doc)
        assert res["encoded_tokens"] <= res["original_tokens"]


# ---------------------------------------------------------------- markdown


def test_prose_document_stays_markdown():
    res = select_representation(_prose_only())
    assert res["representation"] == "markdown"
    # Floor guarantee: when dense cannot win, output == baseline tokens.
    assert res["encoded_tokens"] == res["original_tokens"]
    assert "could not beat Markdown" in res["reason"]
    assert res["risk"] == "none"


# ---------------------------------------------------------------- skeleton


def test_skeleton_requires_explicit_navigation_request():
    doc = _table_heavy()
    balanced = select_representation(doc)
    nav = select_representation(doc, allow_skeleton=True, objective="navigation")

    assert balanced["representation"] != "skeleton"
    assert nav["representation"] in ("skeleton", "hybrid")
    if nav["representation"] == "skeleton":
        assert "expansion required" in nav["reason"]
        assert nav["risk"].startswith("high")


def test_navigation_picks_smallest_measured_candidate():
    doc = _table_heavy()
    res = select_representation(doc, allow_skeleton=True, objective="navigation")
    breakdown = res["breakdown"]
    assert res["encoded_tokens"] == min(breakdown.values())


# ------------------------------------------------------- contract shape


def test_result_contract_matches_mission_section_20():
    res = optimize_context(_table_heavy())
    for key in ("representation", "original_tokens", "encoded_tokens",
                "estimated_savings_pct", "risk", "reason"):
        assert key in res, key


def test_unknown_objective_rejected():
    with pytest.raises(ValueError):
        select_representation(_prose_only(), objective="max_compress")