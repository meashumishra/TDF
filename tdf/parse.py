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
_FENCE_OPEN = re.compile(r"^(`{3,})(.*)$")


def _unescape_caret_cell(v: str) -> str:
    """Exact inverse of emit._escape_caret_cell: drop one trailing caret from
    any all-caret cell of length >= 2. A bare single '^' never reaches this
    function -- it is caught by the back-reference check first."""
    return v[:-1] if len(v) >= 2 and set(v) == {"^"} else v


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


_SIGILS = "DRTFCKGPEVH"


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

        if _is_sigil(stripped, "H"):
            # Distinct from "#" (Heading) on purpose -- see emit.py's
            # comment on this sigil for why reusing "# " for the title made
            # a titleless doc's leading H1 indistinguishable from an actual
            # title on the wire (the independent audit's BUG-5).
            doc.title = expand(stripped[2:].strip())
            i += 1
            continue

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

            # Each entry is (original_index, key, value) -- the index is what
            # lets the merge below reinsert a constant column where it
            # actually was, instead of always appending it after every
            # surviving column (see the independent audit's BUG-1).
            constants: list[tuple[int, str, str]] = []
            f_line = None
            if i < n and _is_sigil(lines[i].strip(), "F"):
                f_line = lines[i]
                for tok in _split(lines[i][3:], " "):
                    if "=" in tok:
                        idx_key, _, v = tok.partition("=")
                        idx_str, sep_found, k = idx_key.partition(":")
                        if sep_found and idx_str.isdigit():
                            constants.append((int(idx_str), k, v))
                i += 1

            cols: list[str] = []
            sep = " "
            c_line = None
            if i < n and _is_sigil(lines[i].strip(), "C"):
                c_line = lines[i]
                rest = lines[i][2:]
                sep = "\t" if "\t" in rest else " "
                # Exactly one separator character sits between "!C" and the
                # first column value (see emit._tdf_table) -- .lstrip(" \t")
                # would greedily eat into a first column name that itself
                # starts with whitespace, e.g. " leading space".
                if rest[:1] in (" ", "\t"):
                    rest = rest[1:]
                cols = _split(rest, sep)
                i += 1

            rows: list[list[str]] = []
            if c_line is None:
                # No data grid was emitted at all -- either every column was
                # constant (see emit._tdf_table's early return, BUG-2) or the
                # table is genuinely columnless. "!T n" already declared the
                # row count; there are no body lines to read, and treating a
                # blank/absent line as "one empty-string column" is exactly
                # the ambiguity that produced the phantom column.
                rows = [[] for _ in range(nrows)]
            else:
                prev: list[str] | None = None
                added = 0
                while added < nrows:
                    if i >= n:
                        break
                    # Skip periodic headers injected for context
                    if (c_line is not None and lines[i] == c_line) or (f_line is not None and lines[i] == f_line):
                        i += 1
                        continue

                    # The marker check runs on the *raw* split cell, before
                    # unquoting/unescaping: the emitter only ever produces a bare
                    # '^' for a genuine back-reference, since a literal all-caret
                    # value is always lengthened by one caret first (see
                    # emit._escape_caret_cell). So a bare '^' here is unambiguous.
                    split_cells = _split(lines[i], sep)
                    added += 1
                    row = []
                    for j, c in enumerate(split_cells):
                        if c == "^" and prev and j < len(prev):
                            row.append(prev[j])
                        else:
                            row.append(_unescape_caret_cell(c))
                    rows.append(row)
                    prev = row
                    i += 1

            # Restore hoisted units.
            surv_cols, marks = [], []
            for c in cols:
                if um := _UNIT_COL.match(c):
                    surv_cols.append(um.group(1)); marks.append(um.group(2))
                else:
                    surv_cols.append(c); marks.append("")
            for r in rows:
                for j, mk in enumerate(marks):
                    if mk and j < len(r) and r[j]:
                        if mk == "%":
                            r[j] = r[j] + "%"
                        elif r[j].startswith("-"):
                            # normalize_cell puts the sign before the currency
                            # symbol ("-$100"), not after it -- restoring the
                            # mark at position 0 unconditionally would instead
                            # produce "$-100", changing the literal formatting
                            # of every negative value in a hoisted currency
                            # column on a round trip (see hoist_units' _UNIT_RE
                            # comment for why the emit side already accounts
                            # for this).
                            r[j] = "-" + mk + r[j][1:]
                        else:
                            r[j] = mk + r[j]

            # Reinsert constant columns at their original index by merging
            # them with the surviving columns positionally, rather than
            # appending every constant after all surviving columns (which
            # silently reordered the whole table -- BUG-1).
            if constants:
                total_width = len(surv_cols) + len(constants)
                by_idx = {idx: (k, v) for idx, k, v in constants}
                # Guards against malformed/adversarial "!F" content (duplicate
                # or out-of-range indices) -- degrade to the old
                # append-at-end behaviour rather than crash or drop data.
                valid = len(by_idx) == len(constants) and all(0 <= idx < total_width for idx in by_idx)
                if valid:
                    out_cols = []
                    surv_iter = iter(surv_cols)
                    for pos in range(total_width):
                        out_cols.append(by_idx[pos][0] if pos in by_idx else next(surv_iter))
                    new_rows = []
                    for r in rows:
                        row_iter = iter(r)
                        new_rows.append([
                            by_idx[pos][1] if pos in by_idx else next(row_iter, "")
                            for pos in range(total_width)
                        ])
                    rows = new_rows
                else:
                    out_cols = surv_cols + [k for _, k, v in constants]
                    for r in rows:
                        for _, k, v in constants:
                            r.append(v)
            else:
                out_cols = surv_cols

            # A coded column stores one-letter codes; without this the table
            # comes back full of "a"/"g" placeholders. Content recall cannot
            # see the difference because the values survive in the codebook.
            for ci, cname in enumerate(out_cols):
                if bk := codebooks.get(cname):
                    for r in rows:
                        if ci < len(r) and r[ci] in bk:
                            r[ci] = bk[r[ci]]

            doc.add(Table(out_cols, rows, caption=expand(caption)))
            codebooks.clear()
            continue

        if _is_sigil(stripped, "K"):
            flush()
            caption = stripped[2:].strip()
            i += 1
            pairs = []
            while i < n and lines[i].strip() and not (
                _starts_sigil(lines[i]) or _starts_heading(lines[i])
                or lines[i].startswith(("- ", "> ", "```"))
                or re.match(r"^\d+\s", lines[i])
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

        if fm := _FENCE_OPEN.match(stripped):
            flush()
            fence, lang = fm.group(1), fm.group(2).strip()
            i += 1
            buf = []
            # The closing fence must be at least as long as the opening one
            # (CommonMark's rule) -- the emitter always picks a fence longer
            # than any backtick run in the content, so a shorter or equal-run
            # of backticks *inside* the code can never be mistaken for it.
            close = re.compile(r"^`{" + str(len(fence)) + r",}\s*$")
            while i < n and not close.match(lines[i]):
                buf.append(lines[i]); i += 1
            doc.add(Code("\n".join(buf), lang)); i += 1
            continue

        if m := _H.match(stripped):
            flush()
            lvl, txt = len(m.group(1)), expand(m.group(2))
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
