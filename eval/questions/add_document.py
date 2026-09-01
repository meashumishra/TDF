"""Phase 20: append questions for ONE new corpus document.

generate.py's main() globs every pkl in eval/corpus/perturbed/ and
overwrites questions.json from scratch -- fine when the corpus first gets
questions, but re-running it today would regenerate questions for all 19
documents (12 with none previously, from the Phase 6 corpus expansion),
turning the 263-question, 5-document baseline v1/v2 were both measured
against into something entirely different and no longer comparable.

This script does the additive thing instead: generate questions for ONE
doc_id and append them, leaving every existing question (and every other
document's absence of questions) untouched. Re-running it for the same
doc_id is idempotent -- existing questions for that doc_id are replaced,
not duplicated.

Usage: .venv/bin/python -m eval.questions.add_document <doc_id>
"""

import json
import pickle
import random
import sys
from pathlib import Path

from eval.questions.generate import generate_questions

QUESTIONS_PATH = Path("eval/questions/questions.json")


def add_document(doc_id: str) -> int:
    pkl_path = Path("eval/corpus/perturbed") / f"{doc_id}.pkl"
    with open(pkl_path, "rb") as f:
        doc = pickle.load(f)

    random.seed(42)  # matches generate.py's main() convention
    new_qs = generate_questions(doc, doc_id)
    for q in new_qs:
        q["doc_id"] = doc_id

    existing = json.loads(QUESTIONS_PATH.read_text()) if QUESTIONS_PATH.exists() else []
    existing = [q for q in existing if q.get("doc_id") != doc_id]
    existing.extend(new_qs)

    QUESTIONS_PATH.write_text(json.dumps(existing, indent=2))
    return len(new_qs)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: python -m eval.questions.add_document <doc_id>")
        sys.exit(1)
    n = add_document(sys.argv[1])
    print(f"Added {n} questions for {sys.argv[1]!r} to {QUESTIONS_PATH}")
