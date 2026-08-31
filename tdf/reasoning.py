"""Phase 15: reasoning-aware transform reporting (mission section 7).

The Phase 13 audit (validation/reasoning_optimizer_audit.md) found that no
transform in this codebase exposes tokens_before/tokens_after/token_savings/
structural_risk/semantic_risk/reasoning_risk, and that the closest existing
mechanisms -- hand-tuned constants inside individual transforms, and
selector.py's whole-representation choice -- are not equivalent to the
mission's scored, per-transformation objective. This module is the audit's
recommendation #3: an additive reporting layer OVER the existing transforms,
not a replacement for them. Nothing here changes what `tdf convert` or
`render_tdf` emit; it answers "what would this transform cost/risk on this
document" for a caller who wants to inspect that before or after the fact.

Two things this module deliberately does NOT do:

1. It does not decide anything. There is no default λ policy applied
   automatically anywhere in the pipeline -- `score()` takes explicit
   weights so a caller states their own risk tolerance.
2. It does not invent risk numbers where no evidence exists. Where a
   mechanism's accuracy impact has actually been measured (the ablation
   ladder in eval/results/REPORT.md: removing §n/!V/^ each recovers <=0.1pp),
   that number is cited directly. Where a mechanism's risk is a documented
   failure mode rather than a measured accuracy delta (Phase-5's
   row_association loss from caret-eliding a lookup key), the risk is a
   deliberately coarse heuristic (identifier-like column -> high, everything
   else -> low), not a fabricated precision this module has no evidence for.
"""

from __future__ import annotations

import re
from copy import deepcopy
from dataclasses import dataclass

from .ir import Doc, Figure, Heading, KV, ListBlock, Para, Quote, Table
from .optimize import build_dictionary, drop_constant_columns, elide_repeats
from .tokens import count

# Header patterns that make a column look like a row identifier/lookup key,
# independent of position. Column 0 is included unconditionally: it is the
# conventional row anchor even when unnamed, and is exactly what Phase-5's
# failure analysis (reports/FAILURE_ANALYSIS.md) traced the dominant
# row_association accuracy loss to when caret-elided.
_IDENTIFIER_HEADER = re.compile(
    r"(?i)\b(id|key|code|identifier|sku|acct|account)\b|_id$|id$"
)


@dataclass
class TransformReport:
    """One transform's measured cost and heuristic risk on one document (or
    one block within it). Risk fields are 0..1 severity scores, not token
    counts -- see score()'s docstring for how they combine with token_savings."""

    name: str
    tokens_before: int
    tokens_after: int
    token_savings: int
    structural_risk: float
    semantic_risk: float
    reasoning_risk: float
    note: str = ""
    evidence: str = ""


def score(report: TransformReport, lambda1: float = 1.0, lambda2: float = 1.0,
          lambda3: float = 1.0) -> float:
    """Mission section 7's objective:

        score = token_savings - lambda1*structural_risk
                               - lambda2*semantic_risk
                               - lambda3*reasoning_risk

    The mission does not fix the units of the risk terms, so this module
    makes that choice explicit: risk fields are 0..1 severity scores, and
    lambda_i is "token-equivalent cost per unit of risk". With the default
    lambda=1.0, a transform whose reasoning_risk is 0.8 (identifier-column
    caret-elision) is charged 0.8 tokens-equivalent against its savings --
    negligible next to a real token_savings in the hundreds. A caller who
    believes reasoning risk should dominate the decision should pass a much
    larger lambda3 (e.g. proportional to tokens_before), not rely on the
    default.
    """
    return (report.token_savings
            - lambda1 * report.structural_risk
            - lambda2 * report.semantic_risk
            - lambda3 * report.reasoning_risk)


def _looks_like_identifier(col_index: int, header: str) -> bool:
    return col_index == 0 or bool(_IDENTIFIER_HEADER.search(header or ""))


def _text_tokens(doc: Doc) -> int:
    total = 0
    for b in doc.blocks:
        if isinstance(b, (Para, Quote, Heading)):
            total += count(b.text)
        elif isinstance(b, Figure):
            total += count(b.desc)
        elif isinstance(b, ListBlock):
            total += sum(count(i) for i in b.items)
        elif isinstance(b, KV):
            total += sum(count(k) + count(v) for k, v in b.pairs)
    return total


def report_constant_column_factoring(doc: Doc) -> list[TransformReport]:
    """drop_constant_columns is exact by construction (a column must be
    identical across every row to qualify), so both risk fields are zero
    regardless of the document -- there is no case where this transform can
    lose or ambiguate content."""
    reports = []
    for b in doc.blocks:
        if not isinstance(b, Table) or not b.rows:
            continue
        cols_before, rows_before = list(b.cols), [list(r) for r in b.rows]
        tokens_before = (sum(count(c) for c in cols_before)
                         + sum(count(v) for r in rows_before for v in r))
        new_cols, new_rows, constants = drop_constant_columns(cols_before, rows_before)
        if not constants:
            continue
        decl_tokens = sum(count(f"{idx}:{name}={val}") for idx, name, val in constants)
        tokens_after = (sum(count(c) for c in new_cols)
                        + sum(count(v) for r in new_rows for v in r)
                        + decl_tokens)
        reports.append(TransformReport(
            name=f"constant_column_factoring:{b.caption or 'table'}",
            tokens_before=tokens_before, tokens_after=tokens_after,
            token_savings=tokens_before - tokens_after,
            structural_risk=0.0, semantic_risk=0.0, reasoning_risk=0.0,
            note=(f"columns {[name for _, name, _ in constants]} are constant "
                  f"across all {len(rows_before)} rows -- declared once, exact "
                  f"by construction"),
            evidence="optimize.drop_constant_columns requires exact equality; no ablation needed",
        ))
    return reports


def report_caret_elision(doc: Doc) -> list[TransformReport]:
    """elide_repeats is exact/reversible (parse_tdf always reconstructs the
    literal value), so structural_risk and semantic_risk are zero here too.
    reasoning_risk is the heuristic this module actually contributes: HIGH
    when elision fires on an identifier-like column (Phase-5's failure
    mode), LOW otherwise. This is deliberately coarse -- see the module
    docstring -- because no per-column accuracy measurement exists yet;
    tdf_nocaret0 in the eval harness is the mechanism that could eventually
    replace this heuristic with a measured number, but it has zero rows in
    every run so far (see validation/reasoning_optimizer_audit.md #2)."""
    reports = []
    for b in doc.blocks:
        if not isinstance(b, Table) or not b.rows:
            continue
        before_rows = [list(r) for r in b.rows]
        after_rows = elide_repeats([list(r) for r in b.rows])
        tokens_before = sum(count(v) for r in before_rows for v in r)
        tokens_after = sum(count(v) for r in after_rows for v in r)
        if tokens_before == tokens_after:
            continue

        ncols = max((len(r) for r in after_rows), default=0)
        risky_cols = []
        for c in range(ncols):
            fired = any(c < len(r) and r[c] == "^" for r in after_rows)
            header = b.cols[c] if c < len(b.cols) else ""
            if fired and _looks_like_identifier(c, header):
                risky_cols.append(header or f"c{c + 1}")

        reasoning_risk = 0.8 if risky_cols else 0.05
        note = (f"caret-elision fired on identifier-like column(s) {risky_cols} -- "
                f"Phase-5 failure analysis traced the dominant row_association "
                f"accuracy loss to exactly this pattern"
                if risky_cols else
                "caret-elision fired only on non-identifier-like columns")
        reports.append(TransformReport(
            name=f"caret_elision:{b.caption or 'table'}",
            tokens_before=tokens_before, tokens_after=tokens_after,
            token_savings=tokens_before - tokens_after,
            structural_risk=0.0, semantic_risk=0.0,
            reasoning_risk=reasoning_risk, note=note,
            evidence=("reports/FAILURE_ANALYSIS.md: row_association:encoded_away, n=30"
                      if risky_cols else
                      "no per-column accuracy measurement exists; heuristic only"),
        ))
    return reports


def report_dictionary(doc: Doc) -> TransformReport | None:
    """build_dictionary substitution is exact, word-bounded, and reversible
    (see optimize.py's own docstring), so structural/semantic risk are zero.
    reasoning_risk is NOT a guess here: eval/results/REPORT.md's ablation
    ladder measured removing the §n mechanism entirely and found it recovers
    <=0.1pp of accuracy -- i.e. the dictionary is *not* where TDF's measured
    accuracy cost comes from. 0.02 encodes "measured negligible", not "we
    assume it's fine"."""
    work = deepcopy(doc)
    tokens_before = _text_tokens(work)
    dictionary = build_dictionary(work)
    if not dictionary:
        return None
    tokens_after = _text_tokens(work) + sum(count(f"{n} {p}") for p, n in dictionary)
    return TransformReport(
        name="phrase_dictionary",
        tokens_before=tokens_before, tokens_after=tokens_after,
        token_savings=tokens_before - tokens_after,
        structural_risk=0.0, semantic_risk=0.0, reasoning_risk=0.02,
        note=f"{len(dictionary)} phrase(s) substituted, exact and reversible",
        evidence="eval/results/REPORT.md section 5: removing sn recovers <=0.1pp accuracy",
    )


def explain(doc: Doc) -> list[TransformReport]:
    """Run every reporting pass on a private copy of doc (never mutates the
    caller's document) and return every report produced. This is the
    single entry point a caller -- or a future scored optimizer -- should
    use; it does not change what render_tdf/tdf convert emit."""
    reports: list[TransformReport] = []
    reports.extend(report_constant_column_factoring(deepcopy(doc)))
    reports.extend(report_caret_elision(deepcopy(doc)))
    dict_report = report_dictionary(deepcopy(doc))
    if dict_report is not None:
        reports.append(dict_report)
    return reports
