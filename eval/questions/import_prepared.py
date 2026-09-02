"""Phase 21: import externally-prepared questions for the 13 unquestioned
Phase 6 corpus documents.

Same additive/idempotent pattern as add_document.py and
add_row_association_stress.py: reads one or more JSON files (each a flat
list of {id, type, question, answer, doc_id} objects, or a dict mapping
doc_id -> list of such objects), replaces any EXISTING question whose
doc_id is one of the incoming file's doc_ids, and appends the rest.
Every pre-existing question for every OTHER doc_id is left untouched.

Validates before writing:
  - every question has the five required fields, all non-empty strings
    (except id, which just needs to be unique)
  - doc_id is one of the 13 expected ids (typos are a common failure mode
    for hand-authored/LLM-authored data -- catch them here, not at eval time)
  - ids are globally unique against both the new batch and the existing file
  - doc_id actually has a perturbed pkl to encode against

Usage:
    .venv/bin/python -m eval.questions.import_prepared <file.json> [more.json ...]
    .venv/bin/python -m eval.questions.import_prepared --dry-run <file.json>
"""

import json
import sys
from pathlib import Path

QUESTIONS_PATH = Path("eval/questions/questions.json")
PERTURBED_DIR = Path("eval/corpus/perturbed")

EXPECTED_DOC_IDS = {
    "k8s_services", "k8s_configmap", "rfc2616_http", "rfc1035_dns",
    "alice_prose", "frankenstein_prose", "pride_prose",
    "readme_requests", "readme_fastapi", "access_log",
    "code_doc_dataclasses", "code_doc_decimal", "github_terms",
}

REQUIRED_FIELDS = ("id", "type", "question", "answer", "doc_id")


def _load_batch(path: Path) -> list[dict]:
    data = json.loads(path.read_text())
    if isinstance(data, dict):
        out = []
        for doc_id, qs in data.items():
            for q in qs:
                q.setdefault("doc_id", doc_id)
            out.extend(qs)
        return out
    if isinstance(data, list):
        return data
    raise ValueError(f"{path}: expected a JSON list or {{doc_id: [...]}} dict")


def validate(questions: list[dict]) -> list[str]:
    errors = []
    seen_ids: set[str] = set()
    for i, q in enumerate(questions):
        for field in REQUIRED_FIELDS:
            if not q.get(field) or not isinstance(q[field], str):
                errors.append(f"item {i}: missing or empty field {field!r}: {q}")
        doc_id = q.get("doc_id")
        if doc_id and doc_id not in EXPECTED_DOC_IDS:
            errors.append(f"item {i}: unexpected doc_id {doc_id!r} "
                          f"(not one of {sorted(EXPECTED_DOC_IDS)})")
        if doc_id and not (PERTURBED_DIR / f"{doc_id}.pkl").exists():
            errors.append(f"item {i}: no perturbed pkl for doc_id {doc_id!r}")
        qid = q.get("id")
        if qid in seen_ids:
            errors.append(f"item {i}: duplicate id {qid!r} within this batch")
        seen_ids.add(qid)
    return errors


def main(argv: list[str]) -> int:
    dry_run = "--dry-run" in argv
    paths = [Path(a) for a in argv if a != "--dry-run"]
    if not paths:
        print(__doc__)
        return 1

    new_questions: list[dict] = []
    for p in paths:
        new_questions.extend(_load_batch(p))

    errors = validate(new_questions)
    if errors:
        print(f"{len(errors)} validation error(s), nothing written:")
        for e in errors[:50]:
            print(" -", e)
        return 1

    incoming_doc_ids = {q["doc_id"] for q in new_questions}
    incoming_ids = {q["id"] for q in new_questions}

    existing = json.loads(QUESTIONS_PATH.read_text()) if QUESTIONS_PATH.exists() else []
    collisions = [q["id"] for q in existing if q["id"] in incoming_ids]
    if collisions:
        print(f"{len(collisions)} id(s) already exist in questions.json and "
              f"would collide: {collisions[:20]}")
        return 1

    kept = [q for q in existing if q.get("doc_id") not in incoming_doc_ids]
    merged = kept + new_questions

    by_doc: dict[str, int] = {}
    for q in new_questions:
        by_doc[q["doc_id"]] = by_doc.get(q["doc_id"], 0) + 1
    print(f"Importing {len(new_questions)} questions across {len(by_doc)} document(s):")
    for doc_id, n in sorted(by_doc.items()):
        print(f"  {doc_id:<22} {n}")
    missing = EXPECTED_DOC_IDS - set(by_doc)
    if missing:
        print(f"Not covered by this import: {sorted(missing)}")

    if dry_run:
        print(f"\n--dry-run: not writing. Would go from {len(existing)} "
              f"to {len(merged)} total questions.")
        return 0

    QUESTIONS_PATH.write_text(json.dumps(merged, indent=2))
    print(f"\nWrote {len(merged)} total questions to {QUESTIONS_PATH} "
          f"(was {len(existing)}).")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
