"""Property-based testing with Hypothesis.

Replaces the hand-rolled fuzzer with a systematic state-space exploration.
"""

from __future__ import annotations

import copy
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from tdf.columnar import decode_columns, encode_columns
from tdf.emit import render_tdf
from tdf.fidelity import compare
from tdf.ir import Doc, Heading, KV, ListBlock, Para, Quote, Table
from tdf.parse import parse_tdf

# Hostile strings from the old fuzzer, plus hypothesis's own text generation
HOSTILE = [
    "!T 5 caption", "!C a b", "!D", "!R", "!K", "!E x1 index 9 9 g", "!V col",
    "!F a=b", "!P 3", "!G chart", "!Kubernetes is great", "!Try it now",
    "!!T already escaped", "# not a heading", "## also not", "- not a list",
    "> not a quote", "```", "~~~", "1 numbered-looking", "^", "^^", "§1", "§99",
    'quoted "value" here', "comma,separated,fields", "tab\tseparated",
    "pipe|separated|fields", "trailing space ", " leading space",
    "", " ", "\t", "multi\nline\ntext", "café naïve 日本語 🚀", "\u00a0nbsp",
    "-(1,234.00)", "0", "-", "n/a", "NULL", "%TDF1", "a" * 300,
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

block_strategy = st.one_of(
    heading_strategy(),
    para_strategy(),
    listblock_strategy(),
    table_strategy(),
    kv_strategy(),
    quote_strategy()
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
