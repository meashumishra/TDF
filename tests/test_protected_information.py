"""Phase 14: protected-information regression tests.

Follow-up to validation/reasoning_optimizer_audit.md (Phase 13), which found
that no category from the mission's protected-information list (IDs,
numbers, dates, units, names, URLs, file paths, DB keys, legal clauses,
negations, conditions, row/column identifiers) has a dedicated classifier
anywhere in optimize.py, tier.py, or columnar.py. What protects them today
is either exact/reversible substitution (dictionary, columnar) or being
outside the reach of every current heuristic gate.

This suite turns that audit finding into regression coverage: run each
protected category through the FULL default pipeline (optimize() -- text
hygiene, dictionary substitution -- plus unconditional columnar coding and
caret-elision) and assert the round-tripped content is character-exact, not
just "a token bag matches". Where the audit found an actual gap rather than
a confirmed-safe result, the test documents the gap explicitly (Test 9)
instead of silently passing over it -- and this suite is itself the reason
that finding got corrected: an earlier draft of Test 9 assumed column 0 was
protected (matching the audit's first draft), until Test 9 was pointed at
column 0 directly and it turned out `tdf/emit.py`'s actual default path
elides it too. `elide_repeats_keep_anchor` protects column 0 only inside an
unshipped, unmeasured eval arm -- see Test 9 and the audit's corrected §6.

Run: .venv/bin/python -m pytest tests/test_protected_information.py -q
"""

from __future__ import annotations

import sys
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tdf.columnar import encode_columns  # noqa: E402
from tdf.emit import render_tdf  # noqa: E402
from tdf.ir import Doc, Para, Table  # noqa: E402
from tdf.optimize import optimize  # noqa: E402
from tdf.parse import parse_tdf  # noqa: E402


def _round_trip(doc: Doc) -> tuple[Doc, str]:
    """Full default pipeline: optimize() + columnar coding + caret-elision,
    then parse back. Returns (restored_doc, wire) so tests can inspect both
    the recovered content and the literal wire form."""
    work = deepcopy(doc)
    books = encode_columns(work)
    wire = render_tdf(work, legend=False, codebooks=books)  # optimized=True default
    return parse_tdf(wire), wire


def _paras(doc: Doc) -> list[str]:
    return [b.text for b in doc.blocks if isinstance(b, Para)]


# --------------------------------------------------------- 1. negation

def test_negation_survives_dictionary_substitution():
    """A negation-bearing phrase repeated 3x is exactly the shape
    build_dictionary looks for -- confirm the §n substitution it performs is
    exact-text and reversible, not a paraphrase that could flip the negation."""
    doc = Doc(title="Report", blocks=[
        Para("The revenue did not increase during the quarter despite forecasts."),
        Para("Analysts noted the revenue did not increase during the quarter despite forecasts."),
        Para("In contrast, the revenue did not increase during the quarter despite forecasts in EMEA."),
    ])
    restored, wire = _round_trip(doc)
    assert "§1" in wire or "§" in wire, "expected dictionary substitution to fire"
    assert _paras(restored) == _paras(doc)


# --------------------------------------------------------- 2. URLs

def test_url_survives_untouched_even_when_not_dictionary_eligible():
    """A URL is one whitespace-delimited token (tdf's word alphabet is \\S+),
    so it can never itself become a multi-word dictionary phrase -- it is
    protected from substitution by construction. Confirm clean_text's
    unicode/emphasis hygiene also leaves it untouched."""
    url = "https://example.com/reports/q1_2024.pdf?ref=exec&page=3"
    doc = Doc(title="Report", blocks=[
        Para(f"See {url} for details on revenue."),
        Para(f"Also see {url} for the raw data export."),
        Para(f"Finally see {url} one more time for archival."),
    ])
    restored, wire = _round_trip(doc)
    assert url in wire
    assert _paras(restored) == _paras(doc)


# --------------------------------------------------------- 3. file paths

def test_file_path_survives_dictionary_substitution():
    """File paths contain underscores, which optimize.py's emphasis-stripping
    regex must NOT treat as CommonMark emphasis delimiters (that guard is
    already load-bearing for identifiers like __init__ or api_key_secret --
    see optimize.py's _EMPHASIS_UNDERSCORE docstring). Repeat the path 3x so
    it becomes dictionary-eligible and is actually exercised end to end."""
    path = "/var/log/app_server/output_2024.log"
    doc = Doc(title="Report", blocks=[
        Para(f"Full path: {path} has the trace."),
        Para(f"Backup path: {path} is rotated daily."),
        Para(f"Restore path: {path} after failure."),
    ])
    restored, wire = _round_trip(doc)
    assert path in wire
    assert _paras(restored) == _paras(doc)


# --------------------------------------------------------- 4. leading-zero IDs

def test_leading_zero_ids_survive_normalize_cell():
    """normalize_cell strips thousand-separator commas from numeric-looking
    cells; it must not also treat a leading-zero ID as a number and drop the
    zeros (mission section 13 explicitly lists this as an adversarial case)."""
    doc = Doc(blocks=[Table(
        cols=["account", "balance"],
        rows=[["00042", "1,234.00"], ["00007", "500.00"], ["00099", "10.00"]],
    )])
    restored, wire = _round_trip(doc)
    tbl = next(b for b in restored.blocks if isinstance(b, Table))
    assert [r[0] for r in tbl.rows] == ["00042", "00007", "00099"]
    # The genuinely-numeric column is still allowed to lose its thousand
    # separator -- that IS normalize_cell's documented, intentional job.
    assert tbl.rows[0][1] == "1234.00"


# --------------------------------------------------------- 5. similar IDs

def test_similar_ids_remain_distinct_through_caret_elision():
    """ID-01 and ID-001 are different strings that a human skimming a diff
    could conflate; the format must not conflate them either. elide_repeats
    only ever collapses a cell that is EXACTLY equal to the one directly
    above it (optimize.py:198-213), so two merely-similar strings can never
    be caret-collapsed into each other -- confirmed here since no two
    adjacent id cells are equal, every one stays literal, independent of
    any anchor protection (see test_KNOWN_GAP_no_column_is_anchor_protected_
    in_default_pipeline below -- there is none in the shipped default
    path)."""
    doc = Doc(blocks=[Table(
        cols=["id", "region", "balance", "opened"],
        rows=[
            ["ID-01", "EMEA", "00042", "2024-01-15"],
            ["ID-001", "EMEA", "00042", "2024-01-15"],
            ["ID-01", "APAC", "00007", "2024-02-20"],
            ["ID-002", "APAC", "00007", "2024-02-20"],
        ],
    )])
    restored, wire = _round_trip(doc)
    tbl = next(b for b in restored.blocks if isinstance(b, Table))
    assert [r[0] for r in tbl.rows] == ["ID-01", "ID-001", "ID-01", "ID-002"]
    id_cells = [line.split(" ", 1)[0] for line in wire.splitlines()
                if line and not line.startswith(("!", "#", "%"))]
    assert len(id_cells) == 4 and "^" not in id_cells


# --------------------------------------------------------- 6. dates

def test_dates_survive_normalize_cell_untouched():
    """ISO and slash-form dates must not match the numeric-cell pattern
    (they contain internal '-'/'/' so _NUM's all-digits body never matches)
    and so must come back byte-identical, not reformatted or truncated."""
    doc = Doc(blocks=[Table(
        cols=["opened", "closed"],
        rows=[["2024-01-15", "2024-03-01"], ["01/15/2024", "03/01/2024"]],
    )])
    restored, wire = _round_trip(doc)
    tbl = next(b for b in restored.blocks if isinstance(b, Table))
    assert tbl.rows == [["2024-01-15", "2024-03-01"], ["01/15/2024", "03/01/2024"]]


# --------------------------------------------------------- 7. conditions / legal clauses

def test_conditional_clause_survives_full_pipeline():
    """A clause with an explicit condition ('if X then Y unless Z') must
    survive dictionary substitution word-for-word -- this is exactly the
    kind of legal/contractual language mission section 8 calls high-risk."""
    clause = ("if the account balance exceeds five hundred dollars then a "
              "monthly fee applies unless the balance is waived by support")
    doc = Doc(title="Terms", blocks=[
        Para(f"Standard tier: {clause}."),
        Para(f"Premium tier: {clause}, backdated to enrollment."),
        Para(f"Legacy tier: {clause}, per the original 2019 agreement."),
    ])
    restored, wire = _round_trip(doc)
    assert _paras(restored) == _paras(doc)


# --------------------------------------------------------- 8. column identifiers

def test_column_headers_never_altered_by_any_pass():
    """Headers are never dictionary-substituted, caret-elided, or coded --
    confirm that holds even when the header text itself looks compressible
    (repeated words, underscores) and every other pass is firing on the body."""
    doc = Doc(blocks=[Table(
        cols=["customer_id", "customer_region", "customer_revenue"],
        rows=[["C1", "EMEA", "100"], ["C1", "EMEA", "100"], ["C2", "APAC", "200"]],
    )])
    restored, wire = _round_trip(doc)
    tbl = next(b for b in restored.blocks if isinstance(b, Table))
    assert tbl.cols == ["customer_id", "customer_region", "customer_revenue"]
    assert "!C customer_id customer_region customer_revenue" in wire


# --------------------------------------------------------- 9. known gap (documented, not silently passed)

def test_KNOWN_GAP_no_column_is_anchor_protected_in_default_pipeline():
    """Documents a real, currently-unmitigated reasoning-risk gap found in
    the Phase 13 audit (corrected there after this test caught the original
    version of the finding understating it): `tdf convert` / `render_tdf` --
    the actual shipped default path -- calls plain `elide_repeats`
    (optimize.py:198), which has NO anchor protection for any column,
    including column 0.

    `elide_repeats_keep_anchor` (optimize.py:216), which protects column 0,
    exists in the codebase but is only ever invoked by
    eval/formats/encode.py's `encode_tdf_nocaret0` -- an exploratory eval
    arm reached via a `unittest.mock` patch, never by `tdf/emit.py`'s
    `_tdf_table`. So this is not "column 0 is protected, other columns
    aren't" -- it's "no column is protected in the code path real users
    hit", regardless of whether the identifier happens to sit in column 0.

    This is NOT a fidelity bug -- parse_tdf reconstructs the exact value,
    asserted below -- but the wire form loses the literal id on repeated
    rows, the precise mechanism Phase-5's failure analysis
    (reports/FAILURE_ANALYSIS.md) traced the dominant row_association loss
    to. If a future change wires elide_repeats_keep_anchor (or a
    generalized version of it) into the default pipeline, this test's
    second assertion should start failing for the column-0 case -- flip it
    then, rather than deleting it silently, and update
    validation/reasoning_optimizer_audit.md's recommendations to match.
    """
    # Case A: the identifier IS column 0 -- still unprotected by default.
    col0_doc = Doc(blocks=[Table(
        cols=["id", "region", "balance"],
        rows=[
            ["ACC-1001", "EMEA", "500"],
            ["ACC-1001", "EMEA", "620"],
            ["ACC-2002", "APAC", "300"],
        ],
    )])
    restored, wire = _round_trip(col0_doc)
    tbl = next(b for b in restored.blocks if isinstance(b, Table))
    assert [r[0] for r in tbl.rows] == ["ACC-1001", "ACC-1001", "ACC-2002"]
    body_lines = [l for l in wire.splitlines() if l and l[0] not in "!#%"]
    id_cells = [l.split(" ")[0] for l in body_lines]
    assert id_cells == ["ACC-1001", "^", "ACC-2002"], (
        "column 0 is no longer caret-elided by default -- anchor "
        "protection has been wired into the default pipeline. Update "
        "this test and validation/reasoning_optimizer_audit.md to match"
    )

    # Case B: the identifier is column 1 -- same lack of protection.
    col1_doc = Doc(blocks=[Table(
        cols=["region", "account_id", "balance"],
        rows=[
            ["EMEA", "ACC-1001", "500"],
            ["EMEA", "ACC-1001", "620"],
            ["APAC", "ACC-2002", "300"],
        ],
    )])
    restored, wire = _round_trip(col1_doc)
    tbl = next(b for b in restored.blocks if isinstance(b, Table))
    assert [r[1] for r in tbl.rows] == ["ACC-1001", "ACC-1001", "ACC-2002"]
    body_lines = [l for l in wire.splitlines() if l and l[0] not in "!#%"]
    account_id_cells = [l.split(" ")[1] for l in body_lines]
    assert account_id_cells == ["ACC-1001", "^", "ACC-2002"]
