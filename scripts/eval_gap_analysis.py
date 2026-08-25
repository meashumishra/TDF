"""One-off: compare raw.jsonl against the full expected eval matrix."""
import json
from collections import Counter, defaultdict
from pathlib import Path

rows = [json.loads(l) for l in open('eval/results/raw.jsonl') if l.strip()]
print(f'rows: {len(rows)}')
print('models:', dict(Counter(r['model'] for r in rows)))
print('arms:', dict(Counter(r['arm'] for r in rows)))
print('docs:', dict(Counter(r['doc_id'] for r in rows)))

qs = json.load(open('eval/questions/questions.json'))
print(f'questions: {len(qs)}; per doc:', dict(Counter(q["doc_id"] for q in qs)))

corpus = sorted(p.stem for p in Path('eval/corpus/perturbed').glob('*.pkl'))
print('corpus pkls:', corpus)

ARMS = ['json', 'md', 'tdf_full', 'tdf_hoist', 'tdf_nocodes',
        'tdf_nodict', 'tdf_nocaret', 'toon']
qper = defaultdict(list)
for q in qs:
    qper[q['doc_id']].append(q['id'])

expected = {(d, qid, a, s)
            for d, doc_qs in qper.items() if d in corpus
            for qid in doc_qs
            for a in ARMS
            for s in (1, 2, 3)}
have = {(r['doc_id'], r['question_id'], r['arm'], r['seed']) for r in rows}
missing = expected - have
extra = have - expected
print(f'expected={len(expected)} have={len(have)} missing={len(missing)} extra={len(extra)}')
print('missing by arm:', dict(Counter(m[2] for m in missing)))
print('missing by doc:', dict(Counter(m[0] for m in missing)))
print('duplicate rows:', len(rows) - len(have))

# how many of the missing are already answered in the response cache?
import hashlib
import pickle
import sys

sys.path.insert(0, str('.'))
from eval.formats.encode import ARMS  # noqa: E402

cache_dir = Path('eval/runner/.cache')
MODEL = 'openai/gpt-oss-120b'

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

cached = missing_api = 0
for (d, qid, arm, seed) in sorted(missing):
    qrow = next(q for q in qs if q['id'] == qid)
    doc_text = encoded.get(d, {}).get(arm)
    if doc_text is None:
        missing_api += 1
        continue
    prompt = f"Document:\n{doc_text}\n\nQuestion: {qrow['question']}\n\nAnswer only with the exact value requested, nothing else."
    key = hashlib.sha256(f"{prompt}|{MODEL}|{seed}".encode()).hexdigest()
    if (cache_dir / f"{key}.json").exists():
        cached += 1
    else:
        missing_api += 1

print(f'missing cells with cached response: {cached}')
print(f'missing cells needing a real API call: {missing_api}')
