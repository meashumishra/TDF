"""Remediation coverage: is the gold SEMANTICALLY present after encoding?

For every categorized Phase-5 failure, check whether the gold's tokens are
fully contained in the content-bag of the PARSED document (parse(encode(doc)))
for both tdf_full and tdf_nocaret0. Parsing re-inserts hoisted constant
columns and expands ^ / dictionary references, so "present" here means
recoverable-in-principle -- a much stricter test than substring search.
"""
import json
import pickle
import sys
from copy import deepcopy
from pathlib import Path

sys.path.insert(0, str('.'))
from eval.formats.encode import ARMS  # noqa: E402
from tdf.fidelity import _tokenize  # noqa: E402
from tdf.parse import parse_tdf  # noqa: E402

docs = {p.stem: pickle.load(open(p, 'rb'))
        for p in Path('eval/corpus/perturbed').glob('*.pkl')}

fails = json.load(open('eval/results/failures.json'))['failures']
arms = ('tdf_full', 'tdf_nocaret0')

from collections import Counter  # noqa: E402

from tdf.fidelity import content_bag  # noqa: E402

bags = {}
for d, doc in docs.items():
    per_arm = {}
    for arm in arms:
        wire = ARMS[arm](deepcopy(doc))
        per_arm[arm] = content_bag(parse_tdf(wire))
    bags[d] = per_arm

from collections import Counter  # noqa: E402

presence = Counter()
hard = []
for r in fails:
    g = set(_tokenize(str(r['gold']).lower()))
    if not g:
        presence['no_gold'] += 1
        continue
    states = []
    for arm in arms:
        pbag = bags[r['doc_id']][arm]
        present = g.issubset(pbag)
        states.append(present)
    key = tuple(states)          # (full_present, nocaret_present)
    presence[key] += 1
    if not all(states):
        hard.append((r, states))

print('presence (full, nocaret0) -> count:')
for k, n in sorted(presence.items(), key=lambda kv: -kv[1]):
    print(f'  {k}: {n}')
print('\nHard cases (not fully present in either):')
for r, st in hard[:10]:
    print(f"  [{r['qtype']}] {r['question_id']} gold={r['gold'][:50]!r}")