import json
import pickle
import random
import re
from pathlib import Path

from tdf.columnar import encode_columns
from tdf.ir import Doc, Para, Table
from tdf.optimize import build_dictionary

NUM_RE = re.compile(r"^-?\d+(?:\.\d+)?$")


def _to_num(s: str):
    s = s.strip().replace(",", "")
    if not s:
        return None
    if s.startswith("(") and s.endswith(")"):
        s = "-" + s[1:-1]
    s = re.sub(r"[$€£¥%]", "", s)
    return float(s) if NUM_RE.match(s) else None


def _add_q(questions: list[dict], doc_id: str, qtype: str, question: str, answer: str):
    questions.append(
        {
            "id": f"{doc_id}_{qtype}_{len(questions)}",
            "type": qtype,
            "question": question,
            "answer": str(answer),
        }
    )


def _unique_col_idx(t: Table):
    for ci, _ in enumerate(t.cols):
        vals = [r[ci] for r in t.rows if ci < len(r) and r[ci]]
        if vals and len(vals) == len(set(vals)):
            return ci
    return None


def generate_questions(doc: Doc, doc_id: str):
    questions: list[dict] = []
    tables = [b for b in doc.blocks if isinstance(b, Table) and b.rows and b.cols]
    paras = [b for b in doc.blocks if isinstance(b, Para) and b.text.strip()]

    # Short prose exact extraction prompts (avoid long free-form answers).
    for p in random.sample(paras, min(2, len(paras))):
        words = p.text.split()
        if len(words) >= 8:
            phrase = " ".join(words[:3])
            answer = " ".join(words[3:6])
            _add_q(
                questions,
                doc_id,
                "exact_identifier",
                f"In the sentence containing '{phrase}', what are the next three words exactly?",
                answer,
            )

    for t in tables:
        if len(t.cols) < 2:
            continue
        key_ci = _unique_col_idx(t)
        if key_ci is None:
            key_ci = 0
        val_ci = 1 if key_ci == 0 else 0
        usable_rows = [r for r in t.rows if key_ci < len(r) and val_ci < len(r) and r[key_ci] and r[val_ci]]
        if not usable_rows:
            continue

        row = random.choice(usable_rows)
        key_col = t.cols[key_ci]
        val_col = t.cols[val_ci]
        key_val = row[key_ci]
        val = row[val_ci]

        # Row association
        _add_q(
            questions,
            doc_id,
            "row_association",
            f"In the table, what is '{val_col}' where '{key_col}' is '{key_val}'?",
            val,
        )

        # Column association
        _add_q(
            questions,
            doc_id,
            "column_association",
            f"In the row where '{key_col}' is '{key_val}', which column has value '{val}'?",
            val_col,
        )

        # Ordering. Anchored on the table's FIRST value, not just "this
        # table" -- a document with many same-shaped tables (common after
        # PDF extraction: no caption, generic "c1"/"c2" column names, see
        # reports/broad_corpus_accuracy.md's qtype breakdown) gives a model
        # no way to tell which table an unanchored "this table" means, and
        # ordering questions scored near floor for EVERY arm as a result --
        # a corpus-quality artifact, not a real capability gap. The first
        # value is a real data value, not a structural placeholder, so it's
        # far more likely to be unique to one specific table.
        first = next((r[key_ci] for r in t.rows if key_ci < len(r) and r[key_ci]), None)
        last = next((r[key_ci] for r in reversed(t.rows) if key_ci < len(r) and r[key_ci]), None)
        if first and last and first != last:
            _add_q(
                questions,
                doc_id,
                "ordering",
                f"In the table whose first '{key_col}' value is '{first}', "
                f"what is the last '{key_col}' value, in row order?",
                last,
            )

        # Repeated-cell stress (^ path in TDF)
        for ci, cname in enumerate(t.cols):
            for ri in range(1, len(t.rows)):
                prev = t.rows[ri - 1][ci] if ci < len(t.rows[ri - 1]) else ""
                cur = t.rows[ri][ci] if ci < len(t.rows[ri]) else ""
                if prev and prev == cur and key_ci < len(t.rows[ri]) and t.rows[ri][key_ci]:
                    _add_q(
                        questions,
                        doc_id,
                        "repeated_cell",
                        f"For '{key_col}'='{t.rows[ri][key_ci]}', what is '{cname}'?",
                        cur,
                    )
                    break
            else:
                continue
            break

        # Leading-zero values
        for ri, r in enumerate(t.rows):
            for ci, cell in enumerate(r):
                if re.match(r"^0\d+$", cell):
                    _add_q(
                        questions,
                        doc_id,
                        "leading_zero",
                        f"Return the exact value in column '{t.cols[ci]}' for row index {ri + 1}. Keep leading zeros.",
                        cell,
                    )
                    break
            else:
                continue
            break

        # Numeric comparison + negation + multi-hop
        numeric_cols = []
        for ci, cname in enumerate(t.cols):
            nums = []
            for r in t.rows:
                if ci < len(r):
                    n = _to_num(r[ci])
                    if n is not None:
                        nums.append((r, n))
            if len(nums) >= 3:
                numeric_cols.append((ci, cname, nums))

        if numeric_cols:
            ci_num, cname_num, nums = random.choice(numeric_cols)
            best_r, _ = max(nums, key=lambda x: x[1])
            if key_ci < len(best_r):
                _add_q(
                    questions,
                    doc_id,
                    "numeric_comparison",
                    f"Which '{key_col}' has the largest '{cname_num}'?",
                    best_r[key_ci],
                )

            # negation: pick one key and ask for value that is NOT it.
            keys = [r[key_ci] for r, _ in nums if key_ci < len(r) and r[key_ci]]
            if len(set(keys)) >= 2:
                ban = keys[0]
                alt = next(k for k in keys if k != ban)
                _add_q(
                    questions,
                    doc_id,
                    "negation",
                    f"Name one '{key_col}' whose '{cname_num}' is NOT associated with '{ban}'.",
                    alt,
                )

            # Multi-hop: among rows with a categorical filter, pick max numeric
            cat_cols = [ci for ci in range(len(t.cols)) if ci != ci_num]
            if cat_cols:
                cci = cat_cols[0]
                groups = {}
                for r, n in nums:
                    if cci < len(r) and r[cci]:
                        groups.setdefault(r[cci], []).append((r, n))
                group_items = [(g, vals) for g, vals in groups.items() if len(vals) >= 2]
                if group_items:
                    gname, gvals = random.choice(group_items)
                    best_g, _ = max(gvals, key=lambda x: x[1])
                    if key_ci < len(best_g):
                        _add_q(
                            questions,
                            doc_id,
                            "multi_hop_table",
                            f"Within rows where '{t.cols[cci]}' is '{gname}', which '{key_col}' has the highest '{cname_num}'?",
                            best_g[key_ci],
                        )

    # Cross-table reference (same key column name across tables).
    if len(tables) >= 2:
        for t1 in tables:
            for t2 in tables:
                if t1 is t2:
                    continue
                shared = [c for c in t1.cols if c in t2.cols]
                if not shared:
                    continue
                k = shared[0]
                c1 = t1.cols.index(k)
                c2 = t2.cols.index(k)
                vals1 = {r[c1] for r in t1.rows if c1 < len(r) and r[c1]}
                vals2 = {r[c2] for r in t2.rows if c2 < len(r) and r[c2]}
                inter = sorted(vals1 & vals2)
                if not inter:
                    continue
                kv = inter[0]
                target_ci = 0 if c2 != 0 else (1 if len(t2.cols) > 1 else None)
                if target_ci is None:
                    continue
                target_row = next((r for r in t2.rows if c2 < len(r) and r[c2] == kv and target_ci < len(r) and r[target_ci]), None)
                if target_row:
                    _add_q(
                        questions,
                        doc_id,
                        "cross_reference",
                        f"Find '{k}'='{kv}' and return '{t2.cols[target_ci]}' from the other table that also contains '{k}'.",
                        target_row[target_ci],
                    )
                    break
            else:
                continue
            break

    # Dictionary/codebook stress categories (still answerable by all arms).
    books = encode_columns(doc)
    for book in books[:2]:
        vals = [v for v in book.mapping.values() if v]
        if vals:
            target = vals[0]
            _add_q(
                questions,
                doc_id,
                "deref_code",
                f"What is one value present in column '{book.header}'?",
                target,
            )

    dict_phrases = [p[0] for p in build_dictionary(doc) if p and p[0]]
    for phrase in random.sample(dict_phrases, min(2, len(dict_phrases))):
        parts = phrase.split()
        if len(parts) >= 3:
            _add_q(
                questions,
                doc_id,
                "deref_dict",
                f"Return the exact phrase that starts with '{parts[0]} {parts[1]}'.",
                phrase,
            )

    return questions

def main():
    out_dir = Path("eval/questions")
    out_dir.mkdir(exist_ok=True)
    
    all_q = []
    
    for pkl_file in Path("eval/corpus/perturbed").glob("*.pkl"):
        doc_id = pkl_file.stem
        with open(pkl_file, "rb") as f:
            doc = pickle.load(f)
            
        qs = generate_questions(doc, doc_id)
        for q in qs:
            q["doc_id"] = doc_id
        all_q.extend(qs)
        
    with open(out_dir / "questions.json", "w") as f:
        json.dump(all_q, f, indent=2)
        
    print(f"Generated {len(all_q)} questions")

if __name__ == "__main__":
    random.seed(42)
    main()
