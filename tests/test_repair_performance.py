"""Phase 22: performance regression test for tdf/repair.py's Re-Pair.

The original implementation rescanned the ENTIRE token sequence to count
every pair on every one of up to 4000 merge iterations -- O(n * max_merges).
Profiled at 170s of self time in _Repair.run() alone on Pride and Prejudice
(~130k words), driven by ~1.2 billion len() calls. Fixed by maintaining
pair counts incrementally over a linked-list sequence representation
(only positions touched by an actual merge ever get recounted) plus a
cheaper select() ranking that avoids a full-corpus regex scan per
candidate just to establish sort order. End-to-end: 186s -> 16s on the
real Pride and Prejudice document (see the commit that introduced this
test for the full before/after profile).

This test uses a synthetic document at a similar scale/redundancy profile
rather than depending on the real corpus fixture, so it's self-contained.
The time bound is generous (comfortably above the ~16s measured on the
real worst case, far below the old ~186s) to avoid flakiness on a slower
machine while still catching a regression back to O(n * max_merges).

Run: .venv/bin/python -m pytest tests/test_repair_performance.py -q
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tdf.ir import Doc, Para  # noqa: E402
from tdf.optimize import build_dictionary  # noqa: E402


def _novel_like_doc(paragraphs: int = 2000, words_per_para: int = 60) -> Doc:
    """A large document with realistic phrase-level redundancy: a handful
    of common multi-word phrases recur throughout (like "said the" or "it
    was a truth universally" would in real prose), interspersed with
    unique filler words so it isn't trivially compressible to nothing."""
    phrases = [
        "it is a truth universally acknowledged that",
        "she could not help thinking about",
        "in the course of the following conversation",
        "as far as she was able to determine",
        "the whole of the assembled company agreed",
    ]
    blocks = []
    for i in range(paragraphs):
        words = []
        while len(words) < words_per_para:
            words.append(phrases[i % len(phrases)])
            words.append(f"filler{i}_{len(words)}")
        blocks.append(Para(" ".join(words)))
    return Doc(title="Synthetic Novel", blocks=blocks)


def test_build_dictionary_completes_quickly_on_a_large_document():
    doc = _novel_like_doc()
    word_count = sum(len(b.text.split()) for b in doc.blocks)
    assert word_count > 100_000, "fixture should be novel-scale to be a meaningful stress test"

    t0 = time.time()
    dictionary = build_dictionary(doc)
    elapsed = time.time() - t0

    assert dictionary, "expected the repeated phrases to actually be found"
    assert elapsed < 60, (
        f"build_dictionary took {elapsed:.1f}s on a {word_count}-word document -- "
        f"the old O(n * max_merges) implementation took ~186s on a similarly-sized "
        f"real novel, so this is a regression back toward that complexity class"
    )
