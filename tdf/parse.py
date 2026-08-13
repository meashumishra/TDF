"""Parse TDF back into the IR.

Round-tripping is how we demonstrate the format is *lossless in meaning*: the
content that goes in comes back out, minus only the encoding overhead and the
literal repetition we deliberately removed (and which is restored here).
"""

from __future__ import annotations

import re

from .emit import needs_escape
from .ir import Code, Doc, Elision, Figure, Heading, KV, ListBlock, PageMark, Para, Quote, Table

_H = re.compile(r"^(#{1,6})\s+(.*)$")
_REF = re.compile(r"\u00a7(\d+)")
_UNIT_COL = re.compile(r"^(.*)\(([$\u20ac\u00a3\u00a5%])\)$")


def _unquote(cell: str) -> str:
    if len(cell) >= 2 and cell[0] == '"' and cell[-1] == '"':
        return cell[1:-1].replace('""', '"')
    return cell


def _split(line: str, sep: str) -> list[str]:
    if sep == "\t":
        return line.split("\t")
    out, buf, inq = [], [], False
    i = 0
    while i < len(line):
        ch = line[i]
        if inq:
            if ch == '"':
                if i + 1 < len(line) and line[i + 1] == '"':
                    buf.append('"'); i += 2; continue
                inq = False
            else:
                buf.append(ch)
        elif ch == '"':
            inq = True
        elif ch == " ":
            out.append("".join(buf)); buf = []
        else:
            buf.append(ch)
        i += 1
    out.append("".join(buf))
    return out


_SIGILS = "DRTFCKGPEV"


def _is_sigil(line: str, letter: str) -> bool:
    """True only when the line *is* that sigil, not merely starts with it.

    `startswith("!T")` also matches the sentence "!Try it now", and
    `startswith("!K")` matches "!Kubernetes is great" -- both of which occur in
    real documents and were silently reparsed as structure, destroying content.
    A sigil must be followed by whitespace or end of line.
    """
    return bool(re.match(rf"^!{re.escape(letter)}(\s|$)", line))


_SIGIL_START = re.compile(r"^!([A-Z])(\s|$)")


def _starts_sigil(line: str) -> bool:
    """True if the line opens a structural region.

    Multi-line regions used to end on a bare leading "!", so ordinary text like
    "!Kubernetes is great" truncated the region and dropped everything after it.
    """
    return bool(_SIGIL_START.match(line.strip()))


_HEADING = re.compile(r"^#+\s")


def _starts_heading(line: str) -> bool:
    """Headings use one to six hashes, so matching only "# " misses "## x"."""
    return bool(_HEADING.match(line))


def _int(text: str, default: int = 0) -> int:
    """Never raise on a malformed sigil argument.

    A parser fed arbitrary text must degrade, not crash: "!P 3: !Kubernetes"
    is a page mark whose argument is not a number, and losing the page number
    is preferable to losing the document.
    """
    try:
        return int(text.strip().split()[0]) if text.strip() else default
    except (ValueError, IndexError):
        return default


def _unescape(line: str) -> str:
    """Exact inverse of the emitter's leading-bang escape."""
    return line[1:] if line.startswith("!") and needs_escape(line[1:]) else line


def parse_tdf(text: str) -> Doc:
    lines = text.splitlines()
    doc = Doc()
    dictionary: dict[int, str] = {}
    boilerplate: list[str] = []
    codebooks: dict[str, dict[str, str]] = {}
    items: list[str] = []
    ordered = False

    def flush():
        nonlocal items, ordered
        if items:
            doc.add(ListBlock(items, ordered))
            items, ordered = [], False

    def expand(s: str) -> str:
        return _REF.sub(lambda m: dictionary.get(int(m.group(1)), m.group(0)), s)

    i, n = 0, len(lines)
    while i < n:
        line = lines[i]
        stripped = line.strip()

        if i == 0 and stripped.startswith("%TDF"):
            i += 1; continue
        if not stripped:
            i += 1; continue

        if _is_sigil(stripped, "D"):
            m = re.match(r"^!D\s+(\d+)", stripped)
            count = int(m.group(1)) if m else -1
            i += 1
            if count >= 0:
                for _ in range(count):
                    if i < n and (m2 := re.match(r"^(\d+) (.*)$", lines[i])):
                        dictionary[int(m2.group(1))] = m2.group(2)
                        i += 1
                    else:
                        break
            else:
                while i < n and (m := re.match(r"^(\d+) (.*)$", lines[i])):
                    dictionary[int(m.group(1))] = m.group(2)
                    i += 1
            continue

        if _is_sigil(stripped, "V"):
            header = stripped[2:].strip()
            i += 1
            book: dict[str, str] = {}
            while i < n and (m := re.match(r"^([a-z]{1,2}) (.*)$", lines[i])):
                book[m.group(1)] = m.group(2)
                i += 1
            codebooks[header] = book
            continue

        if stripped == "!R":
            flush()
            i += 1
            while i < n and lines[i].strip() and not (
                _starts_sigil(lines[i]) or _starts_heading(lines[i])
                or lines[i].startswith(("- ", "> ", "```"))
                or re.match(r"^\d+\s", lines[i])
            ):
                # Genuine boilerplate with one of these shapes arrives escaped
                # ("!- x"), which matches none of them, so this cannot truncate
                # real content -- but an unescaped list/quote/code block that
                # merely *follows* the boilerplate must not be swallowed.
                text = _unescape(lines[i].strip())
                boilerplate.append(text)
                # Declared once but true of the whole document, so it is real
                # content and must come back as content on the way out.
                doc.add(Para(text))
                i += 1
            continue

        if _is_sigil(stripped, "T"):
            flush()
            m = re.match(r"^!T\s+(\d+)(?:\s+(.*))?$", stripped)
            nrows = int(m.group(1)) if m else 0
            caption = (m.group(2) or "").strip() if m else ""
            i += 1

            constants: list[tuple[str, str]] = []
            if i < n and _is_sigil(lines[i].strip(), "F"):
                for tok in _split(lines[i][3:], " "):
                    if "=" in tok:
                        k, _, v = tok.partition("=")
                        constants.append((k, _unquote(v)))
                i += 1

            cols: list[str] = []
            sep = " "
            if i < n and _is_sigil(lines[i].strip(), "C"):
                rest = lines[i][2:]
                sep = "\t" if "\t" in rest else " "
                cols = [_unquote(c) for c in _split(rest.lstrip(" \t"), sep)]
                i += 1

            rows: list[list[str]] = []
            prev: list[str] | None = None
            for _ in range(nrows):
                if i >= n:
                    break
                raw = [_unquote(c) for c in _split(lines[i], sep)]
                raw = [(prev[j] if (c == "^" and prev and j < len(prev)) else c)
                       for j, c in enumerate(raw)]
                rows.append(raw)
                prev = raw
                i += 1

            # Restore hoisted units and constant columns.
            out_cols, marks = [], []
            for c in cols:
                if um := _UNIT_COL.match(c):
                    out_cols.append(um.group(1)); marks.append(um.group(2))
                else:
                    out_cols.append(c); marks.append("")
            for r in rows:
                for j, mk in enumerate(marks):
                    if mk and j < len(r) and r[j]:
                        r[j] = (mk + r[j]) if mk != "%" else (r[j] + "%")
            for k, v in constants:
                out_cols.append(k)
                for r in rows:
                    r.append(v)

            # A coded column stores one-letter codes; without this the table
            # comes back full of "a"/"g" placeholders. Content recall cannot
            # see the difference because the values survive in the codebook.
            for ci, cname in enumerate(out_cols):
                if bk := codebooks.get(cname):
                    for r in rows:
                        if ci < len(r) and r[ci] in bk:
                            r[ci] = bk[r[ci]]

            doc.add(Table(out_cols, rows, caption=expand(caption)))
            continue

        if _is_sigil(stripped, "K"):
            flush()
            caption = stripped[2:].strip()
            i += 1
            pairs = []
            while i < n and lines[i].strip() and not (
                _starts_sigil(lines[i]) or _starts_heading(lines[i])
                or lines[i].startswith("- ")
            ):
                k, sepc, v = _unescape(lines[i].strip()).partition(":")
                if not sepc:
                    break
                pairs.append((expand(k.strip()), expand(v.strip())))
                i += 1
            doc.add(KV(pairs, caption))
            continue

        if _is_sigil(stripped, "G"):
            flush(); doc.add(Figure(expand(stripped[3:]))); i += 1; continue

        if _is_sigil(stripped, "P"):
            flush(); doc.add(PageMark(_int(stripped[3:]))); i += 1; continue
        if _is_sigil(stripped, "E"):
            flush()
            parts = stripped[3:].split(" ", 4)
            doc.add(Elision(parts[0], parts[1] if len(parts) > 1 else "index",
                            int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0,
                            parts[4] if len(parts) > 4 else "",
                            int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else 0))
            i += 1; continue

        if stripped.startswith("```"):
            flush()
            lang = stripped[3:].strip(); i += 1
            buf = []
            while i < n and not lines[i].startswith("```"):
                buf.append(lines[i]); i += 1
            doc.add(Code("\n".join(buf), lang)); i += 1
            continue

        if m := _H.match(stripped):
            flush()
            lvl, txt = len(m.group(1)), expand(m.group(2))
            if lvl == 1 and not doc.title and not doc.blocks:
                doc.title = txt
            else:
                doc.add(Heading(lvl, txt))
            i += 1
            continue

        if stripped.startswith("- "):
            items.append(expand(stripped[2:])); i += 1; continue
        if m := re.match(r"^(\d+) (.*)$", stripped):
            if not items:
                ordered = True
            items.append(expand(m.group(2))); i += 1; continue
        if stripped.startswith("> "):
            flush(); doc.add(Quote(expand(stripped[2:]))); i += 1; continue

        flush()
        doc.add(Para(expand(_unescape(stripped))))
        i += 1

    flush()
    doc.meta["boilerplate"] = boilerplate
    doc.meta["dictionary"] = dictionary
    return doc
