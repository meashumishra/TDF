"""Fill ONLY the missing cells of the eval matrix, preserving existing rows.

run_eval() deletes raw.jsonl and replays everything through the response
cache; that is riskier than necessary when 6310/6312 cells are already done.
This script appends just the missing rows in the identical schema.
"""
import json
import os
import pickle
import sys
import time
from pathlib import Path

sys.path.insert(0, str('.'))
from eval.formats.encode import ARMS  # noqa: E402
from eval.runner.client import generate  # noqa: E402
from eval.runner.run import _is_correct, get_tokens  # noqa: E402

MODEL = 'openai/gpt-oss-120b'

rows = [json.loads(l) for l in open('eval/results/raw.jsonl') if l.strip()]
qs = json.load(open('eval/questions/questions.json'))
have = {(r['doc_id'], r['question_id'], r['arm'], r['seed']) for r in rows}

docs = {}
for p in Path('eval/corpus/perturbed').glob('*.pkl'):
    with open(p, 'rb') as f:
        docs[p.stem] = pickle.load(f)

encoded = {}
for d in docs:
    encoded[d] = {}
    for a, fn in ARMS.items():
        try:
            encoded[d][a] = fn(docs[d])
        except Exception:
            pass

qper = {}
for q in qs:
    qper.setdefault(q['doc_id'], []).append(q)

todo = []
for d, doc_qs in qper.items():
    for q in doc_qs:
        for arm in ARMS:
            for seed in (1, 2, 3):
                if (d, q['id'], arm, seed) not in have and arm in encoded.get(d, {}):
                    todo.append((d, q, arm, seed))

print(f'missing cells to fetch: {len(todo)}')
out = open('eval/results/raw.jsonl', 'a', encoding='utf-8')

for d, q, arm, seed in todo:
    doc_text = encoded[d][arm]
    prompt = (f"Document:\n{doc_text}\n\nQuestion: {q['question']}\n\n"
              f"Answer only with the exact value requested, nothing else.")
    ptoks = get_tokens(prompt)
    size_bucket = 'large' if ptoks > 50000 else ('medium' if ptoks > 10000 else 'small')

    t0 = time.time()
    pred = generate(prompt, model=MODEL, temperature=0.0, seed=seed)
    latency_ms = int((time.time() - t0) * 1000)
    gold = str(q['answer'])
    row = {
        'doc_id': d, 'size_bucket': size_bucket, 'arm': arm, 'model': MODEL,
        'question_id': q['id'], 'qtype': q['type'], 'seed': seed,
        'prompt_tokens': ptoks, 'completion_tokens': get_tokens(pred),
        'gold': gold, 'pred': pred,
        'correct': _is_correct(q.get('type', ''), gold, pred),
        'latency_ms': latency_ms,
    }
    out.write(json.dumps(row) + '\n')
    out.flush()
    print(f'filled {d}/{arm}/seed{seed} correct={row["correct"]} '
          f'({ptoks} prompt tok, {latency_ms} ms)', flush=True)

out.close()

# verify completeness
rows = [json.loads(l) for l in open('eval/results/raw.jsonl') if l.strip()]
have = {(r['doc_id'], r['question_id'], r['arm'], r['seed']) for r in rows}
expected = {(d, q['id'], arm, s)
            for d, doc_qs in qper.items()
            for q in doc_qs
            for arm in ARMS
            for s in (1, 2, 3)}
still = expected - have
print(f'total rows now {len(rows)}; still missing: {len(still)}')
for m in sorted(still)[:10]:
    print('  ', m)