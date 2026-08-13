"""Density tiering: decide which regions earn their tokens.

Every converter in the survey optimises *fidelity to the page*. None optimises
*information per token*. That is why the Kubernetes page compresses by only 2%:
the format is already efficient, but a quarter of the file is a site navigation
tree that no question will ever be asked about, faithfully preserved at full
price.

The discriminator is **sentence density**, measured on real documents:

    navigation / index blobs   0.00 sentence terminators per 100 tokens
    Kubernetes prose           3.83
    Transformer paper prose    4.29
    HR handbook prose          1.92

A long span containing no sentence terminators is not prose. It is an index, and
an index should be encoded as one -- or, above a size threshold, declared and
elided rather than pasted.

Nothing here deletes silently: every elision becomes an ``Elision`` block
carrying its kind, exact token cost, item count, a gist, and an id that
``tdf expand-elided`` resolves back to the full text.
"""

from __future__ import annotations

import re

from .ir import Doc, Elision, ListBlock, Para
from .tokens import count

SENTENCE = re.compile(r"[.!?](?:\s|$)")

MIN_TOKENS = 120        # below this, eliding cannot pay for its own marker
MAX_DENSITY = 0.6       # sentence terminators per 100 tokens
GIST_ITEMS = 8          # leading entries kept so the model can judge relevance


def sentence_density(text: str) -> float:
    """Sentence terminators per 100 tokens."""
    tok = count(text)
    if not tok:
        return 0.0
    return len(SENTENCE.findall(text)) * 100.0 / tok


def is_index_like(text: str) -> bool:
    """True for long spans with no sentence structure (nav trees, TOCs, indexes)."""
    return count(text) >= MIN_TOKENS and sentence_density(text) <= MAX_DENSITY


def _gist(text: str, sep: str) -> tuple[str, int]:
    parts = [p.strip() for p in text.split(sep) if p.strip()] if sep else [text]
    head = parts[:GIST_ITEMS]
    return ", ".join(head), len(parts)


def tier(doc: Doc, enabled: bool = True) -> dict[str, str]:
    """Replace index-like regions with Elision markers.

    Returns {eid: original_text} so the caller can serve expansions.
    """
    if not enabled:
        return {}

    store: dict[str, str] = {}
    out: list = []
    n = 0

    for block in doc.blocks:
        if isinstance(block, Para) and is_index_like(block.text):
            n += 1
            eid = f"x{n}"
            store[eid] = block.text
            gist, items = _gist(block.text, " ")
            out.append(Elision(eid, "index", count(block.text),
                               " ".join(block.text.split()[:40]), items))
            continue

        if isinstance(block, ListBlock):
            keep: list[str] = []
            for item in block.items:
                if is_index_like(item):
                    n += 1
                    eid = f"x{n}"
                    store[eid] = item
                    if keep:
                        out.append(ListBlock(keep, block.ordered))
                        keep = []
                    out.append(Elision(eid, "index", count(item),
                                       " ".join(item.split()[:40]), len(item.split())))
                else:
                    keep.append(item)
            if keep:
                out.append(ListBlock(keep, block.ordered))
            continue

        out.append(block)

    doc.blocks = out
    return store


def restore(doc: Doc, store: dict[str, str], only: str | None = None) -> None:
    """Put elided regions back, either all of them or one by id."""
    out: list = []
    for block in doc.blocks:
        if isinstance(block, Elision) and (only is None or block.eid == only):
            text = store.get(block.eid)
            if text is not None:
                out.append(Para(text))
                continue
        out.append(block)
    doc.blocks = out
