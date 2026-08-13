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


_STRUCTURAL = re.compile(r"""
      !([A-Z])(\s|$)   # sigil line: !T, !C, !R ...
    | \#{1,6}\s         # heading
    | [-*+]\s           # bullet item
    | \d+[.)]?\s        # ordered item; TDF drops the dot, so "2024 was ..."
                        # would otherwise be eaten as a list marker
    | >\s               # quote
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

_NEWLINE = re.compile(r"[\r\n]+")


def _oneline(v: str) -> str:
    """Collapse embedded newlines so one value stays one physical line.

    TDF is line-oriented and a table declares its row count up front, so a cell
    containing a newline (an Alt+Enter cell in Excel, a wrapped PDF cell) would
    split into two lines, shift every following row by one, and silently
    corrupt the grid. Distinct-content recall cannot see this because the words
    all survive -- only the structure is wrong -- so it must be prevented here.
    """
    return _NEWLINE.sub(" ", v) if v else v


def _quote(v: str) -> str:
    v = _oneline(v)
    if v == "":
        return '""'
    if " " in v or v.startswith('"'):
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
    rows = elide_repeats(rows)

    # Pick whichever separator tokenises cheaper for this specific table.
    space = _render_rows(cols, rows, " ")
    tab = _render_rows(cols, rows, "\t")
    body = space if count(space) <= count(tab) else tab

    head = f"!T {len(rows)}" + (f" {_oneline(t.caption)}" if t.caption else "")
    out = [head]
    if constants:
        out.append("!F " + " ".join(f"{k}={_quote(v)}" for k, v in constants))
    lines = body.split("\n")
    first = lines[0]
    out.append("!C" + ("\t" if "\t" in first else " ") + first)
    out.extend(lines[1:])
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
        out.append("# " + doc.title)

    if arts["dictionary"]:
        out.append(f"!D {len(arts['dictionary'])}")
        out.extend(f"{i + 1} {p}" for i, p in enumerate(arts["dictionary"]))
    if arts["boilerplate"]:
        out.append("!R")
        out.extend(_escape_body(line) for line in arts["boilerplate"])
    for book in codebooks or []:
        out.append(f"!V {book.header}")
        out.extend(f"{code} {val}" for code, val in book.mapping.items())

    for b in doc.blocks:
        if isinstance(b, Heading):
            out.append("#" * min(b.level, 6) + " " + b.text)
        elif isinstance(b, Para):
            out.append(_escape_body(b.text))
        elif isinstance(b, Quote):
            out.append("> " + b.text)
        elif isinstance(b, ListBlock):
            for i, item in enumerate(b.items):
                out.append(f"{i + 1} {item}" if b.ordered else f"- {item}")
        elif isinstance(b, Table):
            out.extend(_tdf_table(b))
        elif isinstance(b, KV):
            out.append("!K" + (f" {_oneline(b.caption)}" if b.caption else ""))
            out.extend(_escape_body(f"{k}: {v}") for k, v in b.pairs)
        elif isinstance(b, Figure):
            out.append("!G " + b.desc)
        elif isinstance(b, Code):
            out.append(f"```{b.lang}\n{b.text}\n```")
        elif isinstance(b, PageMark):
            out.append(f"!P {b.number}")
        elif isinstance(b, Elision):
            out.append(f"!E {b.eid} {b.kind} {b.tokens} {b.items} {b.gist}")

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
