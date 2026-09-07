"""Mission section 5D: template extraction (tdf/template.py).

Wires tdf.template's detection into tdf/optimize.py's optimize() pipeline
and tdf/parse.py's Para body-text reader, opt-in via render_tdf(...,
use_templates=True) -- default False, so every existing caller and every
existing test is completely unaffected (see
test_templates_off_by_default_never_emits_new_sigils below).

Run: .venv/bin/python -m pytest tests/test_template.py -q
"""

from __future__ import annotations

import sys
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tdf.emit import render_tdf  # noqa: E402
from tdf.ir import Doc, ListBlock, Para, Quote  # noqa: E402
from tdf.parse import parse_tdf  # noqa: E402
from tdf.template import build_templates, collides_with_marker  # noqa: E402
from tdf.tokens import count  # noqa: E402
from tdf.validate import validate  # noqa: E402


def _round_trip(doc: Doc, use_templates: bool = True) -> tuple[Doc, str]:
    work = deepcopy(doc)
    wire = render_tdf(work, legend=False, use_templates=use_templates)
    return parse_tdf(wire), wire


def _revenue_doc(n: int, start_value: int = 100, step: int = 7) -> Doc:
    countries = ["India", "Brazil", "Japan", "Egypt", "France", "Kenya", "Peru",
                 "Chile", "Ghana", "Nepal", "Laos", "Fiji", "Cuba", "Oman", "Togo"]
    assert n <= len(countries)
    paras = [Para(f"Revenue in {countries[i]} increased to {start_value + i * step}.")
             for i in range(n)]
    return Doc(blocks=paras)


def test_fires_and_round_trips_with_enough_instances():
    doc = _revenue_doc(15)
    restored, wire = _round_trip(doc)
    assert "!M " in wire
    assert wire.count("~1 ") >= 1
    assert [p.text for p in restored.blocks] == [p.text for p in doc.blocks]


def test_actually_saves_tokens_when_it_fires():
    doc = _revenue_doc(15)
    plain = render_tdf(deepcopy(doc), legend=False, use_templates=False)
    templated = render_tdf(deepcopy(doc), legend=False, use_templates=True)
    assert count(templated) < count(plain)


def test_declines_marginal_case_falls_back_to_plain_text():
    """6 short instances: the fixed overhead of the '!M <count>' header
    line plus the declaration line isn't recovered by such a small
    sample -- this is exactly the case that exposed a real bug in an
    earlier version of _cluster_economics (it omitted the header line's
    own cost, and would have fired here at a net LOSS: 53 tokens became
    56 in the buggy version, now correctly declines and stays at 53)."""
    doc = _revenue_doc(6)
    plain = render_tdf(deepcopy(doc), legend=False, use_templates=False)
    templated = render_tdf(deepcopy(doc), legend=False, use_templates=True)
    assert "!M" not in templated
    assert count(templated) == count(plain)


def test_templates_off_by_default_never_emits_new_sigils():
    doc = _revenue_doc(15)
    wire = render_tdf(deepcopy(doc), legend=False)
    assert "!M" not in wire
    assert "~1" not in wire
    restored = parse_tdf(wire)
    assert [p.text for p in restored.blocks] == [p.text for p in doc.blocks]


def test_fewer_than_min_instances_never_fires():
    doc = _revenue_doc(2)
    _, wire = _round_trip(doc)
    assert "!M" not in wire


def test_unrelated_sentences_do_not_cluster():
    doc = Doc(blocks=[
        Para("The quick brown fox jumps over the lazy dog today."),
        Para("A completely different sentence about something else."),
        Para("Yet another paragraph discussing an unrelated topic."),
    ])
    restored, wire = _round_trip(doc)
    assert "!M" not in wire
    assert [p.text for p in restored.blocks] == [p.text for p in doc.blocks]


def test_marker_collision_guard_disables_extraction_entirely():
    doc = _revenue_doc(15)
    doc.blocks.append(Para("~3 this looks like a reference but is real prose"))
    assert collides_with_marker(doc)
    templates = build_templates(deepcopy(doc))
    assert templates == []
    restored, wire = _round_trip(doc)
    assert "!M" not in wire
    assert [p.text for p in restored.blocks] == [p.text for p in doc.blocks]


def test_non_para_blocks_are_never_candidates():
    """Quote and ListBlock items are explicitly out of scope for this
    first version (see tdf/template.py's module docstring) -- they must
    survive completely unmodified even when surrounded by Para sentences
    that DO form a template."""
    doc = _revenue_doc(15)
    doc.blocks.insert(0, Quote("Revenue in Somewhere increased to 999."))
    doc.blocks.append(ListBlock(["Revenue in Nowhere increased to 1."], ordered=False))
    restored, wire = _round_trip(doc)
    quote_block = next(b for b in restored.blocks if isinstance(b, Quote))
    list_block = next(b for b in restored.blocks if isinstance(b, ListBlock))
    assert quote_block.text == "Revenue in Somewhere increased to 999."
    assert list_block.items == ["Revenue in Nowhere increased to 1."]


def test_composes_with_dictionary_substitution():
    """A phrase the word-level dictionary already turned into '§n' inside
    a matched sentence is just one more literal 'word' to this module --
    it must still round-trip through both mechanisms together."""
    countries = ["India", "Brazil", "Japan", "Egypt", "France", "Kenya",
                 "Peru", "Chile", "Ghana", "Nepal"]
    paras = [Para(f"Our comprehensive quarterly analysis shows revenue in "
                  f"{c} increased to {100 + i * 7} dollars this year.")
             for i, c in enumerate(countries)]
    doc = Doc(blocks=paras)
    work = deepcopy(doc)
    wire = render_tdf(work, legend=True, use_templates=True)
    restored = parse_tdf(wire)
    assert [p.text for p in restored.blocks] == [p.text for p in doc.blocks]


def test_multiple_independent_templates_in_one_document():
    revenue = _revenue_doc(15)
    headcount = [Para(f"Headcount in region {i} reached {200 + i * 3} employees total.")
                 for i in range(15)]
    doc = Doc(blocks=revenue.blocks + headcount)
    restored, wire = _round_trip(doc)
    assert wire.count("!M ") == 1  # one header line, declaring 2 templates
    m_header = next(l for l in wire.splitlines() if l.startswith("!M "))
    assert m_header == "!M 2"
    assert [p.text for p in restored.blocks] == [p.text for p in doc.blocks]


def test_validate_accepts_templated_output():
    doc = _revenue_doc(15)
    _, wire = _round_trip(doc)
    result = validate(wire)
    assert result.ok, result.violations


def test_max_slots_cap_prevents_near_total_mismatch_clustering():
    """Two sentences of the same length that differ at nearly every
    position are not a template -- they are two unrelated sentences that
    happen to share a word count."""
    doc = Doc(blocks=[
        Para("Alpha bravo charlie delta echo foxtrot golf."),
        Para("Zulu yankee xray whiskey victor uniform tango."),
        Para("One two three four five six seven."),
    ])
    _, wire = _round_trip(doc)
    assert "!M" not in wire


def test_single_and_empty_doc_do_not_crash():
    _round_trip(Doc(blocks=[Para("Just one short sentence here now.")]))
    _round_trip(Doc(blocks=[]))
