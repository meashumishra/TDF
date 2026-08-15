"""Correctness tests. Run: .venv/bin/python -m pytest tests/ -q"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402

from tdf.emit import extract_sections, render_markdown, render_skeleton, render_tdf  # noqa: E402
from tdf.fidelity import compare  # noqa: E402
from tdf.ir import Doc, Heading, ListBlock, Para, Table  # noqa: E402
from tdf.optimize import clean_text, elide_repeats, normalize_cell, optimize  # noqa: E402
from tdf.parse import parse_tdf  # noqa: E402
from tdf.readers import read  # noqa: E402
from tdf.tokens import count  # noqa: E402

SAMPLES = ROOT / "samples"
REAL = ROOT / "samples_real"


# ------------------------------------------------------------------ unit level

@pytest.mark.parametrize("raw,want", [
    ("\u201csmart\u201d", '"smart"'),
    ("em\u2014dash", "em-dash"),
    ("**bold** text", "bold text"),
    # Single-word underscore emphasis ("_ital_", "__strong__") is no longer
    # stripped -- it is lexically identical to a code identifier like
    # `__init__` (single "word", underscore-delimited), and there is no
    # local-pattern rule that can tell them apart. Multi-word underscore
    # emphasis ("_this is emphasis_") still strips; see the optimizer
    # red-team audit's P0 underscore/identifier-corruption fix.
    ("_ital_ and __strong__", "_ital_ and __strong__"),
    ("_this is emphasis_ and __this is strong__", "this is emphasis and this is strong"),
    ("a\u00a0b", "a b"),
    ("multi   space", "multi space"),
])
def test_clean_text(raw, want):
    assert clean_text(raw) == want


@pytest.mark.parametrize("raw,want", [
    ("$1,234.00", "$1234.00"),
    ("1,000", "1000"),
    ("(500)", "-500"),
    # Trailing decimal zeros are NOT stripped -- "12.50" and "12.5" claim
    # different precision, and there is no way to tell from the string
    # alone which trailing zeros are real digits of precision versus
    # formatting noise, so the only safe choice is to leave them as-is. See
    # the independent audit's BUG-3.
    ("12.50%", "12.50%"),
    ("3.1400", "3.1400"),
    ("not a number", "not a number"),
    # A parenthesis is only an accounting-negative marker as a MATCHED pair.
    # An unpaired paren is not a number at all -- fabricating a sign from it
    # invents data. See the optimizer red-team audit's P1 paren fix.
    ("123)", "123)"),
    ("(123", "(123"),
    ("+123)", "+123)"),
])
def test_normalize_cell(raw, want):
    assert normalize_cell(raw) == want


def test_elide_repeats_marks_only_duplicates():
    rows = [["EMEA", "a"], ["EMEA", "b"], ["APAC", "c"]]
    out = elide_repeats(rows)
    assert out[1][0] == "^"
    assert out[2][0] == "APAC"
    assert out[1][1] == "b"


def test_table_pads_ragged_rows():
    """Rows wider than the header must not be truncated."""
    t = Table(["a"], [["1", "2", "3"]])
    assert len(t.cols) == 3
    assert t.rows[0] == ["1", "2", "3"]


def test_dictionary_only_fires_when_it_saves():
    phrase = ("the quick brown fox jumps over the lazy dog repeatedly and "
              "without any hesitation whatsoever")
    d = Doc(blocks=[Para(f"{phrase} number {i}.") for i in range(6)])
    arts = optimize(d)
    assert arts["dictionary"], "a 6x repeated long phrase should be dictionarised"
    assert all("\u00a7" in b.text for b in d.blocks)


def test_dictionary_skipped_for_unique_text():
    d = Doc(blocks=[Para(f"Unique sentence number {i} with distinct wording.") for i in range(6)])
    arts = optimize(d)
    assert not arts["dictionary"]


def test_boilerplate_deduplicated():
    """use_boilerplate defaults to False (see optimize()'s docstring and the
    independent audit's BUG-4 -- the heuristic cannot distinguish page
    furniture from an ordinary repeated sentence), so this test opts in
    explicitly to verify the mechanism still works correctly for callers
    who know their source has genuine running headers/footers."""
    d = Doc(blocks=[b for i in range(5) for b in
                    (Para("ACME CONFIDENTIAL DO NOT DISTRIBUTE"), Para(f"Real content {i}."))])
    arts = optimize(d, use_boilerplate=True)
    assert arts["boilerplate"] == ["ACME CONFIDENTIAL DO NOT DISTRIBUTE"]
    assert sum(1 for b in d.blocks if isinstance(b, Para)) == 5


def test_boilerplate_off_by_default():
    """See the independent audit's BUG-4: the heuristic fires on ordinary
    repeated prose (confirmed on real technical documentation), not just
    page furniture, so it must not run unless explicitly requested."""
    d = Doc(blocks=[b for i in range(5) for b in
                    (Para("ACME CONFIDENTIAL DO NOT DISTRIBUTE"), Para(f"Real content {i}."))])
    arts = optimize(d)
    assert arts["boilerplate"] == []
    assert sum(1 for b in d.blocks if isinstance(b, Para)) == 10


# --------------------------------------------------------------- round tripping

def _roundtrip(doc: Doc) -> dict:
    original = copy.deepcopy(doc)
    return compare(original, parse_tdf(render_tdf(doc)))


def test_roundtrip_constant_column_and_units():
    t = Table(["id", "amount", "currency"],
              [[str(i), f"${i * 100}.00", "USD"] for i in range(1, 9)])
    res = _roundtrip(Doc(title="T", blocks=[t]))
    assert res["distinct_recall"] == 1.0


# A blank cell ("") is a real, distinct value -- a column that is "USD" on
# every row but one, where that one row is blank, is NOT constant, and must
# never be silently collapsed to a single "USD" fact that erases the blank.
# See the optimizer red-team audit's P0 constant-column investigation
# (confirmed no bug in drop_constant_columns itself -- these lock the
# behavior in against regression -- but the full pipeline is exercised too,
# since drop_constant_columns alone isn't the whole story: emit/parse must
# also preserve the surviving column faithfully).
@pytest.mark.parametrize("rows", [
    pytest.param([["1", "USD"], ["2", ""], ["3", "USD"], ["4", "USD"]], id="blank-middle"),
    pytest.param([["1", ""], ["2", "USD"], ["3", "USD"], ["4", "USD"]], id="blank-first"),
    pytest.param([["1", "USD"], ["2", "USD"], ["3", "USD"], ["4", ""]], id="blank-last"),
    pytest.param([["1", "USD"], ["2", "EUR"], ["3", "USD"], ["4", "USD"]], id="multi-distinct"),
])
def test_constant_column_with_blank_is_not_collapsed(rows):
    from tdf.optimize import drop_constant_columns
    cols, out_rows, constants = drop_constant_columns(["id", "currency"], rows)
    assert constants == []
    assert cols == ["id", "currency"]
    assert out_rows == rows

    t = Table(["id", "currency"], [list(r) for r in rows])
    res = _roundtrip(Doc(blocks=[t]))
    assert res["distinct_recall"] == 1.0
    parsed = parse_tdf(render_tdf(Doc(blocks=[Table(["id", "currency"], [list(r) for r in rows])])))
    parsed_table = next(b for b in parsed.blocks if isinstance(b, Table))
    assert parsed_table.rows == rows


def test_constant_column_all_genuinely_constant_is_dropped():
    from tdf.optimize import drop_constant_columns
    rows = [["1", "USD"], ["2", "USD"], ["3", "USD"], ["4", "USD"]]
    cols, out_rows, constants = drop_constant_columns(["id", "currency"], rows)
    assert constants == [(1, "currency", "USD")]
    assert cols == ["id"]
    assert out_rows == [["1"], ["2"], ["3"], ["4"]]


def test_constant_column_ragged_row_is_not_collapsed():
    """A row missing the trailing cell entirely (ragged) is not the same
    claim as that cell being blank -- drop_constant_columns must not treat a
    missing cell as agreeing with the other rows' value."""
    from tdf.optimize import drop_constant_columns
    rows = [["1", "USD"], ["2", "USD"], ["3", "USD"], ["4"]]
    cols, out_rows, constants = drop_constant_columns(["id", "currency"], rows)
    assert constants == []
    assert cols == ["id", "currency"]


def test_roundtrip_cells_with_spaces_and_empties():
    t = Table(["a", "b", "c"],
              [["hello world", "", "x"], ['say "hi"', "b b", ""], ["", "", ""]])
    res = _roundtrip(Doc(blocks=[t]))
    assert res["distinct_recall"] == 1.0


def test_roundtrip_preserves_list_and_headings():
    d = Doc(title="Doc", blocks=[Heading(1, "Alpha"), ListBlock(["one", "two"]),
                                 Heading(2, "Beta"), Para("Body text here.")])
    res = _roundtrip(d)
    assert res["distinct_recall"] == 1.0


@pytest.mark.parametrize("name", [
    "runbook.md", "orders.csv", "handbook.html",
    "sales_report.xlsx", "services_agreement.docx",
    "quarterly_deck.pptx", "operating_review.pdf",
])
def test_sample_roundtrip_is_lossless(name):
    path = SAMPLES / name
    if not path.exists():
        pytest.skip("run bench/make_samples.py first")
    res = _roundtrip(read(path))
    assert res["distinct_recall"] == 1.0, res["missing_sample"]


@pytest.mark.parametrize("name", [
    "runbook.md", "orders.csv", "handbook.html",
    "sales_report.xlsx", "services_agreement.docx",
])
def test_tdf_is_smaller_than_markdown(name):
    path = SAMPLES / name
    if not path.exists():
        pytest.skip("run bench/make_samples.py first")
    doc = read(path)
    md = count(render_markdown(copy.deepcopy(doc)))
    td = count(render_tdf(copy.deepcopy(doc), legend=False))
    assert td < md, f"{name}: tdf {td} >= markdown {md}"


# ------------------------------------------------------------------- skeleton

def test_skeleton_ids_are_unique_and_expandable():
    d = Doc(blocks=[Heading(3, "Orphan"), Heading(1, "One"), Para("a"),
                    Heading(2, "One A"), Para("b"), Heading(1, "Two"), Para("c")])
    skel = render_skeleton(copy.deepcopy(d))
    ids = [ln.split(" ", 1)[0] for ln in skel.splitlines()[1:] if ln and ln[0].isdigit()]
    assert len(ids) == len(set(ids)), f"duplicate ids: {ids}"

    sub = extract_sections(copy.deepcopy(d), ["2"])
    texts = [getattr(b, "text", "") for b in sub.blocks]
    assert "One" in texts and "a" in texts
    assert "c" not in texts


def test_skeleton_is_far_smaller_than_body():
    path = SAMPLES / "handbook.html"
    if not path.exists():
        pytest.skip("run bench/make_samples.py first")
    doc = read(path)
    skel = count(render_skeleton(copy.deepcopy(doc)))
    full = count(render_tdf(copy.deepcopy(doc)))
    assert skel < full * 0.2


# --------------------------------------------------- borderless PDF tables

TPDF = ROOT / "samples_tables"


def _pdf_tables(name):
    import pymupdf as fitz
    from tdf.readers.pdf_tables import find_borderless_tables
    path = TPDF / name
    if not path.exists():
        pytest.skip("run bench/make_table_pdfs.py first")
    return find_borderless_tables(fitz.open(path)[0])


def test_borderless_table_is_detected():
    """PyMuPDF's ruled-line finder returns nothing here; ours must not."""
    res = _pdf_tables("borderless_report.pdf")
    assert len(res) == 1
    grid = res[0][0]
    assert grid[0] == ["region", "product", "units", "revenue", "status"]
    assert grid[1] == ["EMEA", "Cloud", "412", "1284000", "closed"]
    assert len(grid) == 9


def test_ruled_table_still_detected():
    assert len(_pdf_tables("ruled_report.pdf")) == 1


def test_prose_is_never_mistaken_for_a_table():
    """The failure mode of strategy='text': prose shredded into fake cells."""
    assert _pdf_tables("prose_only.pdf") == []


def test_prose_only_pdf_yields_no_table_blocks():
    path = TPDF / "prose_only.pdf"
    if not path.exists():
        pytest.skip("run bench/make_table_pdfs.py first")
    assert not [b for b in read(path).blocks if isinstance(b, Table)]


def test_borderless_pdf_roundtrips_losslessly():
    path = TPDF / "borderless_report.pdf"
    if not path.exists():
        pytest.skip("run bench/make_table_pdfs.py first")
    doc = read(path)
    assert [b for b in doc.blocks if isinstance(b, Table)]
    assert _roundtrip(doc)["distinct_recall"] == 1.0


def test_table_text_not_duplicated_as_paragraphs():
    path = TPDF / "borderless_report.pdf"
    if not path.exists():
        pytest.skip("run bench/make_table_pdfs.py first")
    paras = " ".join(b.text for b in read(path).blocks if isinstance(b, Para))
    assert "1284000" not in paras


def test_centered_columns_merge_to_true_arity():
    """Centered cells must not split one column into several sparse anchors."""
    import pymupdf as fitz
    from tdf.readers.pdf_tables import find_borderless_tables
    path = ROOT / "samples_real" / "attention.pdf"
    if not path.exists():
        pytest.skip("real samples not present")
    res = find_borderless_tables(fitz.open(path)[5])
    assert res, "the paper's Table 1 is borderless and should be found"
    grid = res[0][0]
    assert all(len(r) == 4 for r in grid)
    assert grid[0][0] == "Self-Attention"


# ------------------------------------------------------------ density tiering

from tdf.ir import Elision  # noqa: E402
from tdf.tier import is_index_like, restore, sentence_density, tier  # noqa: E402

PROSE = ("The controller manager runs reconciliation loops. Each loop compares the "
         "observed state to the desired state. When they differ, it issues changes. "
         "This continues until the cluster converges. Operators rely on it. ") * 3
NAV = " ".join(["Overview Components Objects Names Labels Selectors Namespaces "
                "Annotations Finalizers Owners Dependents Storage Versions"] * 12)


def test_sentence_density_separates_prose_from_index():
    assert sentence_density(PROSE) > 2.0
    assert sentence_density(NAV) == 0.0


def test_index_like_requires_both_length_and_flatness():
    assert is_index_like(NAV)
    assert not is_index_like(PROSE)
    assert not is_index_like("Short nav list")  # too small to pay for a marker


def test_tier_elides_index_and_keeps_prose():
    d = Doc(blocks=[Para(PROSE), Para(NAV), Para(PROSE)])
    store = tier(d)
    assert len(store) == 1
    kinds = [type(b).__name__ for b in d.blocks]
    assert kinds == ["Para", "Elision", "Para"]
    e = d.blocks[1]
    assert e.tokens == count(NAV) and e.gist


def test_tier_is_reversible():
    d = Doc(blocks=[Para(PROSE), Para(NAV)])
    store = tier(d)
    restore(d, store)
    assert [type(b).__name__ for b in d.blocks] == ["Para", "Para"]
    assert d.blocks[1].text == NAV


def test_elision_survives_the_tdf_round_trip():
    """The marker must reach the model intact -- that is the whole contract."""
    d = Doc(title="T", blocks=[Para(PROSE), Para(NAV)])
    tier(d)
    back = parse_tdf(render_tdf(d))
    els = [b for b in back.blocks if isinstance(b, Elision)]
    assert len(els) == 1
    assert els[0].eid == "x1" and els[0].tokens == count(NAV)


def test_tiering_never_fires_on_ordinary_prose_documents():
    for name in ("handbook.html", "runbook.md"):
        path = SAMPLES / name
        if not path.exists():
            pytest.skip("run bench/make_samples.py first")
        assert tier(read(path)) == {}, f"{name} should have no index regions"


def test_tiering_cuts_the_navigation_heavy_document():
    path = ROOT / "samples_real" / "kubernetes_docs.html"
    if not path.exists():
        pytest.skip("real samples not present")
    doc = read(path)
    md = count(render_markdown(copy.deepcopy(doc)))
    tiered = copy.deepcopy(doc)
    assert tier(tiered)
    assert count(render_tdf(tiered, legend=False)) < md * 0.75


# ------------------------------------------- columnar coding & Re-Pair dictionary

from tdf.columnar import decode_columns, encode_columns  # noqa: E402
from tdf.optimize import _iter_texts  # noqa: E402
from tdf.repair import repair_candidates, select  # noqa: E402


def _wide_table(n=60):
    countries = ["Afghanistan", "Bangladesh", "Cambodia", "Denmark"]
    rows = [[countries[i % 4], f"{1000 + i}", "Gross domestic product"] for i in range(n)]
    return Table(cols=["Country Name", "Value", "Indicator"], rows=rows)


def test_columnar_coding_is_lossless():
    doc = Doc(blocks=[_wide_table()])
    original = [list(r) for r in doc.blocks[0].rows]
    books = encode_columns(doc)
    assert books, "a 4-value column over 60 rows must be worth coding"
    assert doc.blocks[0].rows != original
    decode_columns(books)
    assert doc.blocks[0].rows == original


def test_codebook_is_labelled_from_cols_not_the_first_data_row():
    """rows[0] is data; reading a header off it mislabels and under-codes."""
    doc = Doc(blocks=[_wide_table()])
    books = encode_columns(doc)
    headers = {b.header for b in books}
    assert "Country Name" in headers
    assert "Afghanistan" not in headers
    # every row, including the first, must be coded
    assert all(len(r[0]) <= 3 for r in doc.blocks[0].rows)


def test_columnar_declines_high_cardinality_and_tiny_tables():
    unique = Table(cols=["id"], rows=[[f"value-number-{i}"] for i in range(60)])
    assert encode_columns(Doc(blocks=[unique])) == []
    tiny = Table(cols=["c"], rows=[["Afghanistan"], ["Bangladesh"]])
    assert encode_columns(Doc(blocks=[tiny])) == []


def test_codes_avoid_colliding_with_literal_cell_values():
    rows = [["Afghanistan", "a"], ["Bangladesh", "a"], ["Cambodia", "b"]] * 20
    doc = Doc(blocks=[Table(cols=["Country", "Flag"], rows=rows)])
    books = encode_columns(doc)
    for book in books:
        assert not (set(book.mapping) & {"a", "b"})


def test_repair_beats_greedy_extension_on_overlapping_phrases():
    """The failure greedy seed-and-extend cannot arbitrate."""
    text = "alpha beta gamma delta epsilon " * 6
    words = text.split()
    cands = repair_candidates(words, min_occurrences=3)
    assert any(len(c.split()) >= 4 for c in cands)
    accepted = select(cands, text)
    assert accepted and all(text.count(p) >= 3 for p in accepted)


def test_dictionary_now_sees_list_items():
    """List text was invisible to the optimizer; on nav pages it is the bulk."""
    phrase = "kubernetes cluster administration and configuration guide"
    doc = Doc(blocks=[ListBlock(items=[f"{phrase} {i}" for i in range(12)])])
    slots = [v for _, _, v in _iter_texts(doc)]
    assert len(slots) == 12


# --------------------------------------------------------------- robustness

@pytest.mark.parametrize("text", [
    "!E x1 index 9 9 g", "!T 5 caption", "!Try it now", "!Kubernetes is great",
    "!R", "!D", "!C a b", "!P 3", "!!already escaped", "# not a heading?",
])
def test_sigil_shaped_text_survives(text):
    """Body text that looks like structure must not be reparsed as structure."""
    d = Doc(blocks=[Para(text), Para("sentinel tail marker")])
    assert _roundtrip(d)["distinct_recall"] == 1.0


def test_malformed_sigil_arguments_do_not_crash():
    """A parser fed adversarial input must degrade, never raise."""
    for bad in ["!P notanumber", "!P", "!T x cap", "!T", "!E", "!C", "!F",
                "!E x1 nope nope", "!D\nnotanentry", "!R"]:
        parse_tdf("%TDF1\n" + bad + "\nsentinel\n")


def test_newline_in_cell_preserves_grid():
    """A cell with a line break must not shift every following row."""
    d = Doc(blocks=[Table(cols=["a", "b"],
                          rows=[["x\ny", "z"], ["p", "q"], ["r", "s"]])])
    back = parse_tdf(render_tdf(d, legend=False))
    t = [b for b in back.blocks if isinstance(b, Table)][0]
    assert len(t.rows) == 3
    assert t.rows[1] == ["p", "q"]


def test_boilerplate_block_ends_at_next_heading():
    """`!R` must stop at "## x", not only at "# x"."""
    tdf = "%TDF1\n!R\nboiler line\n## Section Two\n- item one\n"
    out = parse_tdf(tdf)
    assert any(isinstance(b, Heading) for b in out.blocks)
    assert any(isinstance(b, ListBlock) for b in out.blocks)


def test_fuzz_campaign_is_lossless():
    """Deterministic slice of the randomised harness, so CI catches regressions."""
    from tests.fuzz import random_doc, check
    import random as _r
    bad = []
    for seed in range(120):
        ok, rep = check(random_doc(_r.Random(seed)))
        if not ok:
            bad.append((seed, round(rep["distinct_recall"], 3)))
    assert not bad, bad


def test_columnar_codes_are_decoded_on_parse():
    """Coded columns must come back as values, not as one-letter codes.

    Distinct-content recall cannot catch this: the values still appear in the
    codebook lines, so the document scores 100% while every coded cell is
    wrong. This asserts the grid itself.
    """
    from tdf.columnar import encode_columns
    path = SAMPLES / "orders.csv"
    if not path.exists():
        pytest.skip("run bench/make_samples.py first")
    doc = read(path)
    work = copy.deepcopy(doc)
    books = encode_columns(work)
    assert books, "expected orders.csv to have codeable columns"
    out = render_tdf(work, codebooks=books, legend=False)
    got = [b for b in parse_tdf(out).blocks if isinstance(b, Table)][0]
    want = [b for b in doc.blocks if isinstance(b, Table)][0]
    # Only the coded columns are asserted: other columns carry deliberate
    # numeric normalisation ("$74,974.00" -> "$74974"), which is by design.
    for book in books:
        ci = want.cols.index(book.header)
        assert [r[ci] for r in got.rows[:20]] == [r[ci] for r in want.rows[:20]], book.header


def test_newline_in_table_caption_does_not_shift_rows():
    """A caption with a line break consumed declared rows (fuzz seed 593)."""
    d = Doc(blocks=[Table(cols=["a", "b"], caption="multi\nline\ntext",
                          rows=[["1", "2"], ["3", "4"], ["5", "6"]])])
    t = [b for b in parse_tdf(render_tdf(d, legend=False)).blocks
         if isinstance(b, Table)][0]
    assert len(t.rows) == 3
    assert t.rows[0] == ["1", "2"]


def test_seed_593_document_roundtrips():
    """The exact failing case from the fuzz campaign."""
    from tests.fuzz import random_doc, check
    import random as _r
    ok, rep = check(random_doc(_r.Random(593)))
    assert ok, rep["missing_sample"]


# --------------------------------------------------------- structural validity

def test_boilerplate_region_does_not_swallow_following_list():
    """!R followed immediately by a list must not eat the items (k8s corpus bug)."""
    tdf = "%TDF1\n!R\nrepeated footer\n- Documentation\n- Training\n"
    out = parse_tdf(tdf)
    lists = [b for b in out.blocks if isinstance(b, ListBlock)]
    assert lists and lists[0].items == ["Documentation", "Training"]


def test_validate_accepts_corpus_and_catches_truncation(tmp_path):
    from tdf.validate import validate
    for name in ("orders.csv", "quarterly_deck.pptx"):
        path = SAMPLES / name
        if not path.exists():
            pytest.skip("run bench/make_samples.py first")
        assert validate(render_tdf(read(path))).ok, name
    truncated = "%TDF1\n!T 5 cap\n!C a b\n1 2\n"
    res = validate(truncated)
    assert not res.ok
    assert any(v.rule == "declared-rows" for v in res.violations)


def test_reemission_converges_on_kubernetes():
    """Optimization normalizes, so one re-emit may differ -- but it must reach
    a fixed point, and content must be stable at every step."""
    path = REAL / "kubernetes_docs.html"
    if not path.exists():
        pytest.skip("real corpus not present")
    cur = render_tdf(read(path), legend=False)
    for _ in range(8):
        nxt = render_tdf(parse_tdf(cur), legend=False)
        assert compare(parse_tdf(cur), parse_tdf(nxt))["distinct_recall"] == 1.0
        if nxt == cur:
            return
        cur = nxt
    raise AssertionError("did not converge within 8 iterations")
