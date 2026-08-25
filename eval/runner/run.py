import json
import pickle
import time
import re
import os
from pathlib import Path
from eval.formats.encode import ARMS
from eval.runner.client import generate

def get_tokens(text: str) -> int:
    if text is None:
        text = ""
    text = str(text)
    try:
        import tiktoken
        enc = tiktoken.get_encoding("o200k_base")
        return len(enc.encode(text, allowed_special="all"))
    except:
        return len(text.split())


def _norm_ws(s: str) -> str:
    if s is None:
        s = ""
    s = str(s)
    return re.sub(r"\s+", " ", s.strip())


def _is_correct(qtype: str, gold: str, pred: str) -> bool:
    g = _norm_ws(gold)
    p = _norm_ws(pred)
    if not g:
        return not p
    # Identifier/leading-zero/dictionary tasks need strict lexical fidelity.
    if qtype in {"exact_identifier", "leading_zero", "deref_dict"}:
        return p == g
    # Default: case-insensitive exact match first, then containment fallback.
    if p.lower() == g.lower():
        return True
    return g.lower() in p.lower()

def run_eval():
    out_dir = Path("eval/results")
    out_dir.mkdir(exist_ok=True)
    
    with open("eval/questions/questions.json", "r") as f:
        questions = json.load(f)
        
    results = []
    
    docs = {}
    for pkl_file in Path("eval/corpus/perturbed").glob("*.pkl"):
        with open(pkl_file, "rb") as f:
            docs[pkl_file.stem] = pickle.load(f)
            
    encoded_docs = {}
    for doc_id, doc in docs.items():
        encoded_docs[doc_id] = {}
        for arm_name, encode_fn in ARMS.items():
            try:
                encoded_docs[doc_id][arm_name] = encode_fn(doc)
            except Exception:
                pass
                
    model_name = os.environ.get("EVAL_MODEL", "gpt-4o-mini")
    print(
        f"Starting eval: model={model_name}, docs={len(docs)}, questions={len(questions)}, arms={len(ARMS)}",
        flush=True,
    )
    attempted = 0
    completed = 0
    skipped = 0

    out_path = Path("eval/results/raw.jsonl")
    if out_path.exists():
        out_path.unlink()
    out_fh = out_path.open("a", encoding="utf-8")

    for q in questions:
        doc_id = q["doc_id"]
        doc = docs[doc_id]
        size_bucket = "small"
        
        for arm_name in ARMS.keys():
            if arm_name not in encoded_docs[doc_id]:
                continue
            
            doc_text = encoded_docs[doc_id][arm_name]
            prompt = f"Document:\n{doc_text}\n\nQuestion: {q['question']}\n\nAnswer only with the exact value requested, nothing else."
            prompt_tokens = get_tokens(prompt)
            
            if prompt_tokens > 50000:
                size_bucket = "large"
            elif prompt_tokens > 10000:
                size_bucket = "medium"
            
            for seed in [1, 2, 3]:
                attempted += 1
                if attempted % 25 == 0:
                    print(
                        f"Progress: attempted={attempted} completed={completed} skipped={skipped}",
                        flush=True,
                    )
                t0 = time.time()
                try:
                    pred = generate(prompt, model=model_name, temperature=0.0, seed=seed)
                except Exception as e:
                    skipped += 1
                    print(f"Skipping {doc_id} / {arm_name} due to API error: {e}", flush=True)
                    continue
                if pred is None:
                    pred = ""
                latency_ms = int((time.time() - t0) * 1000)
                
                gold = str(q["answer"])
                is_correct = _is_correct(q.get("type", ""), gold, pred)
                
                results.append({
                    "doc_id": doc_id,
                    "size_bucket": size_bucket,
                    "arm": arm_name,
                    "model": model_name,
                    "question_id": q["id"],
                    "qtype": q["type"],
                    "seed": seed,
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": get_tokens(pred),
                    "gold": gold,
                    "pred": pred,
                    "correct": is_correct,
                    "latency_ms": latency_ms
                })
                completed += 1
                out_fh.write(json.dumps(results[-1]) + "\n")
                # Flush periodically so partial status is visible during long runs.
                if completed % 10 == 0:
                    out_fh.flush()
                
    out_fh.flush()
    out_fh.close()
            
    print(
        f"Done. Evaluated {len(results)} queries. attempted={attempted} completed={completed} skipped={skipped}",
        flush=True,
    )

if __name__ == "__main__":
    run_eval()
