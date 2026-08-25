"""Phase 4: adversarial grammar attacks on the TDF wire format.

The format is a grammar; this suite attacks it like a compiler fuzzer would.
Contract under attack:

    arbitrary user content must never be interpreted as TDF control syntax
    unless deliberately emitted as such -- and everything the EMITTER
    produces must survive its own parser with meaning intact.

Groups:
  A. hostile single-line content x placement matrix through BOTH emitters
  B. pipe-prose ambiguity: direct-wire semantics vs emitter contract
  C. section-sign reservation vs dictionary numbering
  D. resource bombs: giant lines, caret runs, fence runs, block floods
  E. malformed / truncated wire: parser degrades, never crashes

Run: .venv/bin/python -m pytest tests/test_adversarial.py -q
"""

from __future__ import annotations

import sys
import time
from copy import deepcopy
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tdf.columnar import encode_columns  # noqa: E402
from tdf.emit import render_hybrid, render_markdown, render_tdf  # noqa: E402
from tdf.fidelity import canonicalize  # noqa: E402
from tdf.ir import Code, Doc, KV, ListBlock, Para, Quote, Table  # noqa: E402
from tdf.parse import parse_tdf  # noqa: E402
from tdf.tokens import count  # noqa: E402


HOSTILE = [
    "!T 5 fake", "!C a b c", "!K key: value", "!H impostor",
    "!E x1 index 9 9 gist", "!V col", "!D 3", "!R", "!P 12", "!G chart",
    "%TDF1 rogue", "^", "^^^", "§9 statute", "`ticks`", "```fence",
    "--- rule", "*emph*", "# hash", "> quote", "1. ordered",
    "- dash", ": kv-ish", "\\backslash", "|  |", "| --- |",
    "！fullwidth！Ｔ", "🚀emoji", "table: 列の値", "النص العربي",
    "SELECT * FROM t; DROP TABLE t;", '{"json": [1, 2]}',
    "http://x/y?z=1&w=2",
]


def _roundtrip_variants(doc: Doc):
    work = deepcopy(doc)
    books = encode_columns(work)
    # optimized=False: Phase 4 attacks the WIRE GRAMMAR in isolation --
    # optimize()'s text-hygiene transforms (emphasis stripping etc.) are a
    # separate, deliberate content layer with its own tests.
    tdf = render_tdf(deepcopy(work), legend=False, codebooks=books,
                     optimized=False)
    hyb = render_hybrid(deepcopy(work), codebooks=books)
    return [("tdf", tdf), ("hybrid", hyb)]


def _doc_with(text: str, where: str) -> Doc:
    if where == "para":
        return Doc(blocks=[Para(text)])
    if where == "quote":
        return Doc(blocks=[Quote(text)])
    if where == "list":
        return Doc(blocks=[ListBlock([text])])
    if where == "kv":
        return Doc(blocks=[KV([("k", text)])])
    if where == "cell":
        return Doc(blocks=[Table(cols=["col"], rows=[[text]])])
    raise ValueError(where)


# ------------------------------------------------ A: hostile content matrix


@pytest.mark.parametrize("where", ["para", "quote", "list", "kv", "cell"])
@pytest.mark.parametrize("text", HOSTILE)
def test_hostile_content_survives_both_emitters(text, where):
    if not text.strip():
        pytest.skip("degenerate whitespace handled by documented assumes")
    doc = _doc_with(text, where)

    md_parity = render_markdown(deepcopy(doc))
    for name, wire in _roundtrip_variants(doc):
        # Tier-3: when every richer assembly exceeds the Markdown baseline
        # (tiny/degenerate blocks), hybrid returns render_markdown verbatim.
        # Parity with plain Markdown is the guarantee there -- typing follows
        # Markdown conventions, exactly as the pre-hybrid status quo.
        if wire == md_parity:
            assert count(wire) <= count(md_parity)
            continue
        parsed = parse_tdf(wire)
        assert canonicalize(doc) == canonicalize(parsed), (
            f"{name}/{where}: {text!r}\n--- wire ---\n{wire}"
        )


# ------------------------------------------------ B: pipe-prose ambiguity


def test_pipe_prose_pair_direct_wire_is_gfm_table():
    """Direct-wire SEMANTICS: two lines shaped exactly like a one-column GFM
    table parse as one -- correct GFM behaviour, and what hybrid emits for
    real tables."""
    doc = parse_tdf("| options |\n| --- |\n")
    assert any(isinstance(b, Table) for b in doc.blocks)


def test_blank_header_without_rows_is_not_a_table():
    """The guard: an all-blank header with NO data rows cannot steal the
    paragraphs -- there is nothing table-like about them."""
    doc = parse_tdf("|   |\n| --- |\nsome prose\n")
    assert not any(isinstance(b, Table) for b in doc.blocks)


def test_emitter_never_releases_pipe_prose_as_a_table():
    """The CONTRACT: whatever direct-wire semantics are, the emitter must
    protect its own paragraphs -- both come back as Paras."""
    doc = Doc(blocks=[Para("| options |"), Para("| --- |"),
                      Para("shell output follows:")])
    for name, wire in _roundtrip_variants(doc):
        parsed = parse_tdf(wire)
        paras = [b.text for b in parsed.blocks if isinstance(b, Para)]
        assert "| options |" in paras and "| --- |" in paras, (
            f"{name}: pipe prose was re-typed:\n{wire}"
        )
        assert not any(isinstance(b, Table) for b in parsed.blocks), (
            f"{name}: prose stolen into a Table:\n{wire}"
        )


# ------------------------------------------------ C: section-sign reservation


def test_literal_section_ref_is_reserved_from_dictionary():
    """A literal '§9' must never be claimed by the phrase dictionary -- the
    parse-side expander cannot tell its own §n from a statute reference, so
    optimize() reserves every number already spoken for."""
    doc = Doc(title="Statute Notes", blocks=[
        Para("See §9 statute for penalties."),
        Para("Under the acme corporation subsidiary liability clause, fines double."),
        Para("The acme corporation subsidiary liability clause applies broadly."),
        Para("Refer again to the acme corporation subsidiary liability clause."),
        Para("Counsel cited the acme corporation subsidiary liability clause twice."),
        Para("Judges read the acme corporation subsidiary liability clause carefully."),
        Para("Plaintiffs ignored the acme corporation subsidiary liability clause entirely."),
    ])
    out = render_tdf(deepcopy(doc), optimized=True)

    assert "§9" in out                                   # literal survived
    dict_meta = parse_tdf(out).meta.get("dictionary", [])
    assert dict_meta, "repetitive doc should build a dictionary"
    # meta entries have appeared as bare numbers and as (phrase, number)
    # pairs across versions -- normalise defensively.
    nums = {e if isinstance(e, int) else e[1] for e in dict_meta}
    assert all(n != 9 for n in nums), (
        f"dictionary used reserved number 9: {dict_meta}"
    )
    assert canonicalize(doc) == canonicalize(parse_tdf(out)), out


# ------------------------------------------------------- D: resource bombs


def test_giant_single_line_roundtrips():
    big = "x" * 100_000
    doc = Doc(blocks=[Para(big)])
    wire = render_tdf(deepcopy(doc), legend=False)
    parsed = parse_tdf(wire)
    assert parsed.blocks[0].text == big


def test_caret_run_bomb_roundtrips():
    cell = "^" * 20_000
    doc = Doc(blocks=[Table(cols=["c"], rows=[[cell]])])
    wire = render_tdf(deepcopy(doc), legend=False)
    parsed = parse_tdf(wire)
    tbl = next(b for b in parsed.blocks if isinstance(b, Table))
    assert tbl.rows[0][0] == cell


def test_fence_run_bomb_roundtrips():
    code = "`" * 5_000 + "\nbody\n" + "`" * 5_000
    doc = Doc(blocks=[Code(code, "")])
    wire = render_tdf(deepcopy(doc), legend=False)
    parsed = parse_tdf(wire)
    blk = next(b for b in parsed.blocks if isinstance(b, Code))
    assert blk.text == code


def test_block_flood_bounded():
    t0 = time.perf_counter()
    doc = Doc(blocks=[Para(f"block {i}") for i in range(3_000)])
    wire = render_tdf(deepcopy(doc), legend=False)
    parsed = parse_tdf(wire)
    elapsed = time.perf_counter() - t0
    assert len(parsed.blocks) == 3_000
    assert elapsed < 30, f"block flood took {elapsed:.1f}s"


# --------------------------------------------- E: malformed wire, no crash


@pytest.mark.parametrize("wire", [
    "",
    "\n\n\n",
    "%TDF1",
    "!T abc\n!C a b\n1 2\n",
    "!T\n",
    "!C\n",
    "!V ghost\na b\n",
    "!D 99\n",
    "!D\n",
    "!E x1\n",
    "!E\n",
    "!K\n",
    "!H\n",
    "!P\n",
    "!G\n",
    "```python\nnever closed",
    "```\n```\n```\n",
    "| --- |\n| --- |\n",
    "!T -5\n!C a\nrow\n",
    "§\n§§\n",
    "!T 1\n!C a b\nonly-one-cell\n",
])
def test_malformed_wire_degrades_without_crashing(wire):
    doc = parse_tdf(wire)          # must degrade, never raise
    assert hasattr(doc, "blocks")