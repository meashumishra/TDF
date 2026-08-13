"""Semantic fidelity check.

Compares the *content* of two IRs as a normalized token multiset. This answers
the only question that matters for a compression format aimed at LLMs: did any
meaning-bearing content go missing?
"""

from __future__ import annotations

import re
from collections import Counter

from .ir import Code, Doc, Elision, Figure, Heading, KV, ListBlock, PageMark, Para, Quote, Table
from .optimize import clean_text, normalize_cell

_TOK = re.compile(r"[a-z0-9]+")


def content_bag(doc: Doc) -> Counter:
    bag: Counter = Counter()

    def add(s: str):
        if s:
            bag.update(_TOK.findall(clean_text(str(s)).lower()))

    if doc.title:
        add(doc.title)
    for b in doc.blocks:
        if isinstance(b, (Para, Quote)):
            add(b.text)
        elif isinstance(b, Heading):
            add(b.text)
        elif isinstance(b, ListBlock):
            for it in b.items:
                add(it)
        elif isinstance(b, Figure):
            add(b.desc)
        elif isinstance(b, Code):
            add(b.text)
        elif isinstance(b, KV):
            for k, v in b.pairs:
                add(k); add(v)
        elif isinstance(b, Table):
            add(b.caption)
            for c in b.cols:
                add(c)
            for r in b.rows:
                for v in r:
                    add(normalize_cell(v))
        elif isinstance(b, PageMark):
            pass
        elif isinstance(b, Elision):
            pass
    return bag


def compare(original: Doc, restored: Doc) -> dict:
    """Recall of the original's content in the restored document.

    Boilerplate is deduplicated on purpose, so we compare on *distinct* content
    (set recall) as the headline number and report the multiset delta too.
    """
    a, b = content_bag(original), content_bag(restored)
    sa, sb = set(a), set(b)

    missing = sa - sb
    recall = 1.0 if not sa else len(sa & sb) / len(sa)

    tot_a, tot_b = sum(a.values()), sum(b.values())
    return {
        "distinct_recall": recall,
        "distinct_original": len(sa),
        "distinct_missing": len(missing),
        "missing_sample": sorted(missing)[:15],
        "occurrences_original": tot_a,
        "occurrences_restored": tot_b,
        "occurrence_ratio": (tot_b / tot_a) if tot_a else 1.0,
    }
