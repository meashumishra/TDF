"""PDF reader built on PyMuPDF.

Headings are inferred from font size relative to the document's modal body size,
which is the standard cheap heuristic and good enough for the format comparison
we care about here. Tables use PyMuPDF's built-in finder.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from ..ir import Doc, Figure, Heading, PageMark, Para, Table
from .pdf_tables import find_borderless_tables


def _overlaps(a: tuple, b: tuple) -> bool:
    """True if two bboxes intersect at all."""
    return not (a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1])


def read_pdf(path: str | Path, max_pages: int | None = None) -> Doc:
    import pymupdf as fitz

    pdf = fitz.open(str(path))
    doc = Doc(source=str(path), title=(pdf.metadata or {}).get("title") or Path(path).stem)

    sizes: Counter[float] = Counter()
    pages = list(pdf)[: max_pages or len(pdf)]
    for page in pages:
        for blk in page.get_text("dict")["blocks"]:
            for line in blk.get("lines", []):
                for span in line.get("spans", []):
                    if span["text"].strip():
                        sizes[round(span["size"], 1)] += len(span["text"])
    body_size = sizes.most_common(1)[0][0] if sizes else 10.0

    def level_for(size: float) -> int | None:
        ratio = size / body_size
        if ratio >= 1.6:
            return 1
        if ratio >= 1.35:
            return 2
        if ratio >= 1.15:
            return 3
        return None

    for pno, page in enumerate(pages, 1):
        doc.add(PageMark(pno))

        table_rects = []
        try:
            found = page.find_tables()
            for tbl in found.tables:
                grid = [["" if c is None else str(c).strip().replace("\n", " ") for c in row]
                        for row in tbl.extract()]
                grid = [g for g in grid if any(g)]
                if len(grid) >= 2 and len(grid[0]) >= 2:
                    table_rects.append(tbl.bbox)
                    doc.add(Table(grid[0], grid[1:]))
        except Exception:
            pass

        # PyMuPDF's finder needs ruling lines, so borderless (whitespace-aligned)
        # tables come back empty. Fall back to alignment-based detection for the
        # regions it did not already claim.
        try:
            for grid, bbox in find_borderless_tables(page):
                if any(_overlaps(bbox, r) for r in table_rects):
                    continue
                table_rects.append(bbox)
                doc.add(Table(grid[0], grid[1:]))
        except Exception:
            pass

        def in_table(bbox) -> bool:
            x0, y0, x1, y1 = bbox
            for tx0, ty0, tx1, ty1 in table_rects:
                if x0 >= tx0 - 2 and y0 >= ty0 - 2 and x1 <= tx1 + 2 and y1 <= ty1 + 2:
                    return True
            return False

        for blk in sorted(page.get_text("dict")["blocks"], key=lambda b: (b["bbox"][1], b["bbox"][0])):
            if blk.get("type") == 1:
                continue
            if in_table(blk["bbox"]):
                continue
            texts, span_sizes = [], []
            for line in blk.get("lines", []):
                parts = [s["text"] for s in line.get("spans", []) if s["text"].strip()]
                if parts:
                    texts.append(" ".join(parts))
                    span_sizes += [s["size"] for s in line.get("spans", []) if s["text"].strip()]
            text = " ".join(" ".join(texts).split())
            if not text:
                continue
            avg = sum(span_sizes) / len(span_sizes)
            lvl = level_for(avg)
            if lvl and len(text) < 160:
                doc.add(Heading(lvl, text))
            else:
                doc.add(Para(text))

        for img in page.get_images(full=True):
            doc.add(Figure(f"image on page {pno}"))
            break

    pdf.close()
    return doc
