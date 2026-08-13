"""Borderless-table detection for PDFs.

PyMuPDF's default ``find_tables`` strategy relies on ruling lines, so it returns
nothing for whitespace-aligned tables -- which is how most financial and report
PDFs are actually typeset. Its ``strategy="text"`` fallback is not a safe
substitute: it shreds ordinary prose into fake cells (splitting words mid-token,
e.g. "CORPOR" / "ATION").

The discriminator used here is **column alignment**. Table rows share vertical
anchors: cell left edges line up down the page. Prose does not -- its inter-word
gaps land wherever justification happens to put them. So we cluster words into
visual rows, split each row into cells at wide gaps, and only accept a run of
rows whose cell left-edges repeatedly agree.
"""

from __future__ import annotations

from statistics import median

Word = tuple[float, float, float, float, str]

ROW_TOL = 3.0        # y-centres within this are the same visual row
MIN_GAP = 6.0        # absolute pt gap that can start a new cell
GAP_RATIO = 2.5      # ...or this multiple of the row's median character width
COL_TOL = 6.0        # x-anchors within this are the same column
MIN_ROWS = 3         # a table needs at least this many aligned rows
MIN_COLS = 2
MIN_ALIGN = 0.75     # fraction of rows that must match the dominant arity


def _rows_of_words(words: list[tuple]) -> list[list[Word]]:
    """Cluster words into visual rows by y-centre."""
    items: list[Word] = [(w[0], w[1], w[2], w[3], w[4]) for w in words if w[4].strip()]
    items.sort(key=lambda w: ((w[1] + w[3]) / 2, w[0]))
    rows: list[list[Word]] = []
    for w in items:
        yc = (w[1] + w[3]) / 2
        if rows:
            prev = rows[-1][0]
            if abs(yc - (prev[1] + prev[3]) / 2) <= ROW_TOL:
                rows[-1].append(w)
                continue
        rows.append([w])
    for r in rows:
        r.sort(key=lambda w: w[0])
    return rows


def _split_cells(row: list[Word]) -> list[tuple[float, str]]:
    """Split one visual row into (x_start, text) cells at unusually wide gaps.

    The threshold is derived from character width rather than from the row's own
    gaps: in a table whose cells are single words *every* gap is wide, so a
    gap-relative baseline degenerates and nothing ever splits.
    """
    if len(row) == 1:
        return [(row[0][0], row[0][4])]
    char_w = median([(w[2] - w[0]) / max(len(w[4]), 1) for w in row]) or 4.0
    threshold = max(MIN_GAP, char_w * GAP_RATIO)
    gaps = [row[i + 1][0] - row[i][2] for i in range(len(row) - 1)]

    cells: list[tuple[float, list[str]]] = [(row[0][0], [row[0][4]])]
    for i, gap in enumerate(gaps):
        nxt = row[i + 1]
        if gap >= threshold:
            cells.append((nxt[0], [nxt[4]]))
        else:
            cells[-1][1].append(nxt[4])
    return [(x, " ".join(parts)) for x, parts in cells]


def _anchors(rows: list[list[tuple[float, str]]]) -> list[float]:
    """Cluster cell x-starts across rows into shared column anchors.

    Centered or right-aligned columns make x-starts vary with cell width, which
    can split one true column into several sparse anchors. The dominant row
    arity tells us how many columns there really are, so any surplus anchors --
    always the least-used ones -- get merged into their nearest neighbour.
    """
    xs = sorted(x for r in rows for x, _ in r)
    if not xs:
        return []
    cols: list[list[float]] = [[xs[0]]]
    for x in xs[1:]:
        if x - cols[-1][-1] <= COL_TOL:
            cols[-1].append(x)
        else:
            cols.append([x])

    counts = [len(r) for r in rows]
    target = max(set(counts), key=counts.count)
    while len(cols) > target >= MIN_COLS:
        weakest = min(range(len(cols)), key=lambda i: len(cols[i]))
        neighbours = [i for i in (weakest - 1, weakest + 1) if 0 <= i < len(cols)]
        if not neighbours:
            break
        centre = sum(cols[weakest]) / len(cols[weakest])
        into = min(neighbours, key=lambda i: abs(sum(cols[i]) / len(cols[i]) - centre))
        cols[into].extend(cols.pop(weakest))
    return [sum(c) / len(c) for c in cols]


def _looks_tabular(cell_rows: list[list[tuple[float, str]]]) -> bool:
    """Reject prose. Requires consistent arity, shared anchors and short cells."""
    if len(cell_rows) < MIN_ROWS:
        return False
    counts = [len(r) for r in cell_rows]
    dominant = max(set(counts), key=counts.count)
    if dominant < MIN_COLS:
        return False
    if sum(1 for c in counts if c == dominant) / len(counts) < MIN_ALIGN:
        return False

    anchors = _anchors(cell_rows)
    if len(anchors) < MIN_COLS:
        return False
    # every anchor must be used by most rows -- this is what prose fails
    hits = 0
    for a in anchors:
        used = sum(1 for r in cell_rows if any(abs(x - a) <= COL_TOL for x, _ in r))
        if used / len(cell_rows) >= MIN_ALIGN:
            hits += 1
    if hits < MIN_COLS:
        return False
    # table cells are short; sentences are not
    texts = [t for r in cell_rows for _, t in r]
    if median([len(t) for t in texts]) > 40:
        return False
    return sum(1 for t in texts if len(t.split()) > 8) / max(len(texts), 1) < 0.15


def _grid(cell_rows: list[list[tuple[float, str]]], anchors: list[float]) -> list[list[str]]:
    out: list[list[str]] = []
    for r in cell_rows:
        line = [""] * len(anchors)
        for x, t in r:
            idx = min(range(len(anchors)), key=lambda i: abs(anchors[i] - x))
            line[idx] = (line[idx] + " " + t).strip() if line[idx] else t
        out.append(line)
    return out


def find_borderless_tables(page) -> list[tuple[list[list[str]], tuple]]:
    """Return [(grid, bbox)] for whitespace-aligned tables on ``page``."""
    rows = _rows_of_words(page.get_text("words"))
    cell_rows = [_split_cells(r) for r in rows]
    y_of = [(min(w[1] for w in r), max(w[3] for w in r)) for r in rows]

    results: list[tuple[list[list[str]], tuple]] = []
    i = 0
    while i < len(cell_rows):
        if len(cell_rows[i]) < MIN_COLS:
            i += 1
            continue
        j = i
        while j + 1 < len(cell_rows) and len(cell_rows[j + 1]) >= MIN_COLS:
            j += 1
        run = cell_rows[i:j + 1]
        if _looks_tabular(run):
            anchors = _anchors(run)
            grid = [r for r in _grid(run, anchors) if any(c.strip() for c in r)]
            if len(grid) >= MIN_ROWS:
                x0 = min(w[0] for r in rows[i:j + 1] for w in r)
                x1 = max(w[2] for r in rows[i:j + 1] for w in r)
                bbox = (x0, y_of[i][0], x1, y_of[j][1])
                results.append((grid, bbox))
        i = j + 1
    return results
