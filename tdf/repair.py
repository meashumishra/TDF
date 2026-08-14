"""Token-cost-weighted Re-Pair for phrase-dictionary induction.

The original dictionary was greedy seed-and-extend: index one seed length, keep
seeds that repeat, extend rightwards. A literature survey put a name to why that
is weak -- it is a poor approximation of **Re-Pair** (Larsson & Moffat, DCC
1999), which builds long phrases bottom-up by recursively replacing the most
frequent *bigram* instead of extending a fixed seed in one direction. Greedy
extension cannot arbitrate overlapping candidates ("A B C D" vs "B C D E");
Re-Pair resolves that structurally, because both phrases are composed from the
same merged pairs.

Two deliberate departures from textbook Re-Pair, both forced by the target:

1. **The priority is token saving, not frequency.** Classic Re-Pair merges the
   most frequent bigram, minimising symbols. We are minimising BPE tokens under
   an unknown tokenizer, which is a different and non-additive cost -- a
   3-occurrence phrase worth 14 tokens each beats a 40-occurrence pair worth 1.
   So the queue is ordered by `occurrences * tokens_saved`.

2. **Rules are flattened before emission.** Re-Pair naturally produces a
   hierarchy (`R7 -> R3 R5`). A decompressor resolves that in linear time, but a
   language model reading `§7 = §3 §5` cannot, so every rule is expanded to its
   full word sequence before it is offered. The hierarchy is used only as the
   search strategy, never as the output encoding.

Admission is the same MDL/token-payback test the greedy version used, which the
survey identified as a per-entry Krimp-style code-table criterion (Vreeken et
al., DMKD 2011) expressed in tokens rather than bits:

    saving = occurrences * cost(phrase) - occurrences * cost(ref)
             - cost(phrase) - cost(definition line)

Word boundaries are never crossed: the alphabet is words, not characters, so
generated phrases stay readable ASCII, preserving the property that a reader can
resolve `§n` by eye.
"""

from __future__ import annotations

import re
from collections import defaultdict

from .tokens import count

# Merging stops here; long phrases are built by composition, not by this bound.
MAX_PHRASE_WORDS = 40
REF_TOKENS = 2  # what one "§n" reference costs

_pattern_cache: dict[str, "re.Pattern[str]"] = {}


def _word_bounded(phrase: str) -> "re.Pattern[str]":
    """Match `phrase` only where it stands as its own run of whitespace-
    delimited tokens (see optimize.py's `_WORD = \\S+`), not as a substring
    fused onto a longer token.

    A phrase built from word tokens can still occur as a literal SUBSTRING
    inside an unrelated, longer token elsewhere in the corpus -- e.g. a
    phrase ending in "...covers" is also a substring of "covers2024" if the
    source text has that run with no space (common in messy PDF extraction).
    A naive `str.replace` fires there too, splicing a "§n" reference
    directly onto "2024" with no separator. That is not just a stray
    artifact: parse_tdf's own reference regex (`§(\\d+)`) is greedy, so
    "§12024" reads back as reference number 12024 -- which was never
    defined -- and the entire fused run (including the digits that were
    genuine original content) is lost rather than reconstructed.

    Anchoring on "not preceded/followed by a non-whitespace character"
    enforces the same boundary the phrase was tokenized on, without
    depending on `\\b`'s `\\w`-based definition, which would wrongly refuse
    a phrase that starts or ends in punctuation (word tokens here are
    `\\S+`, not `[\\w]+` -- e.g. `"$100"` or `"widgets,"` are valid tokens).
    """
    pat = _pattern_cache.get(phrase)
    if pat is None:
        pat = _pattern_cache[phrase] = re.compile(r"(?<!\S)" + re.escape(phrase) + r"(?!\S)")
    return pat


def word_bounded_count(text: str, phrase: str) -> int:
    return len(_word_bounded(phrase).findall(text))


def word_bounded_sub(text: str, phrase: str, replacement: str) -> str:
    return _word_bounded(phrase).sub(lambda _m: replacement, text)


def _pair_key(a: int, b: int) -> int:
    return (a << 32) | b


class _Repair:
    """Re-Pair over a word-level alphabet with a token-cost-weighted priority."""

    def __init__(self, words: list[str], barrier: str = "\x00") -> None:
        self.expansion: list[list[str]] = []
        self.symbols: dict[str, int] = {}
        self.barrier_id = -1

        self.seq: list[int] = []
        for w in words:
            if w == barrier:
                self.seq.append(self.barrier_id)
                continue
            sid = self.symbols.get(w)
            if sid is None:
                sid = len(self.expansion)
                self.symbols[w] = sid
                self.expansion.append([w])
            self.seq.append(sid)

    def _phrase(self, sid: int) -> list[str]:
        return self.expansion[sid]

    def _value(self, a: int, b: int, occurrences: int) -> int:
        """Estimated tokens saved by promoting this pair to its own symbol."""
        words = self._phrase(a) + self._phrase(b)
        if len(words) > MAX_PHRASE_WORDS:
            return 0
        return occurrences * count(" ".join(words))

    def run(self, min_occurrences: int, max_merges: int = 4000) -> list[list[str]]:
        """Merge repeatedly; return every phrase the grammar built."""
        built: list[list[str]] = []

        for _ in range(max_merges):
            counts: dict[int, int] = defaultdict(int)
            seq = self.seq
            i = 0
            # Count non-overlapping pair occurrences, never spanning a barrier.
            while i < len(seq) - 1:
                a, b = seq[i], seq[i + 1]
                if a == self.barrier_id or b == self.barrier_id:
                    i += 1
                    continue
                key = _pair_key(a, b)
                counts[key] += 1
                # Skip the second element so "a a a" counts one pair, not two.
                i += 2 if a == b else 1

            best_key = None
            best_value = 0
            for key, n in counts.items():
                if n < min_occurrences:
                    continue
                value = self._value(key >> 32, key & 0xFFFFFFFF, n)
                if value > best_value:
                    best_key, best_value = key, value

            if best_key is None:
                break

            a, b = best_key >> 32, best_key & 0xFFFFFFFF
            words = self._phrase(a) + self._phrase(b)
            new_id = len(self.expansion)
            self.expansion.append(words)
            built.append(words)

            out: list[int] = []
            i = 0
            while i < len(seq):
                if i < len(seq) - 1 and seq[i] == a and seq[i + 1] == b:
                    out.append(new_id)
                    i += 2
                else:
                    out.append(seq[i])
                    i += 1
            self.seq = out

        return built


def repair_candidates(
    words: list[str],
    min_occurrences: int = 3,
    max_merges: int = 4000,
) -> list[str]:
    """Return flattened phrase candidates, longest first.

    Only multi-word phrases are useful -- a single word is already its own
    cheapest encoding.
    """
    if len(words) < 2:
        return []
    built = _Repair(words).run(min_occurrences, max_merges)
    phrases = {" ".join(w) for w in built if len(w) >= 2}
    return sorted(phrases, key=len, reverse=True)


def select(
    candidates: list[str],
    corpus: str,
    min_occurrences: int = 3,
    min_phrase_tokens: int = 5,
    max_entries: int = 96,
) -> list[str]:
    """Admit candidates by token payback against a corpus that mutates as we go.

    Acceptance is checked against a working copy with earlier entries already
    substituted, so an entry can never be credited with savings that a
    previously accepted, overlapping entry has already taken.
    """
    working = corpus
    accepted: list[str] = []
    ranked = sorted(candidates, key=lambda p: -(word_bounded_count(corpus, p) * count(p)))

    for phrase in ranked:
        if len(accepted) >= max_entries:
            break
        occurrences = word_bounded_count(working, phrase)
        if occurrences < min_occurrences:
            continue
        tokens = count(phrase)
        if tokens < min_phrase_tokens:
            continue
        saving = (
            occurrences * tokens - occurrences * REF_TOKENS - tokens - REF_TOKENS
        )
        if saving <= 0:
            continue
        accepted.append(phrase)
        working = word_bounded_sub(working, phrase, "\x01")

    return accepted
