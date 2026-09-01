"""Property-based testing with Hypothesis.

Replaces the hand-rolled fuzzer with a systematic state-space exploration.
"""

from __future__ import annotations

import copy
import pytest
from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st

from tdf.columnar import decode_columns, encode_columns
from tdf.emit import render_tdf
from tdf.fidelity import canonicalize, compare
from tdf.ir import Code, Doc, Elision, Heading, KV, ListBlock, PageMark, Para, Quote, Table
from tdf.optimize import optimize
from tdf.parse import parse_tdf

# Hostile strings from the old fuzzer, plus hypothesis's own text generation
HOSTILE = [
    "!T 5 caption", "!C a b", "!D", "!R", "!K", "!E x1 index 9 9 g", "!V col",
    "!F a=b", "!P 3", "!G chart", "!Kubernetes is great", "!Try it now",
    "!!T already escaped", "# not a heading", "## also not", "- not a list",
    "> not a quote", "```", "~~~", "1 numbered-looking", "^", "^^", "^^^", "§1", "§99",
    'quoted "value" here', "comma,separated,fields", "tab\tseparated",
    "pipe|separated|fields", "trailing space ", " leading space",
    "", " ", "\t", "multi\nline\ntext", "café naïve 日本語 🚀", " nbsp",
    "-(1,234.00)", "0", "-", "n/a", "NULL", "%TDF1", "a" * 300,
    # Multi-line strings whose *second* physical line looks structural -- the
    # class of bug that split ListBlock/Quote/Heading and let an injected
    # sigil open a fake block (issues 3/4/12).
    "line one\n!T 5 fake", "line one\n!K fake", "line one\n!P 3",
    "line one\n```", "line one\n# fake heading", "line one\n- fake item",
    "line one\n> fake quote", "line one\n%TDF1", "^\nsecond line",
]

# Generate text that is either hostile edge cases or arbitrary characters
# We exclude null bytes and surrogates as they often break text processing in ways not relevant to TDF's goals.
text_strategy = st.one_of(
    st.sampled_from(HOSTILE),
    st.text(alphabet=st.characters(blacklist_categories=('Cs', 'Cc')), min_size=0, max_size=100)
)

@st.composite
def heading_strategy(draw):
    level = draw(st.integers(min_value=1, max_value=6))
    text = draw(text_strategy)
    return Heading(level, text)

@st.composite
def para_strategy(draw):
    return Para(draw(text_strategy))

@st.composite
def listblock_strategy(draw):
    items = draw(st.lists(text_strategy, min_size=1, max_size=10))
    ordered = draw(st.booleans())
    return ListBlock(items, ordered)

@st.composite
def table_strategy(draw):
    ncols = draw(st.integers(min_value=0, max_value=5))
    nrows = draw(st.integers(min_value=0, max_value=10))
    cols = draw(st.lists(text_strategy, min_size=ncols, max_size=ncols))
    # Ragged rows on purpose, like in the manual fuzzer
    rows = draw(st.lists(
        st.lists(text_strategy, min_size=0, max_size=ncols),
        min_size=nrows, max_size=nrows
    ))
    caption = draw(text_strategy) if draw(st.booleans()) else ""
    return Table(cols, rows, caption)

@st.composite
def kv_strategy(draw):
    pairs = draw(st.lists(
        st.tuples(text_strategy, text_strategy),
        min_size=1, max_size=5
    ))
    caption = draw(text_strategy) if draw(st.booleans()) else ""
    return KV(pairs, caption)

@st.composite
def quote_strategy(draw):
    return Quote(draw(text_strategy))

# Ingredients that specifically stress the fence-length fix: backtick runs of
# varying length (including longer than the emitter's default 3), sigils and
# %TDF sitting on their own line inside the "code", blank lines, indentation,
# and snippets shaped like the languages the task calls out.
CODE_INGREDIENTS = [
    "```", "````", "`````", "``", "`",
    "!T 5 caption", "!K", "!P 3", "%TDF1",
    "", "    indented line", "\tindented with tab",
    "print(\"hello\")", '{"key": "value", "n": 1}',
    "# Markdown heading\n- a list item\n\n```nested\ncode\n```",
    "SELECT * FROM t WHERE x = '^' AND y != \"z\";",
    "café naïve 日本語 🚀 §1",
]


@st.composite
def code_strategy(draw):
    lines = draw(st.lists(st.sampled_from(CODE_INGREDIENTS), min_size=1, max_size=6))
    lang = draw(st.sampled_from(["", "python", "json", "markdown", "sql", "text"]))
    return Code("\n".join(lines), lang)


@st.composite
def elision_strategy(draw):
    eid = draw(st.sampled_from(["x1", "x2", "x99"]))
    kind = draw(st.sampled_from(["index", "nav", "table"]))
    tokens = draw(st.integers(min_value=0, max_value=100000))
    items = draw(st.integers(min_value=0, max_value=1000))
    gist = draw(text_strategy)
    return Elision(eid, kind, tokens, gist, items)


@st.composite
def pagemark_strategy(draw):
    return PageMark(draw(st.integers(min_value=0, max_value=100000)))


block_strategy = st.one_of(
    heading_strategy(),
    para_strategy(),
    listblock_strategy(),
    table_strategy(),
    kv_strategy(),
    quote_strategy(),
    code_strategy(),
    elision_strategy(),
    pagemark_strategy(),
)

@st.composite
def doc_strategy(draw):
    title = draw(text_strategy) if draw(st.booleans()) else ""
    blocks = draw(st.lists(block_strategy, min_size=0, max_size=10))
    return Doc(title=title, blocks=blocks)

@settings(max_examples=1000, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(doc_strategy())
def test_doc_roundtrip(doc: Doc):
    """Property: Any Document IR emitted to TDF and parsed back has 100% distinct_recall."""
    original = copy.deepcopy(doc)
    working = copy.deepcopy(doc)

    # Try columnar compression as well
    books = encode_columns(working)
    out = render_tdf(working, codebooks=books)

    # Validation step to ensure the string follows the grammar constraints
    from tdf.validate import validate
    val_res = validate(out)
    assert val_res.ok, f"Generated invalid TDF:\n{out}\nViolations: {val_res.violations}"

    # Fidelity test
    parsed = parse_tdf(out)
    report = compare(original, parsed)

    assert report["distinct_recall"] == 1.0, f"Missing: {report['missing_sample']}"


@settings(max_examples=1000, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(doc_strategy())
def test_doc_structural_roundtrip(doc: Doc):
    """Property: block type, order, and every positional relationship survive
    a round-trip exactly -- not just distinct-token recall (see fidelity.
    canonicalize's docstring for exactly what is and isn't normalized here).

    This is the check that catches a ListBlock item being split into a
    ListBlock plus a stray Para, a Quote being truncated to its first line, a
    Code block being truncated by an embedded fence, or a table cell being
    silently misattributed to the wrong row -- all cases where every word is
    still present somewhere in the document, so distinct_recall alone reports
    100% while the structure is actually wrong.

    Two genuinely degenerate cases are excluded, both real ambiguities of a
    line-oriented format rather than bugs:
    - An empty Para/Quote/Heading (text == "" after normalization): a blank
      line is a structural separator, not content, so it is unrepresentable
      by construction -- optimize() already prunes an empty Para outright
      for the same reason (see optimize.py's block-filtering step). An empty
      Quote loses its distinguishing "> " marker the same way once trailing
      whitespace is stripped (">" alone matches nothing structural). A
      ListBlock item that is empty after normalization has the identical
      problem: "- " strips to "-", which matches nothing structural either.
    - A zero-column table: the header line's splitter (_split) always
      returns [''] for an empty string, never [], so "0 columns" and "1
      column named ''" are indistinguishable on the wire. A table with
      neither columns nor rows carries no information either way.
    """
    assume(not any(
        isinstance(b, (Para, Quote, Heading)) and not b.text.strip()
        for b in doc.blocks
    ))
    assume(not any(
        isinstance(b, ListBlock) and any(not i.strip() for i in b.items)
        for b in doc.blocks
    ))
    assume(not any(
        isinstance(b, Table) and not b.cols
        for b in doc.blocks
    ))
    # doc.title now has its own "!H" sigil, distinct from "#" Heading lines
    # (see the independent audit's BUG-5 fix), so the old whitespace-only-
    # title ambiguity this used to guard against ("# " stripping to "#",
    # one char short of the heading regex, falling through to a spurious
    # Para) no longer applies -- title.strip() empty round-trips cleanly to
    # "" with zero spurious blocks, same as the general single-line-field
    # whitespace normalization every other field already gets.
    # Two adjacent ListBlocks have no boundary marker between them, even when
    # they differ in `ordered`: parse_tdf's accumulator only flips the
    # ordered flag when a numbered marker is the *first* item in the current
    # buffer, so "- a" immediately followed by "1 b" just appends "b" to the
    # still-unordered list already in progress rather than starting a new
    # one. Fundamental limitation of the line-oriented list syntax, not a
    # bug, and not a shape real document readers produce (they already merge
    # contiguous items into one block during parsing).
    assume(not any(
        isinstance(a, ListBlock) and isinstance(b, ListBlock)
        for a, b in zip(doc.blocks, doc.blocks[1:])
    ))
    # A KV block's continuation loop stops at a sigil/heading/list/quote/code
    # boundary, but a following Para has no prefix at all to distinguish it
    # from a "key: value" continuation line -- if its text contains a colon,
    # it gets read as one more pair. Same category of inherent ambiguity as
    # the adjacent-ListBlock case above, not a fixable bug (fixed the
    # analogous quote/code/ordered-list gaps that *were* fixable already).
    assume(not any(
        isinstance(a, KV) and isinstance(b, Para) and ":" in b.text
        for a, b in zip(doc.blocks, doc.blocks[1:])
    ))
    # KV keys containing colons or backslashes USED to be excluded here:
    # parse_tdf split "key: value" on the *first* colon, so a key like
    # "Time: start" leaked its own colon into the value. Keys are now escaped
    # on emit (emit._escape_kv_key) and split on the first unescaped colon
    # (parse._split_kv), so they are deliberately generated and asserted.
    original = copy.deepcopy(doc)
    working = copy.deepcopy(doc)

    books = encode_columns(working)
    # optimized=False: isolate serialize/parse correctness from optimize()'s
    # own separately-tested content transforms (text hygiene, boilerplate
    # dedup, phrase-dictionary substitution) -- see canonicalize's docstring.
    out = render_tdf(working, optimized=False, codebooks=books)

    from tdf.validate import validate
    val_res = validate(out)
    assert val_res.ok, f"Generated invalid TDF:\n{out}\nViolations: {val_res.violations}"

    parsed = parse_tdf(out)
    assert canonicalize(original) == canonicalize(parsed), (
        f"Structural mismatch.\nTDF:\n{out}\n"
        f"original: {canonicalize(original)}\nparsed:   {canonicalize(parsed)}"
    )


@settings(max_examples=1000, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(doc_strategy())
def test_optimizer_structural_roundtrip(doc: Doc):
    """Property: the real optimize() pass (text hygiene, phrase-dictionary
    substitution -- boilerplate dedup is opt-in and off by default, see
    optimize()'s docstring) does not corrupt block type, order, or
    positional relationships through a full emit/parse cycle.

    test_doc_structural_roundtrip above deliberately runs with
    optimized=False to isolate serialize/parse correctness from optimize()'s
    own content transforms. This test is the P1 optimizer-level counterpart
    the audit calls for: it exercises optimize() itself (which
    render_tdf(optimized=True) -- the actual default cmd_convert uses --
    applies internally) and checks the result still round-trips
    structurally, not just that distinct words survive (see fidelity.compare,
    which is order-blind and would report 100% even if optimize() silently
    reordered or misattributed content).

    `expected` runs optimize() directly on an independent copy of the same
    input, standing in for ground truth: optimize() itself prunes blocks that
    normalize to nothing (e.g. a Para that is pure zero-width-space content
    becomes "" after clean_text and is dropped -- see optimize()'s own
    empty-block filter), so the degenerate-case exclusions below are applied
    to `expected` (post-optimize) rather than to `doc` (pre-optimize): they
    are the same wire-format ambiguities test_doc_structural_roundtrip
    documents, just evaluated after optimize() has already resolved the
    "does this block survive at all" question.

    Columnar coding is out of scope here on purpose: MIN_ROWS=12 in
    columnar.py and doc_strategy's 10-row table cap mean encode_columns
    never actually fires for these generated fixtures, so this test does not
    exercise (and would give a false failure on) the separately-documented
    pass-ordering finding where a coded column's legend keeps its raw,
    pre-normalize_cell formatting -- see the audit report.
    """
    # use_dictionary=False: build_dictionary()'s phrase -> "§n" substitution
    # is fully reversible -- parse_tdf expands "§n" back to the literal
    # phrase on read (like the four passes canonicalize()'s docstring already
    # calls out: codebook/columnar encoding, "^" elision, constant-column and
    # unit hoisting) -- so a real round trip's final text matches what
    # optimize() would have produced WITHOUT the dictionary pass, not the
    # substituted reference text optimize() leaves in place internally. Disabling
    # it here keeps `expected` representing optimize()'s irreversible
    # transforms only (text hygiene, empty-block pruning -- boilerplate
    # dedup is opt-in and off by default); the real pipeline below still
    # runs the dictionary pass
    # (default True), exercising it precisely because it's expected to wash
    # out by the time parse_tdf returns.
    expected = copy.deepcopy(doc)
    arts = optimize(expected, use_dictionary=False)

    assume(not any(
        isinstance(b, (Para, Quote, Heading)) and not b.text.strip()
        for b in expected.blocks
    ))
    assume(not any(
        isinstance(b, ListBlock) and any(not i.strip() for i in b.items)
        for b in expected.blocks
    ))
    assume(not any(
        isinstance(b, Table) and not b.cols
        for b in expected.blocks
    ))
    assume(not expected.title or expected.title.strip())
    assume(not any(
        isinstance(x, ListBlock) and isinstance(y, ListBlock)
        for x, y in zip(expected.blocks, expected.blocks[1:])
    ))
    assume(not any(
        isinstance(x, KV) and isinstance(y, Para) and ":" in y.text
        for x, y in zip(expected.blocks, expected.blocks[1:])
    ))
    # KV keys with colons/backslashes are no longer excluded here either --
    # see the note on _escape_kv_key/_split_kv in the round-trip test above;
    # this optimize()-on path asserts them under the full pipeline too.
    # strip_boilerplate() no longer runs here at all: optimize()'s
    # use_boilerplate defaults to False (see its docstring and the
    # independent audit's BUG-4 -- the heuristic fires on ordinary repeated
    # prose, not just page furniture, so it must be opt-in). `arts` is kept
    # for its dictionary-related fields; boilerplate is asserted empty as a
    # tripwire in case that default ever changes silently.
    assert arts["boilerplate"] == []

    working = copy.deepcopy(doc)
    books = encode_columns(working)
    out = render_tdf(working, codebooks=books)

    from tdf.validate import validate
    val_res = validate(out)
    assert val_res.ok, f"Generated invalid TDF:\n{out}\nViolations: {val_res.violations}"

    parsed = parse_tdf(out)
    assert canonicalize(expected) == canonicalize(parsed), (
        f"Structural mismatch after optimize().\nTDF:\n{out}\n"
        f"expected: {canonicalize(expected)}\nparsed:   {canonicalize(parsed)}"
    )


def test_kv_key_of_bare_u2028_with_colon_in_value():
    """Regression for a bug surfaced by test_doc_structural_roundtrip's
    Hypothesis search (unrelated to Phase 19's grouping work -- reproduced
    identically on master before it). parse_tdf reads lines via
    str.splitlines(), which treats U+2028 (LINE SEPARATOR) as a line
    boundary like \\n -- but _oneline's newline-collapsing regex only
    handled \\r\\n\\t, so a KV key of a bare U+2028 fragmented into an
    extra physical line on parse, turning one KV pair into an empty-key KV
    plus a stray Para. Fixed by extending emit._NEWLINE to the full set of
    line-boundary characters str.splitlines() recognizes (\\v, \\f,
    \\x1c-\\x1e, \\x85, U+2028, U+2029)."""
    doc = Doc(blocks=[KV(pairs=[(" ", "!T 5 caption")], caption="")])
    working = copy.deepcopy(doc)
    books = encode_columns(working)
    out = render_tdf(working, optimized=False, codebooks=books)
    parsed = parse_tdf(out)
    assert canonicalize(doc) == canonicalize(parsed)
