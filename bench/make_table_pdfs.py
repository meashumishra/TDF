"""Generate PDFs that specifically exercise table detection.

- borderless_report.pdf : whitespace-aligned table, NO ruling lines (the hard case)
- ruled_report.pdf      : same data WITH ruling lines (the easy case)
- prose_only.pdf        : no table at all (false-positive guard)
"""

from __future__ import annotations

from pathlib import Path

import pymupdf as fitz

OUT = Path(__file__).resolve().parent.parent / "samples_tables"

HEADER = ["region", "product", "units", "revenue", "status"]
ROWS = [
    ["EMEA", "Cloud", "412", "1284000", "closed"],
    ["EMEA", "Services", "88", "312000", "open"],
    ["APAC", "Cloud", "366", "1109500", "closed"],
    ["APAC", "Services", "71", "204750", "open"],
    ["AMER", "Cloud", "590", "2044100", "closed"],
    ["AMER", "Services", "133", "498300", "pending"],
    ["LATAM", "Cloud", "204", "612900", "open"],
    ["LATAM", "Services", "45", "133400", "closed"],
]
XS = [60, 150, 260, 330, 430]
PROSE = ("The quarterly operating review covers revenue attainment, pipeline coverage and "
         "regional performance. Management believes the results reflect continued execution "
         "against the operating plan established at the start of the fiscal year. ")


def _table(page, y0: int, ruled: bool) -> int:
    y = y0
    for i, h in enumerate(HEADER):
        page.insert_text((XS[i], y), h, fontsize=9)
    y += 18
    for row in ROWS:
        for i, cell in enumerate(row):
            page.insert_text((XS[i], y), cell, fontsize=9)
        y += 16
    if ruled:
        top, bottom = y0 - 10, y - 10
        for i in range(len(XS) + 1):
            x = XS[i] - 6 if i < len(XS) else 520
            page.draw_line(fitz.Point(x, top), fitz.Point(x, bottom))
        yy = top
        while yy <= bottom + 1:
            page.draw_line(fitz.Point(XS[0] - 6, yy), fitz.Point(520, yy))
            yy += 16 if yy > y0 - 10 else 18
    return y


def _build(name: str, ruled: bool, with_table: bool) -> Path:
    doc = fitz.open()
    for pno in (1, 2):
        page = doc.new_page()
        page.insert_text((60, 40), "ACME CORPORATION - CONFIDENTIAL", fontsize=8)
        page.insert_text((60, 80), f"Section {pno}: Regional Performance", fontsize=17)
        page.insert_textbox(fitz.Rect(60, 100, 540, 170), PROSE + f"Part {pno}.", fontsize=10)
        if with_table:
            page.insert_text((60, 200), "Table 1: Bookings by region", fontsize=10)
            end = _table(page, 225, ruled)
        else:
            end = 200
        page.insert_textbox(fitz.Rect(60, end + 20, 540, end + 90),
                            PROSE + f"Closing commentary {pno}.", fontsize=10)
        page.insert_text((60, 760), "ACME CORPORATION - CONFIDENTIAL", fontsize=8)
    p = OUT / name
    doc.save(p)
    doc.close()
    return p


def main() -> None:
    OUT.mkdir(exist_ok=True)
    for p in (_build("borderless_report.pdf", ruled=False, with_table=True),
              _build("ruled_report.pdf", ruled=True, with_table=True),
              _build("prose_only.pdf", ruled=False, with_table=False)):
        print("wrote", p)


if __name__ == "__main__":
    main()
