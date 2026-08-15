"""Serializers.

``render_markdown`` is the honest baseline: the best Markdown we can produce
from the IR (GFM pipe tables, standard headings). ``render_tdf`` is the
token-dense format. Both consume the same IR, so the delta is format-only.
"""

from __future__ import annotations

import re

from .ir import Code, Doc, Elision, Figure, Heading, KV, ListBlock, PageMark, Para, Quote, Table
from .optimize import drop_constant_columns, elide_repeats, hoist_units, optimize
from .tokens import count

LEGEND = (
    "%TDF1 Sigil lines are structure; all other lines are body text, one per line. "
    "#=heading (depth by count). !D=phrase table, following 'n text' lines define "
    "\u00a7n, which means that text verbatim wherever it appears. !R=lines that "
    "repeated on every page (running header/footer), stated once. !T n cap=table of "
    "n rows; !F=column values constant for all its rows; !C=column names; then n rows "
    "split on the same separator as !C, where ^=same as the cell above and an empty "
    "field=no value. !K=key: value pairs. !G=figure/chart. !P n=page n. "
    "!V col=values in that table column are CODED: the following 'code value' "
    "lines give the expansion, so a cell reading 'ab' means that value verbatim. "
    "!E id kind ntok nitems gist=a region of that many tokens was OMITTED here to "
    "save space; only the gist is shown. If answering needs it, say so and request "
    "id -- do not guess its contents."
)


_SIGIL_LINE = re.compile(r"^!([A-Z])(\s|$)")
_BACKTICK_RUN = re.compile(r"`+")


def _code_fence(text: str) -> str:
    """A fence strictly longer than any backtick run inside the code.

    A fixed 3-backtick fence terminates on the first embedded ```` ``` ````
    (a Markdown example inside a code block, a shell heredoc, etc.), silently
    truncating the block. CommonMark's own answer is to make the fence longer
    than the longest backtick run in the content; parsing then only needs to
    read the opening fence's actual length instead of assuming 3, which is
    fully backward compatible with every existing 3-backtick document.
    """
    longest = max((len(m.group(0)) for m in _BACKTICK_RUN.finditer(text)), default=0)
    return "`" * max(3, longest + 1)


_STRUCTURAL = re.compile(r"""
      !([A-Z])(\s|$)   # sigil line: !T, !C, !R ...
    | \#{1,6}\s         # heading
    | [-*+]\s           # bullet item
    | \d+[.)]?\s        # ordered item; TDF drops the dot, so "2024 was ..."
                        # would otherwise be eaten as a list marker
    | >\s               # quote
    | `{3,}             # code fence opener; parse_tdf matches any line
                        # starting with 3+ backticks, not just real code blocks
    | %TDF              # magic header
""", re.VERBOSE)


def looks_structural(text: str) -> bool:
    """True if this line would be re-read as structure rather than as text.

    Body text is not safe merely because it avoids sigils: a paragraph reading
    "1. numbered-looking" comes back as an ordered list item with the "1."
    consumed as a marker, silently losing it.
    """
    return bool(_STRUCTURAL.match(text))


def needs_escape(text: str) -> bool:
    """Whether this exact line must be bang-prefixed to survive a round trip."""
    return looks_structural(text) or (
        text.startswith("!") and needs_escape(text[1:])
    )


def _escape_body(text: str) -> str:
    """Protect body text that would otherwise be read as structure.

    Escaping prefixes one bang, and the parser strips one bang whenever the
    remainder looks structural. Those two rules are exact inverses only if we
    also escape text that is *already* bang-prefixed structure ("!!T 5"), or
    unescaping would corrupt it -- hence the second condition.
    """
    text = _oneline(text)
    return "!" + text if needs_escape(text) else text


# ------------------------------------------------------------------ Markdown

def _md_table(t: Table) -> str:
    cols = t.cols or [f"c{i + 1}" for i in range(len(t.rows[0]) if t.rows else 0)]
    w = len(cols)
    out = []
    if t.caption:
        out.append(f"**{t.caption}**\n")
    out.append("| " + " | ".join(cols) + " |")
    out.append("| " + " | ".join(["---"] * w) + " |")
    for r in t.rows:
        cells = [(r[i] if i < len(r) else "").replace("|", "\\|").replace("\n", "<br>")
                 for i in range(w)]
        out.append("| " + " | ".join(cells) + " |")
    return "\n".join(out)


def render_markdown(doc: Doc) -> str:
    out: list[str] = []
    if doc.title:
        out.append(f"# {doc.title}\n")
    for b in doc.blocks:
        if isinstance(b, Heading):
            out.append("#" * min(b.level, 6) + " " + b.text + "\n")
        elif isinstance(b, Para):
            out.append(b.text + "\n")
        elif isinstance(b, Quote):
            out.append("> " + b.text.replace("\n", "\n> ") + "\n")
        elif isinstance(b, ListBlock):
            for i, item in enumerate(b.items):
                out.append(f"{i + 1}. {item}" if b.ordered else f"- {item}")
            out.append("")
        elif isinstance(b, Table):
            out.append(_md_table(b) + "\n")
        elif isinstance(b, KV):
            if b.caption:
                out.append(f"**{b.caption}**\n")
            for k, v in b.pairs:
                out.append(f"- **{k}:** {v}")
            out.append("")
        elif isinstance(b, Figure):
            out.append(f"![{b.desc}]()\n" if b.kind == "image" else f"*{b.desc}*\n")
        elif isinstance(b, Code):
            out.append(f"```{b.lang}\n{b.text}\n```\n")
        elif isinstance(b, PageMark):
            out.append(f"\n---\n\n*Page {b.number}*\n")
        elif isinstance(b, Elision):
            out.append(f"> *[{b.kind} omitted: {b.tokens} tokens, id {b.eid}]* {b.gist}\n")
    return "\n".join(out).strip() + "\n"


# ----------------------------------------------------------------------- TDF

_NEWLINE = re.compile(r"[\r\n\t]+")


def _oneline(v: str) -> str:
    """Collapse embedded newlines (and tabs) so one value stays one physical
    line and never masquerades as a separator.

    TDF is line-oriented and a table declares its row count up front, so a cell
    containing a newline (an Alt+Enter cell in Excel, a wrapped PDF cell) would
    split into two lines, shift every following row by one, and silently
    corrupt the grid. Distinct-content recall cannot see this because the words
    all survive -- only the structure is wrong -- so it must be prevented here.

    A literal tab is the same class of problem one level down: the parser
    decides whether a table used tab or space separation by checking for a
    tab character anywhere on the header line (parse_tdf's ``"\\t" in rest``),
    so a value that merely *contains* a tab -- not used as a separator at all
    -- can flip that detection and misparse an otherwise space-separated row.
    """
    return _NEWLINE.sub(" ", v) if v else v


def _escape_caret_cell(v: str) -> str:
    """A cell literally equal to '^' collides with elide_repeats' own use of
    '^' as a back-reference marker -- the parser has no way to tell "this
    cell's real content is the caret" from "this cell repeats the one above".

    Lengthening any all-caret value by one caret resolves it: a lone '^'
    becomes '^^', and '^^' itself (rare, but possible) becomes '^^^', so no
    escaped form ever collides with a shorter all-caret value that wasn't
    escaped. Unescaping is the exact inverse (drop one trailing caret from any
    all-caret cell of length >= 2), which is unambiguous for the same reason.
    """
    return v + "^" if v and set(v) == {"^"} else v


def _quote(v: str) -> str:
    v = _oneline(v)
    if v == "":
        return '""'
    # Any embedded '"' must trigger quoting, not just a leading one: _split's
    # parser toggles "inside a quoted field" on *every* unescaped '"' it
    # sees, so an unquoted value like '0"0' is misread as a quote opening
    # mid-field with no closing quote, silently dropping the character.
    if " " in v or '"' in v:
        return '"' + v.replace('"', '""') + '"'
    return v


def _render_rows(cols: list[str], rows: list[list[str]], sep: str) -> str:
    w = len(cols)
    lines = [sep.join([_oneline(c) for c in cols] if sep == "\t" else [_quote(c) for c in cols])]
    for r in rows:
        cells = [(r[i] if i < len(r) else "") for i in range(w)]
        lines.append(sep.join([_oneline(c) for c in cells] if sep == "\t"
                                else [_quote(c) for c in cells]))
    return "\n".join(lines)


def _tdf_table(t: Table) -> list[str]:
    cols = list(t.cols) or [f"c{i + 1}" for i in range(len(t.rows[0]) if t.rows else 0)]
    rows = [[(r[i] if i < len(r) else "") for i in range(len(cols))] for r in t.rows]

    cols, rows = hoist_units(cols, rows)
    cols, rows, constants = drop_constant_columns(cols, rows)
    rows = [[_escape_caret_cell(c) for c in r] for r in rows]
    rows = elide_repeats(rows)

    # Pick whichever separator tokenises cheaper for this specific table --
    # except a single-column table has no separator between fields, so the
    # parser has no way to detect tab-mode was used (it decides by checking
    # for a literal tab on the !C line, and a single field never has one).
    # A space in that lone column's value would then be wrongly re-split as
    # if it were two columns. Space mode's quoting makes it unambiguous.
    if len(cols) <= 1:
        body = _render_rows(cols, rows, " ")
    else:
        space = _render_rows(cols, rows, " ")
        tab = _render_rows(cols, rows, "\t")
        body = space if count(space) <= count(tab) else tab

    head = f"!T {len(rows)}" + (f" {_oneline(t.caption)}" if t.caption else "")
    out = [head]
    
    f_line = "!F " + " ".join(f"{k}={_quote(v)}" for k, v in constants) if constants else None
    if f_line:
        out.append(f_line)
        
    lines = body.split("\n")
    first = lines[0]
    c_line = "!C" + ("\t" if "\t" in first else " ") + first
    out.append(c_line)
    
    # Research Brief: Periodic header re-emission to counter long-context degradation
    # Re-emit !C (and !F if present) every 50 rows
    for i, line in enumerate(lines[1:]):
        if i > 0 and i % 50 == 0:
            if f_line:
                out.append(f_line)
            out.append(c_line)
        out.append(line)
        
    return out


def render_tdf(
    doc: Doc,
    legend: bool = True,
    optimized: bool = True,
    codebooks: "list | None" = None,
) -> str:
    """Serialize to TDF. Mutates ``doc`` when ``optimized`` (passes are in-place)."""
    arts = optimize(doc) if optimized else {"boilerplate": [], "dictionary": []}

    out: list[str] = []
    out.append(LEGEND if legend else "%TDF1")
    if doc.title:
        # Same reasoning as Heading blocks below: doc.title is a single
        # physical line, and an embedded newline would create an unprefixed
        # second line vulnerable to sigil injection.
        out.append("# " + _oneline(doc.title))

    if arts["dictionary"]:
        # arts["dictionary"] is (phrase, number) pairs -- number can skip
        # values already used by a literal "§N" in the document (see
        # optimize._reserved_section_refs), so it must not be re-derived
        # from position here. parse_tdf already reads the declared number
        # off each line rather than assuming 1..n, so this is a pure fix.
        out.append(f"!D {len(arts['dictionary'])}")
        out.extend(f"{n} {p}" for p, n in arts["dictionary"])
    if arts["boilerplate"]:
        out.append("!R")
        out.extend(_escape_body(line) for line in arts["boilerplate"])
    for b in doc.blocks:
        if isinstance(b, Heading):
            # A heading embedding a newline whose second line looks like a
            # sigil (e.g. "!T 5 ...") would otherwise open a real structural
            # block on parse -- headings are single-line by construction, so
            # any embedded newline is collapsed rather than split.
            out.append("#" * min(b.level, 6) + " " + _oneline(b.text))
        elif isinstance(b, Para):
            out.append(_escape_body(b.text))
        elif isinstance(b, Quote):
            # Same reasoning as headings: a multi-line quote whose second
            # physical line has no "> " prefix is reparsed as loose text (or,
            # worse, as an injected sigil), not as a continuation of the quote.
            out.append("> " + _oneline(b.text))
        elif isinstance(b, ListBlock):
            for i, item in enumerate(b.items):
                # A list item's own "- "/"N " prefix already stops single-line
                # content from being misread as structure, but an embedded
                # newline creates an unprefixed second physical line that
                # isn't protected -- collapse it before that line can exist.
                out.append(f"{i + 1} {_oneline(item)}" if b.ordered else f"- {_oneline(item)}")
        elif isinstance(b, Table):
            # Emit codebooks specific to this table immediately before it
            for book in codebooks or []:
                if book.table is b:
                    out.append(f"!V {book.header}")
                    out.extend(f"{code} {val}" for code, val in book.mapping.items())
            out.extend(_tdf_table(b))
        elif isinstance(b, KV):
            out.append("!K" + (f" {_oneline(b.caption)}" if b.caption else ""))
            out.extend(_escape_body(f"{k}: {v}") for k, v in b.pairs)
        elif isinstance(b, Figure):
            out.append("!G " + _oneline(b.desc))
        elif isinstance(b, Code):
            fence = _code_fence(b.text)
            out.append(f"{fence}{b.lang}\n{b.text}\n{fence}")
        elif isinstance(b, PageMark):
            out.append(f"!P {b.number}")
        elif isinstance(b, Elision):
            # gist is a free-text field at the end of the !E line; an
            # embedded newline would create the same kind of unprefixed
            # continuation line that let Heading/Quote/ListBlock/Figure
            # injection happen before they were fixed. tier()'s own gist
            # construction already collapses whitespace via str.split(), so
            # this isn't reachable from the current tier() code path, but it
            # closes the same IR-round-trip contract gap for anything else
            # that constructs an Elision directly.
            out.append(f"!E {b.eid} {b.kind} {b.tokens} {b.items} {_oneline(b.gist)}")

    return "\n".join(l for l in out if l is not None) + "\n"


# ------------------------------------------------------------------ skeleton

def _section_ids(doc: Doc):
    """Yield (section_id, heading) assigning ids by *effective* depth.

    Documents skip heading levels constantly (an h3 with no h2 above it). Using
    the raw level produces ids like `2.0.5`, which are ugly and, worse, are not
    what a reader would guess when asking to expand a section. A stack maps
    whatever levels appear onto consecutive depths.
    """
    stack: list[int] = []
    counters: list[int] = []
    used: set[str] = set()
    for b in doc.blocks:
        if not isinstance(b, Heading):
            yield None, b
            continue
        lvl = min(b.level, 6)
        while stack and stack[-1] > lvl:
            stack.pop()
            counters.pop()
        if stack and stack[-1] == lvl:
            counters[-1] += 1
        else:
            stack.append(lvl)
            counters.append(1)
        # Levels can jump backwards (a level-3 heading before any level-1), which
        # can regenerate an id already handed out. Ids are retrieval handles, so
        # uniqueness matters more than a perfect outline.
        while (sid := ".".join(str(c) for c in counters)) in used:
            counters[-1] += 1
        used.add(sid)
        yield sid, b


def render_skeleton(doc: Doc, encoding: str = "o200k_base") -> str:
    """Navigation-only view: headings plus what each section costs to expand.

    This is the 'load the map, fetch the territory on demand' mode. An agent
    reads this first and only requests the sections it needs.
    """
    out = [
        "%TDFSKEL1 outline only. 'id' selects a section to expand; 'tok' is its "
        "cost in tokens; 'p' is its page.",
    ]
    if doc.title:
        out.append("# " + doc.title)

    sections: list[dict] = []
    cur = {"id": "0", "title": "(preamble)", "page": 1, "tok": 0, "kinds": set()}
    page = 1

    def push():
        if cur["tok"] or cur["title"] != "(preamble)":
            sections.append(dict(cur, kinds=set(cur["kinds"])))

    for sid, b in _section_ids(doc):
        if sid is not None:
            push()
            cur = {"id": sid, "title": b.text, "page": page, "tok": 0, "kinds": set()}
            continue
        if isinstance(b, PageMark):
            page = b.number
        elif isinstance(b, Table):
            cur["kinds"].add(f"table{len(b.rows)}x{len(b.cols)}")
            cur["tok"] += count("\n".join(_tdf_table(b)), encoding)
        elif isinstance(b, Figure):
            cur["kinds"].add("figure")
            cur["tok"] += count(b.desc, encoding)
        elif isinstance(b, ListBlock):
            cur["tok"] += count("\n".join(b.items), encoding)
        elif isinstance(b, (Para, Quote)):
            cur["tok"] += count(b.text, encoding)
        elif isinstance(b, KV):
            cur["tok"] += count("\n".join(f"{k}{v}" for k, v in b.pairs), encoding)
        elif isinstance(b, Code):
            cur["kinds"].add("code")
            cur["tok"] += count(b.text, encoding)
    push()

    for s in sections:
        extra = (" " + ",".join(sorted(s["kinds"]))) if s["kinds"] else ""
        out.append(f"{s['id']} {s['title']} p{s['page']} ~{s['tok']}{extra}")
    return "\n".join(out) + "\n"


def extract_sections(doc: Doc, ids: list[str]) -> Doc:
    """Return a Doc containing only the requested skeleton section ids (and
    their descendants). This is the 'expand on demand' half of skeleton mode."""
    wanted = set(ids)
    keep: list = []
    active = False
    for sid, b in _section_ids(doc):
        if sid is not None:
            active = any(sid == w or sid.startswith(w + ".") for w in wanted)
            if active:
                keep.append(b)
            continue
        if active:
            keep.append(b)
    return Doc(title=doc.title, source=doc.source, blocks=keep, meta=dict(doc.meta))
