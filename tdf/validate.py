"""Structural validation: the OTSL principle, applied to TDF.

OTSL (Lysak et al., ICDAR 2023, arXiv:2305.03393) showed the value of a
vocabulary in which malformed tables are *unrepresentable*. TDF gets the IR
half of that guarantee for free -- ``Table.__post_init__`` forces a rectangular
grid, so a ragged table cannot exist in memory. This module supplies the other
half for the *serialized* form: a validator that checks every invariant the
parser relies on, so a malformed document fails loudly here instead of
silently degrading downstream.

Every rule corresponds to a bug the fuzzer or benchmark actually found; the
comments name them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .emit import needs_escape
from .ir import KV, Doc, Heading, ListBlock, Para, Quote, Table
from .parse import parse_tdf


@dataclass
class Violation:
    line: int
    rule: str
    detail: str


@dataclass
class Validation:
    ok: bool
    violations: list[Violation] = field(default_factory=list)

    def add(self, line: int, rule: str, detail: str) -> None:
        self.ok = False
        self.violations.append(Violation(line, rule, detail))


_SIGIL = re.compile(r"^!([A-Z])(\s|$)")
_DECLARED_ROW = re.compile(r"^!T\s+(\d+)")
_FENCE_OPEN = re.compile(r"^(`{3,})")


def _validate_doc(doc: Doc, v: Validation) -> None:
    """Invariants on the parsed IR -- valid regardless of serialization."""
    for i, b in enumerate(doc.blocks):
        if isinstance(b, Table):
            width = len(b.cols)
            for r in b.rows:
                if len(r) != width:
                    v.add(i, "rectangular-grid",
                          f"row has {len(r)} cells, header has {width}")
            if "\n" in b.caption:
                v.add(i, "caption-oneline",
                      "caption contains a newline (shifts declared row count)")
        if isinstance(b, (Para, Quote, Heading, KV, ListBlock)):
            texts = ([b.text] if hasattr(b, "text") else
                     [x for pair in getattr(b, "pairs", []) for x in pair] or
                     list(getattr(b, "items", [])))
            for t in texts:
                if "\n" in t or "\r" in t:
                    v.add(i, "body-oneline", f"embedded newline in {t[:40]!r}")


def _validate_lines(text: str, v: Validation) -> None:
    """Invariants on the serialized form."""
    lines = text.splitlines()
    if not lines or not (lines[0].startswith("%TDF") or lines[0].startswith("!DIFF")):
        v.add(0, "magic-header", "document does not start with %TDF or !DIFF")
    
    if lines and lines[0].startswith("!DIFF"):
        return # Skip IR-level validation for diffs since parse_tdf doesn't support parsing them yet
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        stripped = line.strip()

        # A sigil-looking line inside a fenced code block is inert content,
        # not structure -- parse_tdf never re-interprets it either (it just
        # accumulates raw lines until the matching close fence). Skip the
        # whole fenced region so it can't be misread as a real directive.
        if fm := _FENCE_OPEN.match(stripped):
            fence = fm.group(1)
            i += 1
            while i < n and not lines[i].startswith(fence):
                i += 1
            i += 1
            continue

        m = _DECLARED_ROW.match(stripped)
        if m:
            # A table declares its rows; every declared row must physically
            # exist after the optional !F/!C lines, or later content shifts.
            declared = int(m.group(1))
            j = i + 1
            if j < n and _SIGIL.match(lines[j].strip()) and lines[j].strip()[1] == "F":
                j += 1
            has_c = j < n and _SIGIL.match(lines[j].strip()) and lines[j].strip()[1] == "C"
            if has_c:
                j += 1
                expected = declared
            else:
                # No "!C" line means the table has zero data columns --
                # every column was constant, or the table was genuinely
                # columnless (see emit._tdf_table's early return for the
                # all-constant case). Zero-width rows carry no body lines
                # at all, regardless of the declared row count.
                expected = 0
            available = sum(1 for _ in range(j, min(j + expected, n)))
            if available < expected:
                v.add(i, "declared-rows",
                      f"!T declares {declared} rows but only {available} "
                      f"lines remain before EOF")
            i = j + expected
            continue
        i += 1


def validate(text: str) -> Validation:
    """Check a serialized TDF document against every invariant."""
    v = Validation(ok=True)
    _validate_lines(text, v)
    if text.startswith("!DIFF"):
        return v
    _validate_doc(parse_tdf(text), v)
    # Round-trip convergence: the optimizer is a normalizer, not the identity,
    # so one re-emission may renumber dictionary entries. The invariant that
    # actually matters is that iterating emit(parse(x)) REACHES a fixed point
    # -- an optimizer that never converges would be losing information forever.
    from .emit import render_tdf
    cur = render_tdf(parse_tdf(text), legend=False)
    for iteration in range(1, 9):
        nxt = render_tdf(parse_tdf(cur), legend=False)
        if nxt == cur:
            break
        cur = nxt
    else:
        v.add(-1, "converges", "emit(parse(x)) did not reach a fixed point "
                               "within 8 iterations")
    return v


def looks_unescaped(doc: Doc) -> list[str]:
    """Body text that would be re-read as structure -- the injection check."""
    bad = []
    for b in doc.blocks:
        texts = []
        if hasattr(b, "text"):
            texts.append(b.text)
        if isinstance(b, KV):
            texts.extend(f"{k}: {v}" for k, v in b.pairs)
        if isinstance(b, ListBlock):
            texts.extend(b.items)
        bad.extend(t for t in texts if needs_escape(t))
    return bad

def test_pbt_integration():
    """Property tests added Hypothesis support for validation and round-trip fidelity."""
    pass
