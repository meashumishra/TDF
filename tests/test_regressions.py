"""Regression tests for the red-team correctness audit.

Each test reproduces one confirmed bug via the actual emit/parse pipeline
(not a synthetic check of internal helpers) and asserts the fix. See the
audit report for root-cause analysis, false positives, and the handful of
genuine format-level ambiguities that were documented rather than "fixed"
(adjacent same-line-marker blocks, KV keys containing their own colon, and
other degenerate empty-content cases -- all covered by targeted `assume()`
filters in test_properties.py with inline rationale).

Run: .venv/bin/python -m pytest tests/test_regressions.py -q
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tdf.columnar import encode_columns  # noqa: E402
from tdf.emit import render_tdf  # noqa: E402
from tdf.fidelity import canonicalize, compare, content_bag  # noqa: E402
from tdf.ir import Code, Doc, Figure, Heading, KV, ListBlock, Para, Quote, Table  # noqa: E402
from tdf.parse import parse_tdf  # noqa: E402
from tdf.validate import validate  # noqa: E402


def roundtrip(doc: Doc, *, optimized: bool = False, legend: bool = False):
    """Emit -> parse, using real codebooks (matches what `tdf convert` runs
    by default) so table-level bugs that only appear with columnar encoding
    active aren't missed."""
    original = copy.deepcopy(doc)
    working = copy.deepcopy(doc)
    books = encode_columns(working)
    out = render_tdf(working, legend=legend, optimized=optimized, codebooks=books)
    return out, parse_tdf(out), original


# --------------------------------------------------------- issue 1: code fence

def test_code_block_survives_embedded_fence():
    """A ``` sequence inside a Code block must not prematurely close it."""
    text = 'print("hello")\n```\nEnd of embedded example.'
    doc = Doc(blocks=[Code(text, "python")])
    out, parsed, original = roundtrip(doc)

    assert len(parsed.blocks) == 1, f"code block fragmented:\n{out}"
    assert isinstance(parsed.blocks[0], Code)
    assert parsed.blocks[0].text == text
    assert parsed.blocks[0].lang == "python"


def test_code_block_with_longer_embedded_fence():
    """A run of 4+ backticks inside the code must still not close the block
    (the emitter must pick a fence longer than *any* run in the content)."""
    text = "before\n`````\nafter"
    doc = Doc(blocks=[Code(text, "")])
    out, parsed, original = roundtrip(doc)

    assert len(parsed.blocks) == 1, f"code block fragmented:\n{out}"
    assert parsed.blocks[0].text == text


def test_para_starting_with_backticks_is_not_read_as_a_fence():
    """Ordinary prose that happens to start with ``` must not open a fake
    code block on parse (looks_structural was missing this case)."""
    doc = Doc(blocks=[Para("```python not actually code"), Para("next paragraph")])
    out, parsed, original = roundtrip(doc)

    assert canonicalize(original) == canonicalize(parsed), out


# ------------------------------------ issues 3/4/12: multiline block injection

def test_multiline_list_item_stays_one_item():
    doc = Doc(blocks=[ListBlock(["line one\nline two", "second item"], ordered=False)])
    out, parsed, original = roundtrip(doc)

    assert len(parsed.blocks) == 1, f"list item split into extra blocks:\n{out}"
    assert parsed.blocks[0].items == ["line one line two", "second item"]


def test_multiline_quote_stays_one_block():
    doc = Doc(blocks=[Quote("line one\nline two\nline three")])
    out, parsed, original = roundtrip(doc)

    assert len(parsed.blocks) == 1, f"quote split into extra blocks:\n{out}"
    assert isinstance(parsed.blocks[0], Quote)
    assert parsed.blocks[0].text == "line one line two line three"


def test_list_item_injection_does_not_open_a_fake_table():
    """A list item whose (buggy, pre-fix) second physical line looked like
    `!T 5 ...` used to open a real table sigil and swallow the next block."""
    doc = Doc(blocks=[
        ListBlock(["Try this:\n!T 5 fake"], ordered=False),
        Para("after"),
    ])
    out, parsed, original = roundtrip(doc)

    assert not any(isinstance(b, Table) for b in parsed.blocks), f"fake table injected:\n{out}"
    assert canonicalize(original) == canonicalize(parsed), out


def test_heading_with_embedded_newline_does_not_inject_fake_block():
    """Regression for the worst variant found: a heading with an embedded
    newline whose continuation looked like a sigil used to vanish into
    doc.title while fabricating a fake Table that swallowed the next Para."""
    doc = Doc(blocks=[Heading(1, "Chapter 1\n!T 5 fake"), Para("after")])
    out, parsed, original = roundtrip(doc)

    assert not any(isinstance(b, Table) for b in parsed.blocks), f"fake table injected:\n{out}"
    assert any(isinstance(b, Para) and b.text == "after" for b in parsed.blocks), (
        f"following paragraph was swallowed:\n{out}"
    )


def test_figure_with_embedded_newline_does_not_inject_fake_block():
    doc = Doc(blocks=[Figure("a chart\n!K fake"), Para("after")])
    out, parsed, original = roundtrip(doc)

    assert not any(isinstance(b, KV) for b in parsed.blocks), f"fake KV injected:\n{out}"
    assert canonicalize(original) == canonicalize(parsed), out


def test_doc_title_with_embedded_newline_does_not_inject_fake_block():
    """doc.title is emitted outside the main block loop and was missed by
    the first pass of the Heading/Quote/ListBlock/Figure fix."""
    doc = Doc(title="line one\n!T 5 fake", blocks=[])
    out, parsed, original = roundtrip(doc)

    assert not any(isinstance(b, Table) for b in parsed.blocks), f"fake table injected:\n{out}"
    val = validate(out)
    assert val.ok, f"emitted invalid TDF:\n{out}\n{val.violations}"


# --------------------------------------------------- issue 15: caret collision

def test_literal_caret_cell_is_not_confused_with_back_reference_marker():
    rows = [["X", "first"], ["^", "second"], ["^", "third"]]
    doc = Doc(blocks=[Table(["Symbol", "Label"], rows)])
    out, parsed, original = roundtrip(doc)

    assert parsed.blocks[0].rows == rows, f"caret cells corrupted:\n{out}"


def test_genuine_repeated_cell_still_compresses():
    """The caret-collision fix must not disable normal ^ compression."""
    rows = [["duplicate value here", "a"], ["duplicate value here", "b"], ["other value", "c"]]
    doc = Doc(blocks=[Table(["Symbol", "Label"], rows)])
    out, parsed, original = roundtrip(doc)

    assert parsed.blocks[0].rows == rows
    assert any(line.split("\t")[0] == "^" or line.split(" ")[0] == "^" for line in out.split("\n")), (
        f"expected marker not used:\n{out}"
    )


def test_double_caret_literal_round_trips():
    """Escaping scheme must handle values that are themselves multi-caret,
    not just the single-caret case."""
    rows = [["^^", "a"], ["X", "b"], ["^^", "c"]]
    doc = Doc(blocks=[Table(["Symbol", "Label"], rows)])
    out, parsed, original = roundtrip(doc)

    assert parsed.blocks[0].rows == rows, f"double-caret literal corrupted:\n{out}"


# -------------------------------------------- issue 17: verify/convert parity

def test_cmd_verify_pipeline_uses_columnar_encoding():
    """cmd_verify must exercise the same codebooks path cmd_convert uses by
    default -- otherwise a bug reachable only through columnar encoding could
    pass verification and still ship. Simulated here at the library level
    (see tdf/cli.py cmd_verify for the actual CLI wiring)."""
    from tdf.columnar import encode_columns

    rows = [[f"Person{i}", ["Asia Pacific Region", "Europe Middle East Africa",
                             "Americas Region North South"][i % 3], str(100000 + i)]
            for i in range(40)]
    doc = Doc(blocks=[Table(["Person", "Region", "Salary"], rows)])
    original = copy.deepcopy(doc)
    working = copy.deepcopy(doc)

    books = encode_columns(working)
    assert books, "test table should have triggered columnar encoding"
    out = render_tdf(working, legend=False, codebooks=books)
    restored = parse_tdf(out)
    report = compare(original, restored)
    assert report["distinct_recall"] == 1.0


def test_cmd_verify_and_stats_honor_tier_flag(monkeypatch, capsys):
    """`--tier` is a `common()` flag accepted by every subcommand, but
    cmd_verify/cmd_stats used to silently ignore it -- `tdf verify --tier`
    always verified the UNTIERED document, so a bug reachable only through
    tiering (or its interaction with columnar encoding) could pass
    verification and still ship via `tdf convert --tier`. See the optimizer
    red-team audit's P1 convert/verify parity fix.

    Asserting the return code alone can't tell "flag applied" from "flag
    silently ignored" (both would report 100% recall here) -- so this checks
    the tiered token count is actually smaller than the untiered one, proving
    tier() genuinely ran rather than being a no-op."""
    import argparse
    import json
    import random
    from tdf import cli as climod
    from tdf.ir import Doc, Para

    PROSE = ("The controller manager runs reconciliation loops. Each loop "
              "compares observed state to desired state. It issues changes "
              "until the cluster converges. Operators rely on it. ") * 3
    # Shuffled, non-repeating nav terms -- a single repeated phrase would let
    # the dictionary pass compress the UNTIERED version so well (one §n
    # definition covering all repeats) that it beats tiering's fixed-size
    # 40-word literal gist preview on raw token count alone, which is a
    # compression-ratio artifact of this specific fixture, not a bug (see
    # tier.py's `_gist`/GIST_ITEMS design) -- not what this test is checking.
    nav_words = ["Overview", "Components", "Objects", "Names", "Labels", "Selectors",
                 "Namespaces", "Annotations", "Finalizers", "Owners", "Dependents",
                 "Storage", "Versions", "Controllers", "Volumes", "Secrets",
                 "ConfigMaps", "Ingress", "Services", "Endpoints", "Nodes", "Pods"]
    rng = random.Random(7)
    NAV = " ".join(rng.choice(nav_words) for _ in range(160))

    def fake_load(path, max_pages):
        return Doc(blocks=[Para(PROSE), Para(NAV), Para(PROSE)])

    monkeypatch.setattr(climod, "_load", fake_load)

    a = argparse.Namespace(input="fake.txt", max_pages=None, tier=True,
                            no_legend=False, json=True)
    assert climod.cmd_verify(a) == 0
    verify_res = json.loads(capsys.readouterr().out)
    assert verify_res["distinct_recall"] == 1.0

    s_tiered = argparse.Namespace(input="fake.txt", max_pages=None, tier=True,
                                   no_legend=False, json=True)
    climod.cmd_stats(s_tiered)
    tiered = json.loads(capsys.readouterr().out)["tokens"]["tdf (no legend)"]

    s_plain = argparse.Namespace(input="fake.txt", max_pages=None, tier=False,
                                  no_legend=False, json=True)
    climod.cmd_stats(s_plain)
    untiered = json.loads(capsys.readouterr().out)["tokens"]["tdf (no legend)"]

    assert tiered < untiered, "tier=True produced the same size as tier=False -- flag is a no-op"


# ---------------------------------------------- issue 11: unicode fidelity

def test_fidelity_metric_detects_cjk_content_replacement():
    """Before the fix, an ASCII-only [a-z0-9]+ tokenizer produced an empty
    bag for pure-CJK text, so recall against an empty original bag reported
    100% even when the entire document was replaced with unrelated content."""
    original = Doc(blocks=[Para("東京は日本の首都です。人口は約一四〇〇万人。")])
    replaced = Doc(blocks=[Para("大阪は日本の別の都市です。")])

    assert len(content_bag(original)) > 0, "CJK content must be visible to the tokenizer"
    report = compare(original, replaced)
    assert report["distinct_recall"] < 1.0, "metric failed to notice content was replaced"


def test_fidelity_metric_ascii_unchanged():
    """The Unicode fix must not change tokenization of plain ASCII text."""
    doc = Doc(blocks=[Para("The quick brown fox jumps over 42 lazy dogs.")])
    bag = content_bag(doc)
    assert set(bag) == {"the", "quick", "brown", "fox", "jumps", "over", "42", "lazy", "dogs"}


def test_fidelity_metric_devanagari_combining_marks():
    """Combining vowel marks (category Mn) must stay attached to the letter
    they modify -- "भारत" is one token, not "भ" + "रत" with the matra dropped."""
    doc = Doc(blocks=[Para("भारत")])
    assert "भारत" in content_bag(doc)


def test_fidelity_metric_currency_and_emoji_are_visible():
    doc = Doc(blocks=[Para("₹10,000 ≠ ₹100,000 🚀")])
    bag = content_bag(doc)
    assert "₹" in bag and "≠" in bag and "🚀" in bag


def test_actual_roundtrip_preserves_cjk_exactly():
    """Isolates the fix to the metric: the real serializer/parser already
    preserved CJK text correctly before this fix."""
    text = "東京は日本の首都です。"
    doc = Doc(blocks=[Para(text)])
    out, parsed, original = roundtrip(doc)
    assert parsed.blocks[0].text == text


# ------------------------------------- issue 13/misc: single-column tables

def test_single_column_table_with_space_in_value():
    """A single-column table has no separator character for the parser to
    detect tab-mode from, so a value with a space in it must never be
    silently re-split into multiple columns."""
    doc = Doc(blocks=[Table(["Full Name"], [["Alice Smith"], ["Bob Jones"]])])
    out, parsed, original = roundtrip(doc)

    assert parsed.blocks[0].cols == ["Full Name"]
    assert parsed.blocks[0].rows == [["Alice Smith"], ["Bob Jones"]]


def test_single_column_header_with_space_not_split():
    doc = Doc(blocks=[Table(["!T 5 caption"], [[""], ["value"]])])
    out, parsed, original = roundtrip(doc)

    assert parsed.blocks[0].cols == ["!T 5 caption"], f"column name was split:\n{out}"


# --------------------------------------------------- misc quoting/parsing bugs

def test_embedded_quote_character_without_space_is_escaped():
    """_quote() must trigger on *any* embedded '"', not just a leading one --
    _split's parser toggles quoted-field state on every unescaped '"' it
    sees, so an unquoted value like '0"0' silently loses the quote char."""
    doc = Doc(blocks=[Table(['0"0'], [])])
    out, parsed, original = roundtrip(doc)

    assert parsed.blocks[0].cols == ['0"0'], f"embedded quote corrupted:\n{out}"


def test_literal_quote_wrapped_content_is_not_double_unquoted():
    """A value whose actual content starts and ends with a literal '"'
    character (e.g. a column header that is the two characters '""', or a
    cell holding a quoted title like '"quoted"') must survive round-trip
    intact.

    _split() already fully resolves CSV-style quoting inline while
    tokenizing (space mode) -- or applies none at all, correctly, since tab
    mode never quotes on emit (see _render_rows, which uses _oneline for
    tab-separated cells). parse.py used to call a separate _unquote() AGAIN
    on every token _split() returned, redundantly reprocessing already-
    decoded content: whenever that content itself happened to start and end
    with '"', the second pass stripped it as if it were still raw,
    unresolved wire syntax -- e.g. decoded content '""' (two literal quote
    characters) collapsed to '' (empty string), and '"quoted"' collapsed to
    'quoted', in BOTH tab and space mode, silently discarding real content
    (see the optimizer red-team audit's unit-hoisting investigation, which
    surfaced this via the structural round-trip property test)."""
    doc = Doc(blocks=[Table(cols=['""'], rows=[])])
    out, parsed, original = roundtrip(doc)
    assert parsed.blocks[0].cols == ['""'], f"two-quote header corrupted:\n{out}"

    doc2 = Doc(blocks=[Table(["Full Name"], [['"quoted"'], ["Bob"]])])
    out2, parsed2, _ = roundtrip(doc2)
    assert parsed2.blocks[0].rows == [['"quoted"'], ["Bob"]], f"quoted cell corrupted:\n{out2}"

    # Multi-column with an embedded space forces tab-separated mode, the
    # path that never quotes on emit at all -- the bug hit there too.
    doc3 = Doc(blocks=[Table(["A", "B"], [['"quoted"', "has space here"], ["x", "y"]])])
    out3, parsed3, _ = roundtrip(doc3)
    assert parsed3.blocks[0].rows == [['"quoted"', "has space here"], ["x", "y"]], (
        f"quoted cell corrupted in tab mode:\n{out3}"
    )


def test_leading_space_column_name_preserved():
    """The !C line parser must strip exactly the one separator character the
    emitter inserts, not greedily lstrip() all leading whitespace (which ate
    into a first column name that itself starts with a space)."""
    doc = Doc(blocks=[Table([" leading space", "second"], [])])
    out, parsed, original = roundtrip(doc)

    assert parsed.blocks[0].cols == [" leading space", "second"], f"leading space lost:\n{out}"


def test_tab_in_cell_value_does_not_flip_separator_detection():
    """A value containing a literal tab must not make the parser mistake a
    space-separated table for a tab-separated one (or vice versa)."""
    doc = Doc(blocks=[Table(["A\tB", "C"], [])])
    out, parsed, original = roundtrip(doc)

    # The tab is collapsed to a space by _oneline (same treatment as
    # newlines) precisely because it would otherwise be ambiguous with the
    # real separator; the important invariant is the column count survives.
    assert len(parsed.blocks[0].cols) == 2, f"column count corrupted:\n{out}"


def test_kv_continuation_stops_at_quote_boundary():
    """The !K continuation loop used to lack the quote/code/ordered-list
    boundary checks the !R loop already had, so a Quote block immediately
    following a KV block whose text contained a colon was swallowed as an
    extra pair instead of starting a new Quote block."""
    doc = Doc(blocks=[KV([("key", "value")]), Quote("has: a colon")])
    out, parsed, original = roundtrip(doc)

    assert canonicalize(original) == canonicalize(parsed), out


def test_kv_continuation_stops_at_code_fence_boundary():
    doc = Doc(blocks=[KV([("key", "value")]), Code("x: y", "")])
    out, parsed, original = roundtrip(doc)

    assert canonicalize(original) == canonicalize(parsed), out


def test_kv_continuation_stops_at_ordered_list_boundary():
    doc = Doc(blocks=[KV([("key", "value")]), ListBlock(["item: one"], ordered=True)])
    out, parsed, original = roundtrip(doc)

    assert canonicalize(original) == canonicalize(parsed), out


def test_validator_does_not_misread_sigil_inside_code_fence():
    """validate.py's line scanner used to have no notion of fence
    boundaries, so a Code block containing a line that looked like `!T 5 ...`
    was flagged as a real, malformed table declaration."""
    doc = Doc(blocks=[Code("!T 5 caption", "")])
    working = copy.deepcopy(doc)
    books = encode_columns(working)
    out = render_tdf(working, legend=False, codebooks=books)

    val = validate(out)
    assert val.ok, f"false-positive validation error inside a code fence:\n{out}\n{val.violations}"


# ------------------------------------------- extended audit: tier/elision

def test_elision_gist_with_embedded_newline_does_not_inject():
    """Same injection class as Heading/Quote/ListBlock/Figure (issues 3/4/12)
    -- not reachable via tier()'s own gist construction (it already collapses
    whitespace via str.split()), but a real gap for anything constructing an
    Elision directly."""
    from tdf.ir import Elision

    doc = Doc(blocks=[Elision("x1", "index", 100, "gist line one\n!T 5 fake", 3), Para("after")])
    out, parsed, original = roundtrip(doc)

    assert not any(isinstance(b, Table) for b in parsed.blocks), f"fake table injected:\n{out}"
    assert any(isinstance(b, Para) and b.text == "after" for b in parsed.blocks), (
        f"following paragraph was swallowed:\n{out}"
    )


def test_tier_and_columnar_encoding_compose_correctly():
    """--tier (elision) and columnar encoding run in sequence in cmd_convert
    (tier() first, then encode_columns() on the tiered doc) -- verify that
    combination doesn't corrupt either mechanism.

    Built synthetically (an index-like Para to trigger tier(), a
    low-cardinality table to trigger encode_columns()) rather than reading a
    real sample file: samples_real/ is gitignored and has no generator
    script (unlike samples/, which bench/make_samples.py creates), so a real
    file here works locally but breaks CI, which never has that directory.
    """
    from tdf.tier import tier, restore

    # >= tier.MIN_TOKENS (120) and 0 sentence terminators -- matches the
    # nav-tree/index shape tier() is designed to catch.
    nav_text = " ".join(f"Item{i}" for i in range(200))
    regions = ["Asia Pacific Region", "Europe Middle East Africa", "Americas Region North South"]
    rows = [[f"Person{i}", regions[i % 3], str(100000 + i)] for i in range(40)]
    doc = Doc(blocks=[
        Para("Real prose sentence one. Real prose sentence two."),
        Para(nav_text),
        Table(["Person", "Region", "Salary"], rows),
    ])
    original = copy.deepcopy(doc)
    store = tier(doc)
    assert store, "expected at least one elided region on this document"
    books = encode_columns(doc)
    assert books, "expected the table to trigger columnar encoding"
    out = render_tdf(doc, legend=False, codebooks=books)
    restored = parse_tdf(out)

    restore(restored, store)
    report = compare(original, restored)
    assert report["distinct_recall"] == 1.0, report["missing_sample"]


# ------------------------------------------- extended audit: readers

def test_markdown_table_escaped_pipe_stays_one_cell():
    """_split_row used to split on every '|' including GFM's escaped '\\|',
    then try to unescape too late -- 'a\\|b' (one cell) became two cells,
    'a\\' and 'b', shifting the whole row's column count."""
    from tdf.readers.text_formats import read_markdown

    md = "| Name | Value |\n| --- | --- |\n| a\\|b | c |\n"
    doc = read_markdown("test.md", text=md)
    table = doc.blocks[0]
    assert table.cols == ["Name", "Value"]
    assert table.rows == [["a|b", "c"]]


def test_markdown_table_normal_row_unaffected():
    from tdf.readers.text_formats import read_markdown

    md = "| Name | Value |\n| --- | --- |\n| normal | row |\n"
    doc = read_markdown("test.md", text=md)
    assert doc.blocks[0].rows == [["normal", "row"]]


def test_html_table_blank_first_row_does_not_lose_header():
    """A blank spacer <tr> used to desync the header-detection check (which
    referenced the *unfiltered* first <tr>) from the actual first data row
    after blank rows were filtered out of `grid` -- the real header row got
    treated as data, and synthetic column names ('c1', 'c2', ...) were
    fabricated in its place."""
    from tdf.readers.text_formats import read_html

    html = ("<table><tr><td></td><td></td></tr>"
            "<tr><th>Name</th><th>Age</th></tr>"
            "<tr><td>Alice</td><td>30</td></tr></table>")
    doc = read_html("test.html", text=html)
    table = doc.blocks[0]
    assert table.cols == ["Name", "Age"], f"header lost: {table.cols}"
    assert table.rows == [["Alice", "30"]]


def test_html_table_without_header_unaffected():
    from tdf.readers.text_formats import read_html

    html = "<table><tr><td>A</td><td>B</td></tr><tr><td>1</td><td>2</td></tr></table>"
    doc = read_html("test.html", text=html)
    table = doc.blocks[0]
    assert table.cols == ["c1", "c2"]
    assert table.rows == [["A", "B"], ["1", "2"]]


# ------------------------------------------- extended audit: section refs

def test_literal_section_reference_survives_dictionary_substitution():
    """A literal '§1' in the source text (a real character in legal/academic
    writing -- section references) used to collide with build_dictionary's
    own §N reference syntax: if a repeated phrase happened to be assigned
    reference number 1 too, expand() on parse couldn't tell the genuine '§1'
    apart from the inserted one and silently replaced it with the phrase."""
    doc = Doc(blocks=[
        Heading(1, "!T 5 caption"),
        ListBlock(["!T 5 caption", "!T 5 caption", "§1"], ordered=False),
    ])
    original = copy.deepcopy(doc)
    working = copy.deepcopy(doc)
    out = render_tdf(working)
    restored = parse_tdf(out)

    report = compare(original, restored)
    assert report["distinct_recall"] == 1.0, f"literal section ref corrupted:\n{out}\n{report['missing_sample']}"
    assert restored.blocks[0].items[-1] == "§1"


def test_dictionary_legend_numbers_match_actual_references():
    """The !D legend used to re-number phrases sequentially from the list
    position, independent of the (possibly reserved-number-skipping) numbers
    actually substituted into the text -- a real mismatch between what the
    legend declared and what the body actually referenced, whenever a
    reserved number was skipped."""
    doc = Doc(blocks=[
        Heading(1, "!T 5 caption"),
        ListBlock(["!T 5 caption", "!T 5 caption", "§1"], ordered=False),
    ])
    out = render_tdf(doc)
    # The legend's declared number for "!T 5 caption" must be the same
    # number actually used at every reference site.
    import re
    legend_num = re.search(r"^1 !T 5 caption$", out, re.M)
    # number 1 is reserved (literal '§1' exists), so the phrase must be 2+
    assert legend_num is None, "legend used reserved number 1"
    assert re.search(r"^!D 1\n(\d+) !T 5 caption$", out, re.M), f"no legend entry found:\n{out}"
    n = re.search(r"^!D 1\n(\d+) !T 5 caption$", out, re.M).group(1)
    assert out.count(f"§{n}") == 3, f"legend number {n} doesn't match reference count:\n{out}"


# --------------------------------- optimizer audit: semantic-invariant tests
#
# Unlike the tests above (each reproducing one specific historical bug), these
# prove the optimizer's transformations preserve the FACTS a document states
# -- sign, unit, identifier, and row/column relationships -- through the real
# production pipeline (optimize -> encode_columns -> render_tdf -> parse_tdf),
# not just that the right words appear somewhere (fidelity.compare's bag-of-
# words recall is order- and position-blind and would report 100% even if a
# value moved to the wrong row or a sign flipped on the wrong cell).

def test_negative_parenthesized_numbers_survive_full_pipeline():
    """(500) must decode back as a negative number after the FULL pipeline,
    not just at the normalize_cell unit level -- see the P1 paren fix."""
    rows = [["A", "(500)"], ["B", "-500"], ["C", "500"], ["D", "(500)"]]
    doc = Doc(blocks=[Table(["Name", "Delta"], rows)])
    out, parsed, original = roundtrip(doc, optimized=True)
    table = next(b for b in parsed.blocks if isinstance(b, Table))
    got = {r[0]: r[1] for r in table.rows}
    assert got == {"A": "-500", "B": "-500", "C": "500", "D": "-500"}, out


def test_unmatched_parens_and_dates_are_not_corrupted_into_negatives():
    """A stray, unpaired paren or a date-shaped value must not be
    misread as accounting notation and flipped negative, and a genuinely
    matched pair must still flip -- through the full pipeline."""
    rows = [
        ["Note A", "123)"],
        ["Note B", "(123"],
        ["Edition", "(2024)"],
        ["Range", "2020-2024"],
    ]
    doc = Doc(blocks=[Table(["Label", "Value"], rows)])
    out, parsed, original = roundtrip(doc, optimized=True)
    table = next(b for b in parsed.blocks if isinstance(b, Table))
    got = {r[0]: r[1] for r in table.rows}
    assert got["Note A"] == "123)", out
    assert got["Note B"] == "(123", out
    assert got["Edition"] == "-2024", out
    assert got["Range"] == "2020-2024", out


def test_identifiers_and_emphasis_survive_full_pipeline():
    """Code identifiers must survive byte-exact; genuine multi-word emphasis
    must still strip -- through the full pipeline, not just clean_text()
    called directly. See the P0 underscore/identifier fix."""
    doc = Doc(blocks=[
        Para("Call foo_bar_baz() then check __init__ and api_key_secret."),
        Para("This is _genuine emphasis_ and this is __strong text too__."),
    ])
    out, parsed, original = roundtrip(doc, optimized=True)
    paras = [b.text for b in parsed.blocks if isinstance(b, Para)]
    assert "foo_bar_baz" in paras[0], out
    assert "__init__" in paras[0], out
    assert "api_key_secret" in paras[0], out
    assert "genuine emphasis" in paras[1], out
    assert "strong text too" in paras[1], out
    assert "_genuine emphasis_" not in paras[1], out
    assert "__strong text too__" not in paras[1], out


def test_mixed_currency_and_percent_columns_stay_isolated():
    """Two adjacent unit-bearing columns (currency, percent) must each keep
    their own mark through hoist -> render -> parse -- neither column's
    values may pick up the other's symbol."""
    rows = [[f"P{i}", f"${100 + i}.00", f"{i}%"] for i in range(12)]
    doc = Doc(blocks=[Table(["Person", "Salary", "Growth"], rows)])
    out, parsed, original = roundtrip(doc, optimized=True)
    table = next(b for b in parsed.blocks if isinstance(b, Table))
    by_person = {r[0]: r for r in table.rows}
    for i in range(12):
        r = by_person[f"P{i}"]
        assert r[1] == f"${100 + i}", out
        assert r[2] == f"{i}%", out


def test_table_row_facts_survive_full_pipeline_with_combined_passes():
    """Constant-column hoisting, repeated-cell elision, and columnar
    dictionary coding all fire together on this table (40 rows, a constant
    Currency column, and a low-cardinality Region column). Every row's
    Person/Region/Salary/Currency facts must still be individually correct
    after a full round trip -- looked up by column name, since a dropped
    constant column is legitimately restored at the end of the row (see
    parse_tdf's constant-column handling), not necessarily its original
    position."""
    regions = ["Asia Pacific", "Europe Middle East Africa", "Americas"]
    rows = [[f"Person{i}", regions[i % 3], str(50000 + i * 137), "USD"] for i in range(40)]
    doc = Doc(blocks=[Table(["Person", "Region", "Salary", "Currency"], rows)])
    original_facts = {r[0]: {"Region": r[1], "Salary": r[2], "Currency": r[3]} for r in rows}

    out, parsed, original = roundtrip(doc, optimized=True)
    table = next(b for b in parsed.blocks if isinstance(b, Table))
    assert len(table.rows) == 40, out

    for r in table.rows:
        facts = dict(zip(table.cols, r))
        person = facts["Person"]
        expected = original_facts[person]
        assert facts["Region"] == expected["Region"], f"{person}: {out}"
        assert facts["Salary"] == expected["Salary"], f"{person}: {out}"
        assert facts["Currency"] == expected["Currency"], f"{person}: {out}"


def test_dictionary_phrase_does_not_match_inside_a_fused_token():
    """A Re-Pair-selected phrase must only substitute where it stands as its
    own whitespace-delimited run, not as a substring fused onto a longer
    token elsewhere in the corpus (messy PDF extraction routinely glues a
    trailing digit or footnote marker onto the last word with no space).

    Before the fix, `build_dictionary`/`select` matched and replaced via
    plain substring (`str.replace`/`str.count`), so a phrase ending in
    "...covers" also matched inside the unrelated token "covers2024",
    splicing a "§n" reference directly onto "2024" with no separator. On
    read-back, parse_tdf's own reference regex (`§(\\d+)`) is greedy, so
    "§12024" was read as reference 12024 -- never defined -- and the entire
    fused run, digits included, was silently lost rather than reconstructed
    (see the optimizer red-team audit's Re-Pair phrase-boundary fix)."""
    phrase = "the annual financial report covers"
    paras = [
        Para(f"{phrase} many topics of interest to readers everywhere."),
        Para(f"{phrase} many other things as well, in detail."),
        Para(f"{phrase} the full fiscal year in depth."),
        Para(f"Executives noted that {phrase}2024 was a record year."),
    ]
    doc = Doc(blocks=paras)
    out, parsed, original = roundtrip(doc, optimized=True)

    report = compare(original, parsed)
    assert report["distinct_recall"] == 1.0, f"fused-token phrase corrupted:\n{out}\n{report['missing_sample']}"
    fused = next(b.text for b in parsed.blocks if "2024" in b.text)
    assert f"{phrase}2024" in fused, f"fused occurrence not reconstructed:\n{out}"
    assert "§" not in fused, f"stray unresolved reference leaked into body text:\n{out}"


# ------------------------------- optimizer audit: reserved-syntax collisions

def test_reserved_syntax_shaped_table_cells_survive_full_pipeline():
    """Values that look like TDF's own sigils, repeat markers, section
    references, or column codes must stay literal through the full
    optimizer pipeline when they appear as TABLE CELLS specifically --
    where hoist_units, drop_constant_columns, elide_repeats, and
    encode_columns all interact with the raw cell text, not just prose
    (test_sigil_shaped_text_survives already covers Para-level text via
    fidelity.compare's bag-of-words recall; this checks exact per-cell
    content, including values repeated back-to-back to force elide_repeats'
    '^' marker into play, and low-cardinality repeats to force
    encode_columns' a/b/c-style codes into play alongside them)."""
    reserved_shaped = [
        "^", "^^", "^^^", "§1", "§99", "!T 5 x", "!F a=b", "!C", "!K x",
        "!P 3", "!G chart", "!E x1 index 9 9 g", "!D 1", "!R", "%TDF1",
        "!V col", "a", "b", "aa",  # also shaped like the codebook's own codes
    ]
    # Repeat each value 3x consecutively (forces elide_repeats' '^' marker to
    # actually fire on top of already-'^'-shaped literal content) across
    # enough rows to also clear encode_columns' MIN_ROWS=12 threshold.
    rows = [[str(i), reserved_shaped[i % len(reserved_shaped)]] for i in range(len(reserved_shaped) * 3)]
    doc = Doc(blocks=[Table(["id", "value"], rows)])
    out, parsed, original = roundtrip(doc, optimized=True)

    table = next(b for b in parsed.blocks if isinstance(b, Table))
    got = {r[0]: r[1] for r in table.rows}
    for i in range(len(rows)):
        expected = reserved_shaped[i % len(reserved_shaped)]
        assert got[str(i)] == expected, f"row {i} corrupted (expected {expected!r}):\n{out}"
