"""Mission section 5D: template extraction.

The mission's worked example is a set of prose sentences sharing a
fill-in-the-blank shape ("Revenue in {country} increased to {value}"). The
existing phrase dictionary (tdf/optimize.py's build_dictionary, mission
section 5A/5C) only substitutes an exact, fixed multi-word span wherever it
repeats verbatim -- it has no notion of a sentence template with typed
slots that vary between instances. This module adds that: a group of
same-length Para sentences that agree on every word except a small,
consistent set of positions gets factored into one skeleton declaration
(the fixed words) plus one compact per-instance reference (the slot
values), instead of paying for the whole sentence's near-duplicate text on
every occurrence.

Scope, deliberately narrow for a first version (documented, not silently
assumed):
  - Para blocks only. Quote and ListBlock items are real candidates too,
    but each needs its own parse-side interception point (tdf/parse.py has
    one per block kind) and its own escaping/marker-collision check --
    narrower scope now, real follow-up work, not a limitation this module
    hides.
  - Whole-block matching only: the ENTIRE text of a Para must be one
    matched sentence. A sentence embedded among other prose in the same
    Para, or a Para with more than one sentence, is never a candidate --
    this sidesteps sub-string substitution entirely (no risk of mangling
    surrounding text, no sentence-boundary-detection heuristics that would
    need their own accuracy argument for abbreviations like "Mr.").
  - Same word count only, whitespace-tokenized. No reordering, insertion,
    or deletion between instances -- word position IS the alignment.

Wire form is deliberately plain: "~<id> <slot0> <slot1> ...", space-joined,
with NO escaping of the slot values. This only works because a slot value
is always exactly one whitespace-delimited token from the original
sentence (guaranteed empty of internal whitespace by construction, since
str.split() never produces one) -- an earlier version of this module used
a "~M<id>(<v0>|<v1>|...)" syntax with pipe/backslash escaping, which is
unnecessary given that guarantee and was measured to cost MORE tokens than
it saved (the parens and pipes are real BPE tokens with nothing to buy):
"~M1(India|100.)" priced at 8 tokens on o200k_base, the exact same as the
5-word sentence it was replacing, while the plain "~1 India 100." form
prices at 6 -- see this module's own tests for the measured economics.

Runs AFTER tdf/optimize.py's build_dictionary in the pipeline (see
optimize()), not before: this lets the word-level phrase dictionary see
pristine sentence text first (better phrase candidates), and means any
'§n' reference the dictionary already substituted into a matched
sentence is simply treated as one more literal "word" by clustering here
-- it composes correctly without either pass needing to know about the
other. tdf/parse.py's template-reference interception runs BEFORE the
generic per-line expand() call (not after), so a reconstructed sentence
that still contains a literal '§n' gets it expanded exactly the same
way any other line would.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .ir import Doc, Para
from .tokens import count

MIN_WORDS = 4
MIN_INSTANCES = 3
MAX_SLOTS = 6

MARKER_RE = re.compile(r"^~(\d+)(?:\s+(.*))?$")
_COLLISION_RE = re.compile(r"^~\d+(\s|$)")

# The "!M <count>" header line itself is only emitted once per document, no
# matter how many templates it declares -- but each cluster's own economics
# check runs independently, before it's known how many OTHER clusters will
# also be accepted and could share that one line's cost. Charging each
# cluster the full header cost, as if it were the only template in the
# document, is conservative (it can only make acceptance harder, never
# creates a false positive from underestimating overhead) -- the same
# "demand a real margin" bias tdf/columnar.py's own docstring states for
# its own break-even estimate.
_HEADER_TOKENS = count("!M 1")


def _tokenize(text: str) -> list[str]:
    return text.split()


def collides_with_marker(doc: Doc) -> bool:
    """True if some Para's WHOLE existing text already looks like a
    template reference ("~<digits>" at the start) -- an extremely
    unlikely coincidence in real prose, but template extraction bails out
    entirely for the whole document rather than risk misreading it back
    (same conservative instinct as this project's other marker-collision
    guards, e.g. emit._render_member_row's force-quoting of a member row
    starting with '@'). Anchored to the whole block, matching exactly what
    parse.py's MARKER_RE.match(line) tests -- a mid-sentence '~3' deep
    inside otherwise-ordinary prose is not this module's problem, since
    only a WHOLE block ever becomes a reference in the first place."""
    return any(isinstance(b, Para) and _COLLISION_RE.match(b.text) for b in doc.blocks)


@dataclass
class _Cluster:
    reference_words: list[str]
    slot_positions: tuple[int, ...] | None = None
    members: list[list[str]] = field(default_factory=list)
    block_indices: list[int] = field(default_factory=list)


@dataclass
class TemplateDef:
    tid: int
    skeleton_words: list[str]        # fixed words, in position order (slots omitted)
    slot_positions: tuple[int, ...]  # ascending, 0-indexed into the full word list

    @property
    def total_len(self) -> int:
        return len(self.skeleton_words) + len(self.slot_positions)

    def fill(self, slot_values: list[str]) -> str:
        """Reconstruct the original sentence text from this template's
        skeleton plus one instance's slot values."""
        words: list[str] = []
        si = ii = 0
        slots = set(self.slot_positions)
        for pos in range(self.total_len):
            if pos in slots:
                words.append(slot_values[si]); si += 1
            else:
                words.append(self.skeleton_words[ii]); ii += 1
        return " ".join(words)


def _cluster_bucket(candidates: list[tuple[int, list[str]]]) -> list[_Cluster]:
    """Single-pass greedy clustering within one word-count bucket.
    `candidates` is [(block_index, words), ...] in document order.

    A cluster starts as a single sentence with no established slots. The
    second sentence to match it (agreeing everywhere except a small,
    bounded set of positions) establishes slot_positions permanently;
    every later candidate must then agree on every non-slot position
    exactly to join. Two sentences that are byte-identical (diff size 0)
    never establish a cluster on their own -- an exact duplicate repeated
    enough times is already the phrase dictionary's job (it runs first;
    see this module's docstring), and if it wasn't dictionary-eligible
    there is no template to build from it either.
    """
    clusters: list[_Cluster] = []
    for block_idx, words in candidates:
        placed = False
        for cl in clusters:
            if cl.slot_positions is None:
                diff = [i for i in range(len(words)) if words[i] != cl.reference_words[i]]
                if 1 <= len(diff) <= MAX_SLOTS:
                    cl.slot_positions = tuple(diff)
                    cl.members.append(words)
                    cl.block_indices.append(block_idx)
                    placed = True
                    break
            else:
                if all(words[i] == cl.reference_words[i]
                       for i in range(len(words)) if i not in cl.slot_positions):
                    cl.members.append(words)
                    cl.block_indices.append(block_idx)
                    placed = True
                    break
        if not placed:
            clusters.append(_Cluster(reference_words=words, members=[words], block_indices=[block_idx]))
    return clusters


def _reference_line(tid: int, member: list[str], slot_positions: tuple[int, ...]) -> str:
    values = " ".join(member[p] for p in slot_positions)
    return f"~{tid} {values}" if values else f"~{tid}"


def _cluster_economics(cluster: _Cluster) -> int | None:
    """Net token savings if this cluster becomes a template, or None if
    not positive. Uses a representative id (1) for cost estimation --
    the real id assigned later differs by at most a digit or two, never
    enough to flip a decision made with a real margin."""
    tokens_before = sum(count(" ".join(w)) for w in cluster.members)
    skeleton_words = [w for i, w in enumerate(cluster.reference_words)
                       if i not in cluster.slot_positions]
    decl_line = (f"1 {','.join(str(p) for p in cluster.slot_positions)} "
                 + " ".join(skeleton_words))
    tokens_after = _HEADER_TOKENS + count(decl_line) + sum(
        count(_reference_line(1, m, cluster.slot_positions)) for m in cluster.members
    )
    savings = tokens_before - tokens_after
    return savings if savings > 0 else None


def build_templates(doc: Doc) -> list[TemplateDef]:
    """Detect and apply template extraction across every Para block.

    Mutates matched Para blocks' `.text` in place to their compact
    "~id v0 v1 ..." reference form. Returns the accepted TemplateDef list
    (empty if none cleared the net-positive-and-min-instances bar, or if
    collides_with_marker found existing text that looks like a reference
    already) -- the caller (render_tdf) uses this to emit the `!M` legend.
    """
    if collides_with_marker(doc):
        return []

    candidates_by_len: dict[int, list[tuple[int, list[str]]]] = {}
    for idx, b in enumerate(doc.blocks):
        if not isinstance(b, Para) or not b.text:
            continue
        words = _tokenize(b.text)
        if len(words) < MIN_WORDS:
            continue
        candidates_by_len.setdefault(len(words), []).append((idx, words))

    accepted: list[tuple[_Cluster, int]] = []  # (cluster, token_savings)
    for length in sorted(candidates_by_len):
        for cl in _cluster_bucket(candidates_by_len[length]):
            if cl.slot_positions is None or len(cl.members) < MIN_INSTANCES:
                continue
            savings = _cluster_economics(cl)
            if savings is not None:
                accepted.append((cl, savings))

    if not accepted:
        return []

    templates: list[TemplateDef] = []
    for tid, (cl, _savings) in enumerate(accepted, start=1):
        skeleton_words = [w for i, w in enumerate(cl.reference_words)
                           if i not in cl.slot_positions]
        templates.append(TemplateDef(tid=tid, skeleton_words=skeleton_words,
                                      slot_positions=cl.slot_positions))
        for block_idx, member in zip(cl.block_indices, cl.members):
            doc.blocks[block_idx].text = _reference_line(tid, member, cl.slot_positions)

    return templates
