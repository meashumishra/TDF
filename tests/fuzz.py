"""Randomised round-trip testing for the TDF pipeline.

Hand-picked edge cases only find the bugs you already suspect. This generates
adversarial documents from a pool of strings chosen to attack the format's
assumptions -- sigil-shaped text, separator characters, quotes, back-reference
markers, unicode, embedded newlines, empty cells -- and asserts that content
survives emit -> parse.

It found real bugs on first run; see README section 13.

Run standalone for a longer campaign:

    .venv/bin/python -m tests.fuzz 2000
"""

from __future__ import annotations

import random
import sys

from tdf.columnar import decode_columns, encode_columns
from tdf.emit import render_markdown, render_tdf
from tdf.fidelity import compare
from tdf.ir import Doc, Heading, KV, ListBlock, Para, Quote, Table
from tdf.parse import parse_tdf

# Strings picked to break specific assumptions rather than to look realistic.
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

WORDS = "alpha beta gamma delta epsilon zeta eta theta".split()


def _text(rng: random.Random) -> str:
    if rng.random() < 0.35:
        return rng.choice(HOSTILE)
    return " ".join(rng.choice(WORDS) for _ in range(rng.randint(1, 12)))


def _table(rng: random.Random) -> Table:
    ncols = rng.randint(1, 4)
    nrows = rng.randint(1, 30)
    cols = [_text(rng) for _ in range(ncols)]
    # Ragged rows on purpose: real filings have them and they used to truncate.
    rows = [
        [_text(rng) for _ in range(rng.randint(1, ncols))]
        for _ in range(nrows)
    ]
    return Table(cols=cols, rows=rows, caption=_text(rng) if rng.random() < 0.3 else "")


def random_doc(rng: random.Random) -> Doc:
    blocks = []
    for _ in range(rng.randint(0, 12)):
        kind = rng.random()
        if kind < 0.30:
            blocks.append(Para(_text(rng)))
        elif kind < 0.45:
            blocks.append(Heading(rng.randint(1, 6), _text(rng)))
        elif kind < 0.62:
            blocks.append(ListBlock(items=[_text(rng) for _ in range(rng.randint(1, 8))]))
        elif kind < 0.85:
            blocks.append(_table(rng))
        elif kind < 0.93:
            blocks.append(Quote(_text(rng)))
        else:
            blocks.append(KV(pairs=[(_text(rng), _text(rng)) for _ in range(rng.randint(1, 4))]))
    return Doc(title=_text(rng) if rng.random() < 0.5 else "", blocks=blocks)


def check(doc: Doc) -> tuple[bool, dict]:
    """Emit and re-parse; content must survive."""
    import copy

    original = copy.deepcopy(doc)
    working = copy.deepcopy(doc)
    books = encode_columns(working)
    out = render_tdf(working, codebooks=books)
    decode_columns(books)
    report = compare(original, parse_tdf(out))
    return report["distinct_recall"] == 1.0, report


def campaign(n: int, seed: int = 0) -> list[tuple[int, dict, Doc]]:
    """Run n random documents; return the failures."""
    failures = []
    for i in range(n):
        rng = random.Random(seed + i)
        doc = random_doc(rng)
        import copy

        ok, report = check(copy.deepcopy(doc))
        if not ok:
            failures.append((seed + i, report, doc))
    return failures


if __name__ == "__main__":  # pragma: no cover
    count = int(sys.argv[1]) if len(sys.argv) > 1 else 500
    bad = campaign(count)
    print(f"{count - len(bad)}/{count} documents round-tripped")
    for seed, report, _ in bad[:10]:
        print(f"  seed={seed} recall={report['distinct_recall']:.1%} "
              f"missing={report['missing_sample'][:4]}")
    sys.exit(1 if bad else 0)
