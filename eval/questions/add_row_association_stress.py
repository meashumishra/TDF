"""Phase 20 addendum: targeted row-association stress questions.

generate.py's generic generate_questions() produces exactly ONE
repeated_cell question per table (it breaks after the first repeat found)
-- not enough statistical power to say anything confident about the
caret-elision-vs-group-header mechanism this whole exercise is about (see
reports/grouped_metrics_preliminary.md: n=9 for tdf_full on that single
question was already suggestive, but far too thin to be a verdict).

This script adds many more of exactly that question shape for
grouped_metrics: "what is 'country' where 'record_id' is X", sampled from
NON-FIRST rows within each country's block. Position 0 of a group is
trivially correct for every arm (the value is always literal there, group
header or not) -- the interesting rows are 1..7, where tdf_full caret-
elides and tdf_grouped/tdf_nocaret0 don't. Same additive/idempotent
pattern as add_document.py: existing questions (including
add_document.py's own generated set) are untouched; re-running this
replaces only this script's own previously-added questions.

Usage: .venv/bin/python -m eval.questions.add_row_association_stress
"""

import json
import pickle
from pathlib import Path

QUESTIONS_PATH = Path("eval/questions/questions.json")
DOC_ID = "grouped_metrics"
QTYPE = "row_association"
ID_PREFIX = f"{DOC_ID}_stress_{QTYPE}_"


def build_questions() -> list[dict]:
    with open(f"eval/corpus/perturbed/{DOC_ID}.pkl", "rb") as f:
        doc = pickle.load(f)
    table = next(b for b in doc.blocks if hasattr(b, "cols"))
    country_ci, record_ci = 0, 1

    # Group rows by country, in row order, to find each group's non-first positions.
    groups: dict[str, list[int]] = {}
    for i, r in enumerate(table.rows):
        groups.setdefault(r[country_ci], []).append(i)

    questions = []
    n = 0
    for country, indices in groups.items():
        for pos in indices[1:4]:  # 3 non-first rows per group, deterministic
            row = table.rows[pos]
            record_id = row[record_ci]
            questions.append({
                "id": f"{ID_PREFIX}{n}",
                "type": QTYPE,
                "question": f"In the table, what is 'country' where 'record_id' is '{record_id}'?",
                "answer": country,
                "doc_id": DOC_ID,
            })
            n += 1
    return questions


def main() -> int:
    new_qs = build_questions()
    existing = json.loads(QUESTIONS_PATH.read_text()) if QUESTIONS_PATH.exists() else []
    existing = [q for q in existing if not q.get("id", "").startswith(ID_PREFIX)]
    existing.extend(new_qs)
    QUESTIONS_PATH.write_text(json.dumps(existing, indent=2))
    return len(new_qs)


if __name__ == "__main__":
    n = main()
    print(f"Added {n} row-association stress questions for {DOC_ID!r} to {QUESTIONS_PATH}")
