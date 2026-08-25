"""Print the exact missing eval matrix cells with their question details."""
import json

rows = [json.loads(l) for l in open('eval/results/raw.jsonl') if l.strip()]
qs = json.load(open('eval/questions/questions.json'))
ARMS = ['json', 'md', 'tdf_full', 'tdf_hoist', 'tdf_nocodes',
        'tdf_nodict', 'tdf_nocaret', 'toon']
have = {(r['doc_id'], r['question_id'], r['arm'], r['seed']) for r in rows}

n = 0
for q in qs:
    for arm in ARMS:
        for s in (1, 2, 3):
            k = (q['doc_id'], q['id'], arm, s)
            if k not in have:
                n += 1
                print(f"MISSING {n}: {k}")
                print(f"  question : {q['question'][:140]}")
                print(f"  gold     : {q.get('answer')!r} | type: {q.get('type')}")