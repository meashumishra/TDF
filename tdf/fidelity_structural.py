"""Structural fidelity: graded comparison of two IRs, block by block.

Phase-3 replacement for using ``compare()`` (bag-of-words recall) as primary
evidence. The bag metric answers "is any *word* missing?"; this module answers
the questions that actually matter for a *structural* format:

    did the block sequence survive?      -> ordering_accuracy
    did every table keep its grid?       -> table_cell_accuracy, col/row counts
    is every heading still a heading,
    at the same level, with same text?   -> heading_accuracy
    is code byte-exact (indentation!)?   -> code_exact_accuracy
    ... per aspect, with explicit counts,
    so every rate has a denominator.

``exact_structural_match`` is ``canonicalize(a) == canonicalize(b)`` re-exported
here so callers need one import. All rates are floats in [0, 1] with an
explicit ``*_compared`` count; aspects with no instances report 1.0 alongside
a zero count (nothing could be lost), keeping aggregates honest.
"""

from __future__ import annotations

import hashlib

from .emit import _oneline
from .fidelity import canonicalize
from .ir import Doc


def _h(canonical_block: tuple) -> str:
    return hashlib.sha1(repr(canonical_block).encode()).hexdigest()


def _rate(matches: int, total: int) -> float:
    return 1.0 if total == 0 else matches / total


def _type_name(b) -> str:
    return type(b).__name__


def _aligned_pairs(a_blocks, b_blocks):
    n = min(len(a_blocks), len(b_blocks))
    return list(zip(a_blocks[:n], b_blocks[:n])), a_blocks[n:], b_blocks[n:]


def _type_filtered(pairs, tname):
    return [(a, b) for a, b in pairs if _type_name(a) == tname == _type_name(b)]


def structural_report(original: Doc, restored: Doc) -> dict:
    """Graded structural comparison. See module docstring."""
    a_blocks, b_blocks = original.blocks, restored.blocks
    pairs, a_extra, b_extra = _aligned_pairs(a_blocks, b_blocks)

    # ---- ordering: LCS ratio over canonical block hashes -----------------
    a_hashes = [_h(t) for t in canonicalize(original)[1]]
    b_hashes = [_h(t) for t in canonicalize(restored)[1]]
    la, lb = len(a_hashes), len(b_hashes)
    dp = [[0] * (lb + 1) for _ in range(la + 1)]
    for i in range(1, la + 1):
        for j in range(1, lb + 1):
            dp[i][j] = (dp[i - 1][j - 1] + 1
                        if a_hashes[i - 1] == b_hashes[j - 1]
                        else max(dp[i - 1][j], dp[i][j - 1]))
    lcs = dp[la][lb]

    type_ok = sum(1 for a, b in pairs if _type_name(a) == _type_name(b))

    def aspect(tname, key_fn):
        sel = _type_filtered(pairs, tname)
        ok = sum(1 for a, b in sel if key_fn(a) == key_fn(b))
        return ok, len(sel)

    h_ok, h_n = aspect("Heading", lambda b: (b.level, _oneline(b.text)))
    p_ok, p_n = aspect("Para", lambda b: _oneline(b.text))
    q_ok, q_n = aspect("Quote", lambda b: _oneline(b.text))
    l_ok, l_n = aspect(
        "ListBlock", lambda b: (b.ordered, tuple(_oneline(i) for i in b.items)))
    c_ok, c_n = aspect("Code", lambda b: (b.text, b.lang))
    k_ok, k_n = aspect(
        "KV", lambda b: tuple((_oneline(k), _oneline(v)) for k, v in b.pairs))
    f_ok, f_n = aspect("Figure", lambda b: _oneline(b.desc))
    pm_ok, pm_n = aspect("PageMark", lambda b: b.number)
    e_ok, e_n = aspect("Elision", lambda b: (b.eid, b.kind, b.tokens))

    tables = _type_filtered(pairs, "Table")
    col_ok = cell_ok = cells_total = cap_ok = rowcount_ok = 0
    for ta, tb in tables:
        if (tuple(_oneline(c) for c in ta.cols)
                == tuple(_oneline(c) for c in tb.cols)):
            col_ok += 1
        if len(ta.rows) == len(tb.rows):
            rowcount_ok += 1
        w = max(len(ta.cols), 1)
        ra = [list(r) + [""] * (w - len(r)) for r in ta.rows]
        rb = [list(r) + [""] * (w - len(r)) for r in tb.rows]
        n_rows = max(len(ra), len(rb))
        for ri in range(n_rows):
            av = ra[ri] if ri < len(ra) else [""] * w
            bv = rb[ri] if ri < len(rb) else [""] * w
            for ci in range(w):
                a_cell = _oneline(av[ci]) if ci < len(av) else ""
                b_cell = _oneline(bv[ci]) if ci < len(bv) else ""
                cells_total += 1
                cell_ok += a_cell == b_cell
        cap_ok += _oneline(ta.caption) == _oneline(tb.caption)
    tables_n = len(tables)

    meta_ok = (_oneline(original.title) == _oneline(restored.title))

    return {
        "exact_structural_match":
            canonicalize(original) == canonicalize(restored),
        "block_count_original": len(a_blocks),
        "block_count_restored": len(b_blocks),
        "blocks_dropped_original": len(a_extra),
        "blocks_inserted_restored": len(b_extra),
        "block_type_accuracy": _rate(type_ok, len(pairs)) if pairs else 1.0,
        "ordering_accuracy": _rate(lcs, max(la, lb)),
        "heading_accuracy": _rate(h_ok, h_n),
        "heading_compared": h_n,
        "paragraph_exact_accuracy": _rate(p_ok, p_n),
        "paragraph_compared": p_n,
        "quote_exact_accuracy": _rate(q_ok, q_n),
        "quote_compared": q_n,
        "list_exact_accuracy": _rate(l_ok, l_n),
        "list_compared": l_n,
        "code_exact_accuracy": _rate(c_ok, c_n),
        "code_compared": c_n,
        "kv_pair_accuracy": _rate(k_ok, k_n),
        "kv_compared": k_n,
        "figure_exact_accuracy": _rate(f_ok, f_n),
        "figure_compared": f_n,
        "pagemark_exact_accuracy": _rate(pm_ok, pm_n),
        "pagemark_compared": pm_n,
        "elision_reference_accuracy": _rate(e_ok, e_n),
        "elision_compared": e_n,
        "table_col_structure_accuracy": _rate(col_ok, tables_n),
        "table_row_count_match": _rate(rowcount_ok, tables_n),
        "table_caption_accuracy": _rate(cap_ok, tables_n),
        "table_cell_level_accuracy": _rate(cell_ok, cells_total),
        "table_cells_compared": cells_total,
        "tables_compared": tables_n,
        "metadata_title_accuracy": float(meta_ok),
    }