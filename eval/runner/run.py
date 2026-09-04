import json
import pickle
import time
import re
import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
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

def _size_bucket(prompt_tokens: int) -> str:
    if prompt_tokens > 50000:
        return "large"
    if prompt_tokens > 10000:
        return "medium"
    return "small"


def _build_tasks(questions, docs, encoded_docs, seeds, arm_filter=None):
    """One task per (question, arm, seed). size_bucket is derived from THIS
    arm's own prompt_tokens -- it previously carried over from whichever arm
    ran first for a question, so a small md prompt could inherit "large"
    from an earlier huge tdf_full prompt for the same question."""
    tasks = []
    for q in questions:
        doc_id = q["doc_id"]
        for arm_name in ARMS.keys():
            if arm_filter is not None and arm_name not in arm_filter:
                continue
            if arm_name not in encoded_docs[doc_id]:
                continue
            doc_text = encoded_docs[doc_id][arm_name]
            prompt = f"Document:\n{doc_text}\n\nQuestion: {q['question']}\n\nAnswer only with the exact value requested, nothing else."
            prompt_tokens = get_tokens(prompt)
            for seed in seeds:
                tasks.append({
                    "q": q, "doc_id": doc_id, "arm_name": arm_name,
                    "prompt": prompt, "prompt_tokens": prompt_tokens,
                    "size_bucket": _size_bucket(prompt_tokens), "seed": seed,
                })
    return tasks


def _run_task(task, model_name):
    q = task["q"]
    t0 = time.time()
    pred, meta = generate(task["prompt"], model=model_name, temperature=0.0, seed=task["seed"])
    if pred is None:
        pred = ""
    latency_ms = int((time.time() - t0) * 1000)
    gold = str(q["answer"])
    return {
        "doc_id": task["doc_id"],
        "size_bucket": task["size_bucket"],
        "arm": task["arm_name"],
        "model": model_name,
        "question_id": q["id"],
        "qtype": q["type"],
        "seed": task["seed"],
        "prompt_tokens": task["prompt_tokens"],
        "completion_tokens": get_tokens(pred),
        "gold": gold,
        "pred": pred,
        "correct": _is_correct(q.get("type", ""), gold, pred),
        "latency_ms": latency_ms,
        "finish_reason": meta.get("finish_reason"),
        "used_reasoning_fallback": meta.get("used_reasoning_fallback"),
    }


def run_eval():
    out_dir = Path("eval/results")
    out_dir.mkdir(exist_ok=True)

    with open("eval/questions/questions.json", "r") as f:
        questions = json.load(f)

    doc_filter = os.environ.get("EVAL_DOC_IDS")
    if doc_filter:
        wanted = {d.strip() for d in doc_filter.split(",") if d.strip()}
        questions = [q for q in questions if q["doc_id"] in wanted]

    # Only load/encode documents actual questions reference. The corpus
    # directory can (and, since the Phase 6 expansion, does) hold documents
    # with zero questions written against them yet -- encoding those for
    # every arm is pure waste, and for large prose documents it is worse
    # than waste: repair.py's Re-Pair dictionary builder rescans the full
    # token sequence on every merge (O(merges x length)), so a full-length
    # novel costs ~3 minutes PER dictionary-enabled arm (measured: Pride and
    # Prejudice, 186s for one optimize() call). See validation/ for the
    # follow-up perf issue; the fix here is simply not to do unneeded work.
    needed_doc_ids = {q["doc_id"] for q in questions}
    docs = {}
    for pkl_file in Path("eval/corpus/perturbed").glob("*.pkl"):
        if pkl_file.stem not in needed_doc_ids:
            continue
        with open(pkl_file, "rb") as f:
            docs[pkl_file.stem] = pickle.load(f)

    arm_env = os.environ.get("EVAL_ARMS")
    arm_filter = {a.strip() for a in arm_env.split(",") if a.strip()} if arm_env else None

    encoded_docs = {}
    for doc_id, doc in docs.items():
        encoded_docs[doc_id] = {}
        for arm_name, encode_fn in ARMS.items():
            if arm_filter is not None and arm_name not in arm_filter:
                continue
            try:
                encoded_docs[doc_id][arm_name] = encode_fn(doc)
            except Exception:
                pass

    model_name = os.environ.get("EVAL_MODEL", "gpt-4o-mini")
    seeds = [int(s) for s in os.environ.get("EVAL_SEEDS", "1,2,3").split(",") if s.strip()]
    concurrency = max(1, int(os.environ.get("EVAL_CONCURRENCY", "1")))
    out_path = Path(os.environ.get("EVAL_OUT", "eval/results/raw.jsonl"))

    tasks = _build_tasks(questions, docs, encoded_docs, seeds, arm_filter)
    arms_used = sorted(arm_filter) if arm_filter is not None else sorted(ARMS)
    print(
        f"Starting eval: model={model_name}, docs={len(docs)}, questions={len(questions)}, "
        f"arms={arms_used}, seeds={seeds}, concurrency={concurrency}, tasks={len(tasks)}, "
        f"out={out_path}",
        flush=True,
    )

    attempted = 0
    completed = 0
    skipped = 0
    write_lock = threading.Lock()
    progress_lock = threading.Lock()

    if out_path.exists():
        out_path.unlink()
    out_fh = out_path.open("a", encoding="utf-8")

    def submit(task):
        nonlocal attempted, completed, skipped
        try:
            row = _run_task(task, model_name)
        except Exception as e:
            with progress_lock:
                attempted += 1
                skipped += 1
            print(f"Skipping {task['doc_id']} / {task['arm_name']} / seed={task['seed']} "
                  f"due to API error: {e}", flush=True)
            return
        with write_lock:
            out_fh.write(json.dumps(row) + "\n")
            out_fh.flush()
        with progress_lock:
            attempted += 1
            completed += 1
            if attempted % 25 == 0:
                print(f"Progress: attempted={attempted}/{len(tasks)} "
                      f"completed={completed} skipped={skipped}", flush=True)

    if concurrency == 1:
        for task in tasks:
            submit(task)
    else:
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            futures = [pool.submit(submit, task) for task in tasks]
            for f in as_completed(futures):
                f.result()  # re-raise anything submit() itself failed to catch

    out_fh.flush()
    out_fh.close()

    print(
        f"Done. attempted={attempted} completed={completed} skipped={skipped}",
        flush=True,
    )

if __name__ == "__main__":
    run_eval()
