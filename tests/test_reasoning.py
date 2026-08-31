"""Phase 15: reasoning-aware transform reporting tests.

Covers tdf/reasoning.py, the audit's recommendation #3: an additive
reporting layer over existing transforms, not a change to what render_tdf
emits. Every test here should also confirm that property -- explain() must
never mutate the document it's given.

Run: .venv/bin/python -m pytest tests/test_reasoning.py -q
"""

from __future__ import annotations

import sys
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tdf.ir import Doc, Para, Table  # noqa: E402
from tdf.reasoning import explain, report_caret_elision, score  # noqa: E402


def test_explain_never_mutates_the_input_doc():
    doc = Doc(blocks=[
        Table(cols=["id", "region"], rows=[["A1", "EMEA"], ["A1", "APAC"]]),
        Para("Some prose here."),
    ])
    before = deepcopy(doc)
    explain(doc)
    assert doc == before


def test_caret_elision_flags_identifier_column_as_high_reasoning_risk():
    doc = Doc(blocks=[Table(
        cols=["id", "region", "balance"],
        rows=[["ACC-1", "EMEA", "500"], ["ACC-1", "EMEA", "620"], ["ACC-2", "APAC", "300"]],
    )])
    reports = report_caret_elision(doc)
    assert len(reports) == 1
    r = reports[0]
    assert r.reasoning_risk > 0.5
    assert "id" in r.note
    assert r.structural_risk == 0.0 and r.semantic_risk == 0.0
    assert r.token_savings > 0


def test_caret_elision_on_non_identifier_columns_is_low_risk():
    """Column 0 is always identifier-like by the heuristic (Phase-5's
    finding was specifically about column 0 as the conventional anchor,
    independent of its name), so the repeat must be in a LATER column with
    a non-identifier name and column 0 non-repeating to isolate this case."""
    doc = Doc(blocks=[Table(
        cols=["timestamp", "region", "note"],
        rows=[["t1", "EMEA", "steady growth this quarter"],
              ["t2", "EMEA", "steady growth this quarter"],
              ["t3", "APAC", "slower start"]],
    )])
    reports = report_caret_elision(doc)
    assert len(reports) == 1
    assert reports[0].reasoning_risk < 0.5


def test_caret_elision_reports_nothing_when_nothing_elides():
    doc = Doc(blocks=[Table(
        cols=["id", "region"], rows=[["A1", "EMEA"], ["A2", "APAC"]],
    )])
    assert report_caret_elision(doc) == []


def test_dictionary_report_cites_measured_ablation_evidence():
    doc = Doc(blocks=[
        Para("The revenue did not increase during the quarter despite forecasts."),
        Para("Analysts noted the revenue did not increase during the quarter despite forecasts."),
        Para("In contrast, the revenue did not increase during the quarter despite forecasts in EMEA."),
    ])
    reports = explain(doc)
    dict_reports = [r for r in reports if r.name == "phrase_dictionary"]
    assert len(dict_reports) == 1
    r = dict_reports[0]
    assert r.token_savings > 0
    assert "REPORT.md" in r.evidence


def test_constant_column_factoring_is_always_zero_risk():
    doc = Doc(blocks=[Table(
        cols=["region", "currency", "amount"],
        rows=[["EMEA", "USD", "100"], ["EMEA", "USD", "200"],
              ["EMEA", "USD", "300"], ["EMEA", "USD", "400"]],
    )])
    reports = explain(doc)
    ccf = [r for r in reports if r.name.startswith("constant_column_factoring")]
    assert len(ccf) == 1
    assert ccf[0].structural_risk == 0.0 and ccf[0].semantic_risk == 0.0
    assert ccf[0].reasoning_risk == 0.0
    assert ccf[0].token_savings > 0


def test_score_combines_savings_and_risk_with_explicit_lambdas():
    from tdf.reasoning import TransformReport
    r = TransformReport(
        name="x", tokens_before=100, tokens_after=80, token_savings=20,
        structural_risk=0.0, semantic_risk=0.0, reasoning_risk=0.8,
    )
    assert score(r) == 20 - 0.8
    assert score(r, lambda3=10.0) == 20 - 8.0
    assert score(r, lambda3=0.0) == 20
