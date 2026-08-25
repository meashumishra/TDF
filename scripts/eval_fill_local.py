"""Fill the missing eval cells using a LOCAL model (no external API).

Integrity rules:
- Rows are tagged with the local model id so they are never silently blended
  with the primary gpt-oss-120b corpus; eval/scoring/stats.py excludes
  non-dominant-model rows from headline statistics and cross-model pairing.
- Prompts are byte-identical to runner/run.py's construction.
"""
import json
import pickle
import sys
import time
from pathlib import Path

sys.path.insert(0, str('.'))
import torch  # noqa: E402
from eval.formats.encode import ARMS  # noqa: E402
from eval.runner.run import _is_correct, get_tokens  # noqa: E402

MODEL_ID = "Qwen/Qwen2.5-0.5B-Instruct"

rows = [json.loads(l) for l in open('eval/results/raw.jsonl') if l.strip()]
qs = json.load(open('eval/questions/questions.json'))
ARMS_ORDER = list(ARMS)
have = {(r['doc_id'], r['question_id'], r['arm'], r['seed']) for r in rows}

docs = {}
for p in Path('eval/corpus/perturbed').glob('*.pkl'):
    with open(p, 'rb') as f:
        docs[p.stem] = pickle.load(f)

todo = []
qper = {}
for q in qs:
    qper.setdefault(q['doc_id'], []).append(q)
for d, doc_qs in qper.items():
    for q in doc_qs:
        for arm in ARMS_ORDER:
            for s in (1, 2, 3):
                if (d, q['id'], arm, s) not in have:
                    todo.append((d, q, arm, s))
print(f'missing cells: {len(todo)}')

print(f'loading {MODEL_ID} on mps...', flush=True)
from transformers import AutoModelForCausalLM, AutoTokenizer  # noqa: E402

tok = AutoTokenizer.from_pretrained(MODEL_ID)
model = AutoModelForCausalLM.from_pretrained(
    MODEL_ID, dtype=torch.bfloat16).to('mps')
model.eval()
print('loaded.', flush=True)

out = open('eval/results/raw.jsonl', 'a', encoding='utf-8')
for d, q, arm, seed in todo:
    doc_text = ARMS[arm](docs[d])
    prompt = (f"Document:\n{doc_text}\n\nQuestion: {q['question']}\n\n"
              f"Answer only with the exact value requested, nothing else.")
    ptoks = get_tokens(prompt)
    size_bucket = 'large' if ptoks > 50000 else ('medium' if ptoks > 10000 else 'small')

    chat = tok.apply_chat_template(
        [{"role": "user", "content": prompt}],
        add_generation_prompt=True, tokenize=False)
    enc = tok(chat, return_tensors="pt").to('mps')
    t0 = time.time()
    with torch.no_grad():
        gen = model.generate(**enc, max_new_tokens=256, do_sample=False)
    latency_ms = int((time.time() - t0) * 1000)
    pred = tok.decode(gen[0][enc['input_ids'].shape[1]:], skip_special_tokens=True)

    gold = str(q['answer'])
    row = {
        'doc_id': d, 'size_bucket': size_bucket, 'arm': arm,
        'model': f'local/{MODEL_ID}', 'question_id': q['id'],
        'qtype': q['type'], 'seed': seed, 'prompt_tokens': ptoks,
        'completion_tokens': get_tokens(pred), 'gold': gold, 'pred': pred,
        'correct': _is_correct(q.get('type', ''), gold, pred),
        'latency_ms': latency_ms,
    }
    out.write(json.dumps(row) + '\n')
    out.flush()
    print(f"filled {d}/{arm}/seed{seed}: pred={pred[:60]!r} "
          f"correct={row['correct']} ({latency_ms} ms)", flush=True)

out.close()

# completeness check across ALL models
rows = [json.loads(l) for l in open('eval/results/raw.jsonl') if l.strip()]
have = {(r['doc_id'], r['question_id'], r['arm'], r['seed']) for r in rows}
expected = {(d, q['id'], arm, s)
            for d, doc_qs in qper.items() if d in docs
            for q in doc_qs
            for arm in ARMS_ORDER
            for s in (1, 2, 3)}
still = expected - have
print(f'total rows now {len(rows)}; still missing: {len(still)}')