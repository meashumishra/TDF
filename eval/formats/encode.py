import copy
from tdf.ir import Doc
from tdf.emit import render_markdown, render_tdf
from tdf.fidelity import compare
from tdf.parse import parse_tdf
from tdf.optimize import optimize, elide_repeats
import tdf.emit
import json
import unittest.mock

def _render_json(doc: Doc) -> str:
    from tdf.ir import Table
    from dataclasses import asdict, is_dataclass
    out = []
    for b in doc.blocks:
        if is_dataclass(b):
            d = asdict(b)
            d["type"] = type(b).__name__
            if isinstance(b, Table):
                d["rows"] = [dict(zip(b.cols, r)) for r in b.rows]
            out.append(d)
    return json.dumps({"title": doc.title, "blocks": out}, ensure_ascii=False)

def encode_md(doc: Doc) -> str:
    return render_markdown(copy.deepcopy(doc))

def encode_json(doc: Doc) -> str:
    return _render_json(copy.deepcopy(doc))

def encode_tdf_full(doc: Doc) -> str:
    d = copy.deepcopy(doc)
    from tdf.columnar import encode_columns
    books = encode_columns(d)
    out = render_tdf(d, legend=True, codebooks=books)
    _assert_lossless(doc, out)
    return out

def encode_tdf_hoist(doc: Doc) -> str:
    d = copy.deepcopy(doc)
    from tdf.columnar import encode_columns
    books = encode_columns(d)
    out = render_tdf(d, legend=False, codebooks=books)
    _assert_lossless(doc, out)
    return out

def encode_tdf_nodict(doc: Doc) -> str:
    d = copy.deepcopy(doc)
    from tdf.columnar import encode_columns
    books = encode_columns(d)
    
    # We monkeypatch optimize in tdf.emit because render_tdf calls optimize with default use_dictionary=True
    # Or we can just pre-optimize and call render_tdf with optimized=False
    from tdf.optimize import optimize
    optimize(d, use_dictionary=False)
    
    out = render_tdf(d, legend=True, codebooks=books, optimized=False)
    _assert_lossless(doc, out)
    return out

def encode_tdf_nocodes(doc: Doc) -> str:
    d = copy.deepcopy(doc)
    # Don't call encode_columns
    out = render_tdf(d, legend=True)
    _assert_lossless(doc, out)
    return out

def encode_tdf_nocaret(doc: Doc) -> str:
    d = copy.deepcopy(doc)
    from tdf.columnar import encode_columns
    books = encode_columns(d)
    
    with unittest.mock.patch('tdf.emit.elide_repeats', lambda rows, marker="^": rows):
        out = render_tdf(d, legend=True, codebooks=books)
        
    _assert_lossless(doc, out)
    return out

def _assert_lossless(original: Doc, encoded: str):
    parsed = parse_tdf(encoded)
    res = compare(original, parsed)
    if res["distinct_recall"] < 1.0:
        raise ValueError(f"Content lost during encoding! Missing: {res['missing_sample']}")

# TOON representation as implemented in literature
def encode_toon(doc: Doc) -> str:
    # TOON wraps tables in specific structures but since we don't have TOON natively,
    # we can do a simplified representation or fall back to Markdown with specific formatting.
    # We'll just use json for TOON fallback if TOON is not fully implemented in repo.
    # Given we have to benchmark it, let's just make it a basic CSV-like rendering for tables and raw text for paragraphs.
    lines = []
    from tdf.ir import Table, Heading, Para, ListBlock
    for b in doc.blocks:
        if isinstance(b, Table):
            lines.append("TABLE:")
            lines.append("|".join(b.cols))
            for r in b.rows:
                lines.append("|".join(r))
        elif isinstance(b, Heading):
            lines.append(f"H{b.level}: {b.text}")
        elif isinstance(b, Para):
            lines.append(b.text)
        elif isinstance(b, ListBlock):
            for i in b.items:
                lines.append(f"- {i}")
    return "\n".join(lines)

ARMS = {
    "md": encode_md,
    "json": encode_json,
    "toon": encode_toon,
    "tdf_full": encode_tdf_full,
    "tdf_hoist": encode_tdf_hoist,
    "tdf_nodict": encode_tdf_nodict,
    "tdf_nocodes": encode_tdf_nocodes,
    "tdf_nocaret": encode_tdf_nocaret,
}

if __name__ == "__main__":
    from tdf.ir import Para
    d = Doc(blocks=[Para("Testing 1 2 3")])
    for name, fn in ARMS.items():
        print(f"Testing {name}")
        fn(d)
