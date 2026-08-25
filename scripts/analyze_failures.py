"""Phase 5: mine the eval run for WHY TDF loses accuracy vs Markdown.

Pairs every (doc, question, seed) triple across arms, isolates the
TDF-loss bucket (md correct, tdf_full wrong), and categorises each failure
by root cause using the actual wire representation:

  empty_pred            model returned nothing
  encoded_away          gold string absent from the wire entirely (caret /
                        codebook / hygiene removed the literal) and not
                        recoverable from any dictionary entry
  dict_covered          gold absent from body but present in a !D phrase --
                        answerable only via indirection
  scorer_strict         gold IS contained in the prediction but the strict
                        matcher rejected it (possible scorer false negative)
  deref_leak            prediction looks like a raw code letter / short token
                        where gold is a resolved value
  other                 none of the above

Outputs:
  eval/results/failures.json   every categorized failure record
  stdout                       ranked failure-mode table + headline stats
"""

import json
import sys
from collections import Counter, defaultdict
from copy import deepcopy
from pathlib import Path

sys.path.insert(0, str('.'))
from eval.formats.encode import ARMS  # noqa: E402

ROOT = Path('.')
rows = [json.loads(l) for l in open('eval/results/raw.jsonl') if l.strip()]
qs = {q['id']: q for q in json.load(open('eval/questions/questions.json'))}

docs = {}
for p in Path('eval/corpus/perturbed').glob('*.pkl'):
    import pickle
    with open(p, 'rb') as f:
        docs[p.stem] = pickle.load(f)

# ---- encode the two arms we compare -----------------------------------------
wires = {}
for arm in ('md', 'tdf_full'):
    for d, doc in docs.items():
        try:
            wires[(d, arm)] = ARMS[arm](deepcopy(doc))
        except Exception as e:
            print(f'ENCODE FAIL {d}/{arm}: {e}', file=sys.stderr)

# dictionary coverage per tdf wire (gold hidden inside a !D phrase?)
from tdf.parse import parse_tdf  # noqa: E402
dict_phrases = {}
for (d, arm), w in list(wires.items()):
    if arm != 'tdf_full':
        continue
    meta = parse_tdf(w).meta.get('dictionary', [])
    phrases = []
    for e in meta:
        phrase = e[0] if isinstance(e, tuple) else None
        if phrase:
            phrases.append(phrase)
    dict_phrases[d] = phrases


def gold_visible(gold: str, doc_id: str, wire: str) -> str:
    g = str(gold).strip()
    if not g:
        return 'no_gold'
    if g in wire:
        return 'present'
    for ph in dict_phrases.get(doc_id, []):
        if g and g in ph:
            return 'dict_covered'
    return 'absent'


def norm(s: str) -> str:
    return ' '.join(str(s).lower().split())


# ---- pair up -----------------------------------------------------------------
by_key = defaultdict(dict)
meta_of = {}
for r in rows:
    k = (r['doc_id'], r['question_id'], r['seed'])
    by_key[k][r['arm']] = r
    meta_of[k[1]] = qs.get(k[1], {})

records = []
loss_by_qtype = Counter()
cat_by_qtype = defaultdict(Counter)
win_by_qtype = Counter()

for k, arms in sorted(by_key.items()):
    doc_id, qid, seed = k
    if 'md' not in arms or 'tdf_full' not in arms:
        continue
    md_r, tf_r = arms['md'], arms['tdf_full']
    qtype = meta_of[qid].get('type', 'unknown')
    if md_r['correct'] and not tf_r['correct']:
        loss_by_qtype[qtype] += 1
        gold, pred = tf_r['gold'], tf_r['pred']
        wire = wires.get((doc_id, 'tdf_full'), '')
        vis = gold_visible(gold, doc_id, wire)
        ng, np_ = norm(gold), norm(pred)
        # gpt-oss-120b is a REASONING model: it spends completion tokens
        # thinking before answering. EVAL_MAX_TOKENS=256 truncates most runs
        # (see REPORT.md caveat); a truncated prediction is an artifact of
        # the budget, not evidence about the representation -- classify it
        # separately so the confound is visible instead of laundered into
        # 'other_wrong'.
        if tf_r.get('completion_tokens', 0) >= 250:
            cat = 'reasoning_truncated'
        elif not np_.strip():
            cat = 'empty_pred'
        elif vis == 'absent':
            cat = 'encoded_away'
        elif vis == 'dict_covered':
            cat = 'dict_covered'
        elif ng in np_:
            cat = 'scorer_strict'
        elif len(np_) <= 2 and len(ng) > 2 and np_.isalpha() and np_.islower():
            cat = 'deref_leak'
        else:
            cat = 'other_wrong'
        cat_by_qtype[qtype][cat] += 1
        records.append({
            'doc_id': doc_id, 'question_id': qid, 'seed': seed,
            'qtype': qtype, 'category': cat,
            'gold': gold[:120], 'pred': pred[:200],
            'question': meta_of[qid].get('question', '')[:160],
            'prompt_tokens': tf_r['prompt_tokens'],
            'completion_tokens': tf_r['completion_tokens'],
        })
    elif tf_r['correct'] and not md_r['correct']:
        win_by_qtype[qtype] += 1

total_loss = sum(loss_by_qtype.values())
total_win = sum(win_by_qtype.values())

print(f'TDF-loss triples: {total_loss} | TDF-win triples: {total_win} '
      f'| net TDF-vs-MD loss: {total_win - total_loss}')

print('\n== TDF losses by question type (top 15) ==')
for qt, n in loss_by_qtype.most_common(15):
    wins = win_by_qtype.get(qt, 0)
    print(f'  {qt:22s} losses={n:4d} wins={wins:3d} net={wins - n:+d}')

print('\n== Category mix per top loss type ==')
for qt, _ in loss_by_qtype.most_common(8):
    print(f'  {qt}: {dict(cat_by_qtype[qt])}')

cat_totals = Counter()
for qt in cat_by_qtype:
    for c, n in cat_by_qtype[qt].items():
        cat_totals[c] += n
print('\n== Root-cause totals (all losses) ==')
for c, n in cat_totals.most_common():
    print(f'  {c:16s} {n:4d}')

clusters = [(f'{qt}:{c}', n) for qt in cat_by_qtype for c, n in
            cat_by_qtype[qt].items()]
clusters.sort(key=lambda x: -x[1])
print('\n== Top 20 failure clusters (qtype:category) ==')
for name, n in clusters[:20]:
    print(f'  {n:4d}  {name}')

out = {
    'totals': {'tdf_losses': total_loss, 'tdf_wins': total_win,
               'root_causes': dict(cat_totals)},
    'failures': records,
}
Path('eval/results').mkdir(exist_ok=True)
with open('eval/results/failures.json', 'w') as f:
    json.dump(out, f, indent=1, ensure_ascii=False)
print('\nwrote eval/results/failures.json '
      f'({len(records)} records)')