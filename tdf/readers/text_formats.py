"""Markdown / HTML / CSV / plain-text readers."""

from __future__ import annotations

import csv as _csv
import io
import re
from pathlib import Path

from ..ir import Code, Doc, Figure, Heading, ListBlock, Para, Quote, Table

_H = re.compile(r"^(#{1,6})\s+(.*)$")
_UL = re.compile(r"^\s*[-*+]\s+(.*)$")
_OL = re.compile(r"^\s*(\d+)[.)]\s+(.*)$")
_FENCE = re.compile(r"^\s*```(\w*)\s*$")
_IMG = re.compile(r"^!\[([^\]]*)\]\(([^)]*)\)\s*$")
_ROW = re.compile(r"^\s*\|(.*)\|\s*$")
_SEPROW = re.compile(r"^\s*\|[\s:|-]+\|\s*$")


_UNESCAPED_PIPE = re.compile(r"(?<!\\)\|")


def _split_row(line: str) -> list[str]:
    inner = _ROW.match(line).group(1)
    # Split on unescaped '|' only. A naive str.split("|") followed by
    # unescaping runs too late -- "a\|b" (one cell, GFM's escaped-pipe
    # syntax for a literal '|') was already split into "a\" and "b" before
    # any unescaping happened, shifting the whole row's column count.
    cells = _UNESCAPED_PIPE.split(inner)
    return [c.strip().replace("<br>", " ").replace("\\|", "|") for c in cells]


def read_markdown(path: str | Path, text: str | None = None) -> Doc:
    src = text if text is not None else Path(path).read_text(encoding="utf-8", errors="replace")
    doc = Doc(source=str(path))
    lines = src.splitlines()
    i, n = 0, len(lines)
    para: list[str] = []
    items: list[str] = []
    ordered = False

    def flush_para():
        nonlocal para
        if para:
            doc.add(Para(" ".join(para).strip()))
            para = []

    def flush_items():
        nonlocal items, ordered
        if items:
            doc.add(ListBlock(items, ordered))
            items, ordered = [], False

    while i < n:
        line = lines[i]

        if m := _FENCE.match(line):
            flush_para(); flush_items()
            lang, i = m.group(1), i + 1
            buf = []
            while i < n and not _FENCE.match(lines[i]):
                buf.append(lines[i]); i += 1
            doc.add(Code("\n".join(buf), lang)); i += 1
            continue

        if _ROW.match(line) and i + 1 < n and _SEPROW.match(lines[i + 1]):
            flush_para(); flush_items()
            cols = _split_row(line)
            i += 2
            rows = []
            while i < n and _ROW.match(lines[i]):
                rows.append(_split_row(lines[i])); i += 1
            doc.add(Table(cols, rows))
            continue

        if m := _H.match(line):
            flush_para(); flush_items()
            doc.add(Heading(len(m.group(1)), m.group(2).strip())); i += 1
            continue

        if m := _IMG.match(line.strip()):
            flush_para(); flush_items()
            doc.add(Figure(m.group(1) or "image")); i += 1
            continue

        if m := _UL.match(line):
            flush_para()
            items.append(m.group(1).strip()); i += 1
            continue

        if m := _OL.match(line):
            flush_para()
            if not items:
                ordered = True
            items.append(m.group(2).strip()); i += 1
            continue

        if line.startswith(">"):
            flush_para(); flush_items()
            doc.add(Quote(line.lstrip("> ").strip())); i += 1
            continue

        if not line.strip():
            flush_para(); flush_items(); i += 1
            continue

        flush_items()
        para.append(line.strip()); i += 1

    flush_para(); flush_items()
    if doc.blocks and isinstance(doc.blocks[0], Heading) and doc.blocks[0].level == 1:
        doc.title = doc.blocks.pop(0).text
    return doc


def read_csv(path: str | Path) -> Doc:
    doc = Doc(source=str(path), title=Path(path).stem)
    with open(path, newline="", encoding="utf-8", errors="replace") as fh:
        sample = fh.read(8192); fh.seek(0)
        try:
            dialect = _csv.Sniffer().sniff(sample)
        except _csv.Error:
            dialect = _csv.excel
        rows = list(_csv.reader(fh, dialect))
    if not rows:
        return doc
    doc.add(Table(rows[0], rows[1:], caption=Path(path).stem))
    return doc


def read_html(path: str | Path, text: str | None = None) -> Doc:
    from bs4 import BeautifulSoup

    src = text if text is not None else Path(path).read_text(encoding="utf-8", errors="replace")
    soup = BeautifulSoup(src, "lxml")
    for bad in soup(["script", "style", "noscript", "svg"]):
        bad.decompose()

    doc = Doc(source=str(path))
    if soup.title and soup.title.string:
        doc.title = soup.title.string.strip()
    body = soup.body or soup

    for el in body.find_all(
        ["h1", "h2", "h3", "h4", "h5", "h6", "p", "ul", "ol", "table", "pre", "blockquote", "img"]
    ):
        if el.find_parent("table") is not None and el.name != "table":
            continue
        if el.name.startswith("h") and len(el.name) == 2 and el.name[1].isdigit():
            if t := el.get_text(" ", strip=True):
                doc.add(Heading(int(el.name[1]), t))
        elif el.name == "p":
            if t := el.get_text(" ", strip=True):
                doc.add(Para(t))
        elif el.name in ("ul", "ol"):
            its = [li.get_text(" ", strip=True) for li in el.find_all("li", recursive=False)]
            if any(its):
                doc.add(ListBlock(its, el.name == "ol"))
        elif el.name == "blockquote":
            if t := el.get_text(" ", strip=True):
                doc.add(Quote(t))
        elif el.name == "pre":
            doc.add(Code(el.get_text()))
        elif el.name == "img":
            if alt := (el.get("alt") or "").strip():
                doc.add(Figure(alt))
        elif el.name == "table":
            trs = el.find_all("tr")
            if not trs:
                continue
            # Keep each <tr> paired with its extracted row while filtering
            # out blank ones (spacer rows are common in real HTML tables) --
            # filtering `grid` alone and then still indexing the header
            # check against the *unfiltered* trs[0] desyncs the two lists
            # the moment the true first row is blank, silently swapping the
            # real header into the data rows and fabricating synthetic
            # column names instead.
            pairs = [(tr, [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])])
                     for tr in trs]
            pairs = [(tr, g) for tr, g in pairs if any(g)]
            if not pairs:
                continue
            first_tr, first_row = pairs[0]
            grid = [g for _, g in pairs]
            head = first_row if first_tr.find("th") else [f"c{i+1}" for i in range(len(first_row))]
            data = grid[1:] if first_tr.find("th") else grid
            cap = el.find("caption")
            doc.add(Table(head, data, caption=cap.get_text(" ", strip=True) if cap else ""))
    return doc


def read_text(path: str | Path) -> Doc:
    doc = Doc(source=str(path), title=Path(path).stem)
    raw = Path(path).read_text(encoding="utf-8", errors="replace")
    for chunk in re.split(r"\n\s*\n", raw):
        if chunk.strip():
            doc.add(Para(" ".join(chunk.split())))
    return doc
