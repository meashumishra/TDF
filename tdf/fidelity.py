"""Semantic fidelity check.

Compares the *content* of two IRs as a normalized token multiset. This answers
the only question that matters for a compression format aimed at LLMs: did any
meaning-bearing content go missing?
"""

from __future__ import annotations

import unicodedata
from collections import Counter

from .emit import _oneline
from .ir import Code, Doc, Elision, Figure, Heading, KV, ListBlock, PageMark, Para, Quote, Table
from .optimize import clean_text, normalize_cell


def _tokenize(s: str) -> list[str]:
    """Extract meaning-bearing tokens from text of any script.

    A plain ``[a-z0-9]+`` regex is ASCII-only: a document that is entirely
    Chinese, Japanese, Devanagari, Cyrillic, Greek, or Arabic produces an
    *empty* bag, and recall against an empty original bag reports 100% by
    definition (see ``compare``) -- so a document that has been completely
    replaced with unrelated text in one of those scripts would still show
    perfect "recall". Unicode letters and digits (category L*/N*, any script)
    merge into words the same way ASCII ones do. Standalone symbols --
    currency marks, math operators, emoji (category S*) -- carry meaning on
    their own (``$10,000`` vs ``₹10,000`` is a different fact) and become
    individual tokens. Punctuation and whitespace remain excluded, same as
    the ASCII-only version, so plain-prose recall numbers are unchanged.
    """
    tokens: list[str] = []
    buf: list[str] = []
    for ch in s:
        cat = unicodedata.category(ch)
        # Category M (combining marks: Devanagari matras, Arabic diacritics,
        # etc.) attach to the preceding letter and must not split a word --
        # "भारत" is one token, not "भ" + "रत" with the matra silently dropped.
        if cat[0] in ("L", "N", "M"):
            buf.append(ch)
            continue
        if buf:
            tokens.append("".join(buf))
            buf = []
        if cat[0] == "S":
            tokens.append(ch)
    if buf:
        tokens.append("".join(buf))
    return tokens


def content_bag(doc: Doc) -> Counter:
    bag: Counter = Counter()

    def add(s: str):
        if s:
            bag.update(_tokenize(clean_text(str(s)).lower()))

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


def canonicalize(doc: Doc) -> tuple:
    """Structural fingerprint: block type, order, and every positional
    relationship, exactly -- list item order, table row/column alignment,
    KV key-value pairing, quote/code boundaries. This is deliberately
    different from ``content_bag``/``compare``, which is order-blind and
    reports 100% even when rows are swapped or a list item is dropped into a
    separate paragraph.

    Meant to be compared as ``canonicalize(original) == canonicalize(parse_tdf(
    render_tdf(original, optimized=False)))``. With ``optimized=False`` none
    of ``optimize()``'s intentional content transforms run (text hygiene,
    boilerplate dedup, phrase-dictionary substitution), so this checks pure
    serialize/parse correctness in isolation. Codebook/columnar encoding,
    repeated-cell ``^`` elision, constant-column hoisting, and unit hoisting
    are NOT optimize() passes -- they run unconditionally in ``_tdf_table``
    -- but ``parse_tdf`` fully reverses all four before returning, so no
    special-casing for them is needed here either; by the time a ``Doc``
    exists, those encodings have already been undone.

    Two transforms are unconditional regardless of ``optimized``:

    1. Heading, Quote, ListBlock items, Figure text, and the title are each
       one physical TDF line, so an embedded newline is always collapsed to
       a space on emit (the same ``_oneline`` treatment Para/KV/table cells
       already got, extended here to close the structural-splitting and
       sigil-injection bugs those block types otherwise allowed).
    2. Every line the parser reads goes through ``line.strip()`` before any
       further handling, so leading/trailing whitespace on any single-line
       text field (title, heading, quote, list item, figure, para) never
       survives a round-trip. This is whitespace padding, never content, so
       it is normalized here rather than flagged as a structural loss.

    Both are applied to both sides below so neither registers as a false
    structural mismatch.

    A third unconditional rule: a level-1 heading as the very first block of
    a titleless doc is read back as ``doc.title``, not a Heading block (see
    parse_tdf) -- title promotion, not data loss, so it is replicated here
    rather than treated as one.
    """
    def norm(t: str) -> str:
        return _oneline(t).strip()

    title = doc.title
    blocks = doc.blocks
    if not title and blocks and isinstance(blocks[0], Heading) and blocks[0].level == 1:
        title = blocks[0].text
        blocks = blocks[1:]

    out = []
    for b in blocks:
        if isinstance(b, Heading):
            out.append(("Heading", b.level, norm(b.text)))
        elif isinstance(b, Para):
            out.append(("Para", norm(b.text)))
        elif isinstance(b, Quote):
            out.append(("Quote", norm(b.text)))
        elif isinstance(b, ListBlock):
            out.append(("ListBlock", b.ordered, tuple(norm(i) for i in b.items)))
        elif isinstance(b, Table):
            # Caption is explicitly .strip()'d by parse_tdf's own regex
            # (unlike cols/cell values, which are only ever _oneline'd), so
            # it needs norm() here, not just _oneline().
            out.append(("Table", tuple(_oneline(c) for c in b.cols),
                        tuple(tuple(_oneline(v) for v in r) for r in b.rows),
                        norm(b.caption)))
        elif isinstance(b, KV):
            out.append(("KV", tuple((norm(k), norm(v)) for k, v in b.pairs), norm(b.caption)))
        elif isinstance(b, Figure):
            out.append(("Figure", norm(b.desc)))
        elif isinstance(b, Code):
            out.append(("Code", b.text, b.lang))
        elif isinstance(b, PageMark):
            out.append(("PageMark", b.number))
        elif isinstance(b, Elision):
            out.append(("Elision", b.eid, b.kind))
    return (norm(title), tuple(out))


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
