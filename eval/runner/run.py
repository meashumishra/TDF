import json
import pickle
import time
from pathlib import Path
from eval.formats.encode import ARMS
from eval.runner.client import generate

def get_tokens(text: str) -> int:
    try:
        import tiktoken
        enc = tiktoken.get_encoding("o200k_base")
        return len(enc.encode(text, allowed_special="all"))
    except:
        return len(text.split())

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
                t0 = time.time()
                try:
                    pred = generate(prompt, model="gpt-4o-mini", temperature=0.0, seed=seed)
                except Exception as e:
                    print(f"Skipping {doc_id} / {arm_name} due to API error: {e}")
                    continue
                latency_ms = int((time.time() - t0) * 1000)
                
                # Check correctness
                gold = str(q["answer"])
                is_correct = gold.strip().lower() in pred.strip().lower()
                
                results.append({
                    "doc_id": doc_id,
                    "size_bucket": size_bucket,
                    "arm": arm_name,
                    "model": "gpt-4o-mini",
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
                
    with open("eval/results/raw.jsonl", "w") as f:
        for r in results:
            f.write(json.dumps(r) + "\n")
            
    print(f"Done. Evaluated {len(results)} queries.")

if __name__ == "__main__":
    run_eval()
