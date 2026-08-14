import json
import pickle
import random
from pathlib import Path
from tdf.ir import Doc, Table, Para, Heading
from tdf.columnar import encode_columns
from tdf.optimize import build_dictionary

def generate_questions(doc: Doc, doc_id: str):
    questions = []
    
    # Generate prose questions
    paras = [b for b in doc.blocks if isinstance(b, Para)]
    if paras:
        for p in random.sample(paras, min(3, len(paras))):
            words = p.text.split()
            if len(words) > 5:
                q = f"What text contains the phrase '{' '.join(words[:3])}'?"
                questions.append({
                    "id": f"{doc_id}_prose_{len(questions)}",
                    "type": "prose",
                    "question": q,
                    "answer": p.text
                })
                
    # Generate table questions
    tables = [b for b in doc.blocks if isinstance(b, Table) and len(b.rows) > 0 and len(b.cols) > 0]
    for t in tables:
        # Lookup
        row_idx = random.randint(0, len(t.rows) - 1)
        col_idx = random.randint(0, len(t.cols) - 1)
        # Avoid empty cols/rows
        if t.cols[col_idx] and t.rows[row_idx][col_idx]:
            # Use another column as key if possible
            key_col = (col_idx + 1) % len(t.cols)
            if t.rows[row_idx][key_col]:
                q = f"In the table containing '{t.cols[col_idx]}', what is the value of '{t.cols[col_idx]}' where '{t.cols[key_col]}' is '{t.rows[row_idx][key_col]}'?"
                questions.append({
                    "id": f"{doc_id}_lookup_{len(questions)}",
                    "type": "lookup",
                    "question": q,
                    "answer": t.rows[row_idx][col_idx]
                })

    # Find deref_code and deref_dict
    books = encode_columns(doc)
    dict_phrases = build_dictionary(doc)
    
    if books:
        for book in books:
            for code, value in book.mapping.items():
                if value and len(value) > 2:
                    q = f"What is one of the decoded values in the column '{book.header}'?"
                    questions.append({
                        "id": f"{doc_id}_deref_code_{len(questions)}",
                        "type": "deref_code",
                        "question": q,
                        "answer": value
                    })
                    break
                    
    if dict_phrases:
        phrases = [p[0] for p in dict_phrases]
        for p in random.sample(phrases, min(3, len(phrases))):
            words = p.split()
            if len(words) > 2:
                q = f"What phrase contains '{words[0]} {words[1]}'?"
                questions.append({
                    "id": f"{doc_id}_deref_dict_{len(questions)}",
                    "type": "deref_dict",
                    "question": q,
                    "answer": p
                })
                
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
