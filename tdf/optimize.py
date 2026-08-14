"""Lossless-in-meaning token reduction passes.

Every pass here is reversible or explicitly declared in the output, so a model
reading the result can reconstruct the original meaning. Nothing is summarised
away; we only remove *encoding overhead* and *literal repetition*.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter, defaultdict

from .ir import Doc, Figure, Heading, KV, ListBlock, Para, Quote, Table
from .repair import repair_candidates, select, word_bounded_sub
from .tokens import count

# ---------------------------------------------------------------- text hygiene

_UNI = {
    "\u2018": "'", "\u2019": "'", "\u201a": "'", "\u201b": "'",
    "\u201c": '"', "\u201d": '"', "\u201e": '"', "\u201f": '"',
    "\u2013": "-", "\u2014": "-", "\u2012": "-", "\u2212": "-",
    "\u2022": "-", "\u00b7": "-", "\u25cf": "-", "\u25aa": "-", "\u2023": "-",
    "\u00a0": " ", "\u2007": " ", "\u202f": " ", "\u2009": " ", "\u200b": "",
    "\u2026": "...", "\ufb01": "fi", "\ufb02": "fl", "\ufeff": "",
    "\u00ad": "",
}
_UNI_RE = re.compile("|".join(map(re.escape, _UNI)))

# Asterisk emphasis is unambiguous -- `*` is never part of an identifier, so
# intraword use (*bold*inside*text*) is safe to strip exactly as before.
_EMPHASIS_STAR = re.compile(r"(\*\*\*|\*\*|\*)(?=\S)(.+?)(?<=\S)\1", re.S)
# Underscore emphasis is not: `foo_bar_baz`, `__init__`, `api_key_secret` are
# all real identifiers a technical document is full of, and treating every
# underscore pair as emphasis destroyed them (`foo_bar_baz` -> `foobarbaz`,
# `__init__` -> `init`). Two guards, both needed:
#   (?<!\w) ... (?!\w)   CommonMark's intraword rule -- a delimiter touching
#                        a word character on its outside edge never opens or
#                        closes emphasis. Protects foo_bar_baz, _internal_var.
#   content must be multi-word    __init__ and __name__ satisfy the intraword
#                        rule (nothing outside the dunders), so that rule
#                        alone still stripped them to `init`/`name` --
#                        genuine underscore emphasis in prose is essentially
#                        always multi-word ("_this is emphasis_"), while a
#                        bare single "word" wrapped in underscores is far
#                        more likely to be a code identifier in TDF's target
#                        domain. `__init__` and `__strong__` are otherwise
#                        lexically identical (single word, same delimiter) --
#                        there is no local-pattern rule that strips one but
#                        not the other, so this trades a small, one-sided
#                        cost (single-word underscore emphasis no longer
#                        strips -- extra tokens kept, never content lost) for
#                        protecting the identifier case, matching "semantic
#                        correctness over ratio".
#
# The content pattern itself needs care too: a naive `.+?` forced to contain
# a space will happily backtrack THROUGH an adjacent, unrelated delimiter
# run to find one further away -- "_ital_ and __strong__" collapsed into one
# match spanning the whole string, with the inner "__" swallowed as content.
# Restricting content to "non-underscore, or an underscore that is itself
# intraword" stops a delimiter-adjacent underscore (whitespace on one side)
# from ever being consumed as plain content, so each run is matched
# independently.
_CONTENT = r"(?:[^_\s]|(?<=\w)_(?=\w)|\s(?!_))"
_EMPHASIS_UNDERSCORE = re.compile(
    r"(?<!\w)(___|__|_)(?=\S)(" + _CONTENT + r"*\s" + _CONTENT + r"*)(?<=\S)\1(?!\w)", re.S
)
_MD_ESCAPE = re.compile(r"\\([\\`*_{}\[\]()#+\-.!|>~])")
_WS = re.compile(r"[ \t]+")
_HYPHEN_BREAK = re.compile(r"(\w)-\n(\w)")


def clean_text(s: str, strip_emphasis: bool = True) -> str:
    """Normalise text to its cheapest tokenisation without changing meaning.

    Curly quotes, en/em dashes, ligatures and non-breaking spaces all cost extra
    tokens versus their ASCII equivalents while carrying no semantic payload.
    Markdown emphasis markers are pure presentation, so they go too.
    """
    if not s:
        return ""
    s = unicodedata.normalize("NFKC", s)
    s = _UNI_RE.sub(lambda m: _UNI[m.group(0)], s)
    s = _HYPHEN_BREAK.sub(r"\1\2", s)
    if strip_emphasis:
        prev = None
        while prev != s:
            prev = s
            s = _EMPHASIS_STAR.sub(r"\2", s)
            s = _EMPHASIS_UNDERSCORE.sub(r"\2", s)
    s = _MD_ESCAPE.sub(r"\1", s)
    s = _WS.sub(" ", s)
    return s.strip()


# ------------------------------------------------------------ cell / number ops

_NUM = re.compile(r"^\s*([\-+(]?)\s*([$\u20ac\u00a3\u00a5]?)\s*([\d,]+(?:\.\d+)?)\s*([%)]?)\s*$")


def normalize_cell(v: str) -> str:
    """`$1,234.00` -> `1234` and friends. Currency/percent are hoisted to the
    column header by :func:`hoist_units`, so stripping them here is safe."""
    v = clean_text(str(v))
    if not v:
        return ""
    m = _NUM.match(v)
    if not m:
        return v
    sign, cur, body, suffix = m.groups()
    # `(` and `)` are only a negative marker as a matched pair -- an unpaired
    # paren ("123)", "(123") is not accounting notation at all, and treating
    # it as one fabricates a sign that was never there. Leave the value
    # untouched rather than guess.
    if (sign == "(") != (suffix == ")"):
        return v
    body = body.replace(",", "")
    if "." in body:
        body = body.rstrip("0").rstrip(".") or "0"
    neg = sign == "-" or (sign == "(" and suffix == ")")
    return ("-" if neg else "") + cur + body + ("%" if suffix == "%" else "")


# Sign comes before the currency symbol here ("-$100"), matching what
# normalize_cell actually emits (its own return statement prepends "-"
# before `cur`) -- putting the optional sign inside the number group instead
# ("$-100") would never match normalize_cell's real output, so an entire
# common category (negative currency amounts -- accounting figures are
# routinely negative) silently never qualified for hoisting. Not a
# correctness bug (an unmatched column is simply left un-hoisted, cells stay
# correct), but a real, avoidable compression miss on exactly the kind of
# data this format targets.
_UNIT_RE = re.compile(r"^(-)?([$\u20ac\u00a3\u00a5])?([\d.]+)(%)?$")


def hoist_units(cols: list[str], rows: list[list[str]]) -> tuple[list[str], list[list[str]]]:
    """If every value in a column shares a currency symbol or trailing `%`,
    move it into the header once instead of repeating it on every row."""
    if not rows:
        return cols, rows
    cols = list(cols)
    rows = [list(r) for r in rows]
    for c in range(len(cols)):
        vals = [r[c] for r in rows if c < len(r) and r[c]]
        if len(vals) < 3:
            continue
        marks = set()
        for v in vals:
            m = _UNIT_RE.match(v)
            if not m:
                marks.add(None)
                break
            marks.add(m.group(2) or m.group(4))
        if len(marks) == 1 and (mark := marks.pop()):
            cols[c] = f"{cols[c]}({mark})"
            for r in rows:
                if c < len(r) and r[c]:
                    r[c] = r[c].replace(mark, "", 1)
    return cols, rows


def drop_constant_columns(
    cols: list[str], rows: list[list[str]]
) -> tuple[list[str], list[list[str]], list[tuple[str, str]]]:
    """A column with one distinct value across 4+ rows is stated once as a fact
    about the table rather than repeated per row."""
    if len(rows) < 4:
        return cols, rows, []
    keep, constants = [], []
    for c, name in enumerate(cols):
        # A ragged row missing this cell entirely is not the same claim as an
        # agreeing value -- it must count as a disagreement (via the `None`
        # sentinel, distinct from any real string including ""), not be
        # silently excluded from consideration the way `if c < len(r)` did.
        vals = {r[c] if c < len(r) else None for r in rows}
        if len(vals) == 1 and (v := next(iter(vals))):
            constants.append((name, v))
        else:
            keep.append(c)
    if not constants:
        return cols, rows, []
    return ([cols[c] for c in keep],
            [[r[c] for c in keep if c < len(r)] for r in rows],
            constants)


def elide_repeats(rows: list[list[str]], marker: str = "^") -> list[list[str]]:
    """Replace a cell identical to the one directly above it with a 1-token
    marker. Sorted exports (the common spreadsheet case) repeat heavily."""
    out: list[list[str]] = []
    prev: list[str] | None = None
    for r in rows:
        if prev is None:
            out.append(list(r))
        else:
            new = []
            for i, v in enumerate(r):
                same = i < len(prev) and v == prev[i] and v != ""
                new.append(marker if (same and count(v) > 1) else v)
            out.append(new)
        prev = list(r)
    return out


# -------------------------------------------------------------- boilerplate

def strip_boilerplate(doc: Doc, min_repeats: int = 3) -> list[str]:
    """Detect running headers/footers and per-page furniture.

    A short line that recurs verbatim many times through a document is page
    furniture, not content. We remove every copy and declare it once. Applies to
    both standalone paragraphs and list items (slide decks put chrome in both).

    This is intentionally lossy about everything except the literal text: all
    N occurrences collapse to one, parse_tdf reinserts that one as a plain
    Para positioned right after the legend (see its "!R" handling) -- not at
    any of the original occurrences' positions, and not preserving whichever
    original block type carried it (a ListBlock item that was boilerplate
    comes back as a standalone Para, not a list item). Distinct-content
    recall is therefore unaffected, but position/count/type are not
    recoverable from the declaration alone -- unlike `!E` elision, which
    marks its exact original position. The heuristic itself (recur >=
    min_repeats times, <=200 chars, >=3 tokens) has no positional signal
    either, so it fires equally on genuine page furniture and on any other
    short line a document happens to repeat >=3 times -- both get the same
    relocate-and-retype treatment.
    """
    counts: Counter[str] = Counter()
    for b in doc.blocks:
        if isinstance(b, Para):
            t = b.text.strip()
            if 0 < len(t) <= 200:
                counts[t] += 1
        elif isinstance(b, ListBlock):
            for it in b.items:
                t = it.strip()
                if 0 < len(t) <= 200:
                    counts[t] += 1

    boiler = {t for t, c in counts.items() if c >= min_repeats and count(t) >= 3}
    if not boiler:
        return []

    kept, seen = [], set()
    for b in doc.blocks:
        if isinstance(b, Para) and b.text.strip() in boiler:
            seen.add(b.text.strip())
            continue
        if isinstance(b, ListBlock):
            new_items = []
            for it in b.items:
                if it.strip() in boiler:
                    seen.add(it.strip())
                else:
                    new_items.append(it)
            if not new_items:
                continue
            b.items = new_items
        kept.append(b)
    doc.blocks = kept
    return sorted(seen, key=lambda t: -counts[t])


# --------------------------------------------------------------- dictionary

_WORD = re.compile(r"\S+")
_SECTION_REF = re.compile(r"§(\d+)")


def _reserved_section_refs(doc: Doc) -> set[int]:
    """Numbers already used by a literal '§N' somewhere in the document.

    '§' (section sign) is a real character in legal/academic text --
    "§1", "§2.3" are ordinary section references, not something a
    reader needs to guess might appear. parse_tdf's expand() can't tell our
    own inserted reference apart from text that already looked like one, so
    if build_dictionary reused number N for a phrase while the document also
    contains a literal '§N', that literal text would be silently
    replaced by the phrase on parse. Scan everywhere expand() is applied on
    the read side (title, Heading, Para, Quote, ListBlock, Figure, Table
    caption, KV pairs) so every number already spoken for is avoided.
    """
    found: set[int] = set()

    def scan(s: str) -> None:
        found.update(int(m) for m in _SECTION_REF.findall(s))

    scan(doc.title)
    for b in doc.blocks:
        if isinstance(b, (Para, Quote, Heading)):
            scan(b.text)
        elif isinstance(b, Figure):
            scan(b.desc)
        elif isinstance(b, ListBlock):
            for item in b.items:
                scan(item)
        elif isinstance(b, Table):
            scan(b.caption)
        elif isinstance(b, KV):
            for k, v in b.pairs:
                scan(k)
                scan(v)
    return found


class _ItemSlot:
    """Adapter so a list item can be written back like an object attribute.

    `ListBlock` stores bare strings, but the dictionary pass rewrites text via
    setattr. Wrapping each item keeps one uniform interface instead of forking
    the substitution loop.
    """

    __slots__ = ("_block", "_index")

    def __init__(self, block: ListBlock, index: int) -> None:
        self._block, self._index = block, index

    @property
    def text(self) -> str:
        return self._block.items[self._index]

    @text.setter
    def text(self, value: str) -> None:
        self._block.items[self._index] = value


def _iter_texts(doc: Doc):
    for b in doc.blocks:
        if isinstance(b, (Para, Quote)):
            yield b, "text", b.text
        elif isinstance(b, Heading):
            yield b, "text", b.text
        elif isinstance(b, Figure):
            yield b, "desc", b.desc
        elif isinstance(b, ListBlock):
            # Bullet text carries as much repetition as prose; on nav-heavy
            # pages it is the *majority* of the document.
            for i, item in enumerate(b.items):
                if item:
                    yield _ItemSlot(b, i), "text", item


def _maximal_repeats(words: list[str], min_occ: int, seed: int, max_words: int) -> list[str]:
    """Find maximal repeated word sequences via seed-and-extend.

    Enumerating every n-gram for n in 4..24 is quadratic and mostly wasted, so
    we index one seed length, keep only seeds that already repeat, then extend
    each rightwards as long as it keeps repeating.
    """
    if len(words) < seed:
        return []
    index: dict[tuple, list[int]] = defaultdict(list)
    for i in range(len(words) - seed + 1):
        index[tuple(words[i : i + seed])].append(i)

    phrases: list[str] = []
    for key, pos in index.items():
        if len(pos) < min_occ:
            continue
        n = seed
        cur = pos
        while n < max_words:
            nxt: dict[str, list[int]] = defaultdict(list)
            for p in cur:
                if p + n < len(words):
                    nxt[words[p + n]].append(p)
            best = max(nxt.items(), key=lambda kv: len(kv[1]), default=None)
            if best is None or len(best[1]) < min_occ:
                break
            cur = best[1]
            n += 1
        phrases.append(" ".join(words[cur[0] : cur[0] + n]))
    return phrases


def build_dictionary(
    doc: Doc,
    min_occurrences: int = 3,
    max_entries: int = 96,
    min_phrase_tokens: int = 5,
    max_phrase_words: int = 40,
) -> list[tuple[str, int]]:
    """Find repeated multi-word phrases and replace them with `§n` references.

    Returns ``(phrase, n)`` pairs, not just phrases -- ``n`` can skip numbers
    already used by a literal ``§N`` elsewhere in the document (see
    ``_reserved_section_refs``), so the caller must not assume 1..len(result).

    Entries are accepted greedily against a *working copy* of the corpus that
    already has earlier entries substituted in. That is what stops overlapping
    candidates from being accepted and then never firing, which would spend
    tokens on a definition line that saves nothing.

        saving = occurrences * cost(phrase)      # what we stop paying
               - occurrences * 2                 # what each `§n` use costs
               - cost(phrase) - 2                # the definition line itself
    """
    texts = [(obj, attr, val) for obj, attr, val in _iter_texts(doc) if val]
    if not texts:
        return []

    corpus = "\n".join(v for _, _, v in texts)
    if len(corpus) > 4_000_000:
        return []

    words: list[str] = []
    for _, _, val in texts:
        words.extend(_WORD.findall(val))
        words.append("\x00")  # barrier so phrases never span two blocks

    candidates = [
        c
        for c in repair_candidates(words, min_occurrences)
        if "\x00" not in c and len(c.split()) <= max_phrase_words
    ]
    accepted = select(
        candidates,
        corpus,
        min_occurrences=min_occurrences,
        min_phrase_tokens=min_phrase_tokens,
        max_entries=max_entries,
    )

    if not accepted:
        return []

    # Apply in acceptance order so the substitution mirrors the accounting.
    # Skip any number a literal '\u00a7N' in the document already uses -- see
    # _reserved_section_refs.
    reserved = _reserved_section_refs(doc)
    numbers: list[int] = []
    nxt = 1
    for _ in accepted:
        while nxt in reserved:
            nxt += 1
        numbers.append(nxt)
        reserved.add(nxt)
        nxt += 1
    repl = {p: f"\u00a7{n}" for p, n in zip(accepted, numbers)}
    for obj, attr, val in texts:
        for p in accepted:
            val = word_bounded_sub(val, p, repl[p])
        setattr(obj, attr, val)
    # Numbers may skip reserved values above, so the caller (the !D legend
    # emitter) needs the actual (phrase, number) pairs, not just the phrase
    # list with an assumed 1..n numbering -- see _reserved_section_refs.
    return list(zip(accepted, numbers))


# ------------------------------------------------------------------ pipeline

def optimize(doc: Doc, use_dictionary: bool = True) -> dict:
    """Run every reduction pass. Returns the artifacts the emitter must declare."""
    for b in doc.blocks:
        if isinstance(b, (Para, Quote)):
            b.text = clean_text(b.text)
        elif isinstance(b, Heading):
            b.text = clean_text(b.text)
        elif isinstance(b, Figure):
            b.desc = clean_text(b.desc)
        elif isinstance(b, ListBlock):
            b.items = [clean_text(i) for i in b.items]
        elif isinstance(b, KV):
            b.pairs = [(clean_text(k), clean_text(v)) for k, v in b.pairs]
        elif isinstance(b, Table):
            b.caption = clean_text(b.caption)
            b.cols = [clean_text(c) for c in b.cols]
            b.rows = [[normalize_cell(v) for v in r] for r in b.rows]

    doc.blocks = [
        b for b in doc.blocks
        if not (isinstance(b, Para) and not b.text)
        and not (isinstance(b, ListBlock) and not any(b.items))
    ]

    boiler = strip_boilerplate(doc)
    dictionary = build_dictionary(doc) if use_dictionary else []
    return {"boilerplate": boiler, "dictionary": dictionary}
