"""Phase 10: automatic representation selection.

Chooses among Markdown / Hybrid / Skeleton by MEASURING each candidate on the
actual document rather than guessing from heuristics. Because render_hybrid's
floor is enforced upstream, the decision is simple and honest:

    encoded_tokens = min(markdown_tokens, hybrid_tokens)   # floor guaranteed
    skeleton enters only as an explicit navigation request (it is a lossy
    retrieval format, not a compression format -- see Phase 11 caveats)

The returned dict follows the mission's optimize_context contract:
    representation / original_tokens / encoded_tokens /
    estimated_savings / risk / reason
"""

from __future__ import annotations

from copy import deepcopy

from .columnar import encode_columns
from .emit import render_hybrid, render_markdown, render_skeleton
from .ir import Doc, Table
from .tokens import count


def analyze(doc: Doc) -> dict:
    """Cheap structural signals (no rendering) useful for logging/debugging."""
    tables = [b for b in doc.blocks if isinstance(b, Table)]
    rows = sum(len(t.rows) for t in tables)
    cells = sum(len(t.rows) * len(t.cols) for t in tables)
    paras = sum(len(b.text) for b in doc.blocks if hasattr(b, "text"))
    return {
        "blocks": len(doc.blocks),
        "tables": len(tables),
        "table_rows": rows,
        "table_cells": cells,
        "prose_chars": paras,
    }


def select_representation(
    doc: Doc,
    allow_skeleton: bool = False,
    objective: str = "balanced",
) -> dict:
    """Measure Markdown / Hybrid (and optionally Skeleton) on this exact
    document and pick per the objective.

    objective:
      "balanced" | "accuracy_per_token" -- hybrid's floor makes it dominate
      markdown token-wise while keeping prose native, so ties resolve to
      plain Markdown (native title semantics, zero surprise).
      "navigation" additionally permits the skeleton, which drops document
      bodies entirely -- only meaningful for retrieval-style agent flows.
    """
    if objective not in ("balanced", "accuracy_per_token", "navigation"):
        raise ValueError(f"unknown objective: {objective!r}")

    md_txt = render_markdown(doc)                     # read-only baseline
    c_md = count(md_txt)

    work = deepcopy(doc)
    books = encode_columns(work)
    hyb_txt = render_hybrid(work, codebooks=books)
    c_hyb = count(hyb_txt)

    skel_txt = render_skeleton(deepcopy(doc))
    c_skel = count(skel_txt)

    breakdown = {"markdown": c_md, "hybrid": c_hyb, "skeleton": c_skel}
    sig = analyze(doc)

    # ---- navigation objective: skeleton allowed to win outright ----------
    if objective == "navigation" and allow_skeleton and c_skel < min(c_hyb, c_md):
        savings = round(100 * (1 - c_skel / max(c_md, 1)), 1)
        return {
            "representation": "skeleton",
            "original_tokens": c_md,
            "encoded_tokens": c_skel,
            "estimated_savings_pct": savings,
            "risk": "high -- bodies dropped; expand sections before answering",
            "reason": (f"navigation mode: outline is {savings}% of Markdown "
                       f"({c_skel} vs {c_md} tokens); expansion required "
                       f"for content questions"),
            "breakdown": breakdown,
            "signals": sig,
        }

    # ---- balanced / accuracy_per_token -----------------------------------
    if c_hyb < c_md:
        representation, encoded = "hybrid", c_hyb
        reason = (f"per-block arbitration saved {c_md - c_hyb} tokens "
                  f"({100 * (c_md - c_hyb) / max(c_md, 1):.1f}%) over "
                  f"Markdown; floor enforced")
        risk = "low"
    else:
        representation, encoded = "markdown", c_md
        reason = ("dense forms could not beat Markdown on this document; "
                  "native Markdown returned unchanged")
        risk = "none"

    savings_pct = round(100 * (1 - encoded / max(c_md, 1)), 1)
    return {
        "representation": representation,
        "original_tokens": c_md,
        "encoded_tokens": encoded,
        "estimated_savings_pct": savings_pct,
        "risk": risk,
        "reason": reason,
        "breakdown": breakdown,
        "signals": sig,
    }


# Mission §20 convenience alias
def optimize_context(doc: Doc, model: str | None = None,
                     objective: str = "balanced",
                     allow_skeleton: bool = False) -> dict:
    return select_representation(doc, allow_skeleton=allow_skeleton,
                                 objective=objective)