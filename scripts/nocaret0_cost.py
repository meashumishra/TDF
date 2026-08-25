"""Token-cost comparison: tdf_full vs tdf_nocaret0 across the corpus."""
import pickle
import sys
from copy import deepcopy
from pathlib import Path

sys.path.insert(0, str('.'))
from eval.formats.encode import ARMS  # noqa: E402
from tdf.tokens import count  # noqa: E402

print(f'{"doc":16s} {"md":>8s} {"tdf_full":>9s} {"nocaret0":>9s} {"cost":>7s}')
for p in sorted(Path('eval/corpus/perturbed').glob('*.pkl')):
    doc = pickle.load(open(p, 'rb'))
    md = count(ARMS['md'](deepcopy(doc)))
    tf = count(ARMS['tdf_full'](deepcopy(doc)))
    n0 = count(ARMS['tdf_nocaret0'](deepcopy(doc)))
    print(f'{p.stem:16s} {md:8,d} {tf:9,d} {n0:9,d} {100 * (n0 - tf) / tf:+6.1f}%')

# remediation coverage: of the 82 categorized failures, how many golds are
# now PRESENT on the nocaret0 wire?
import json  # noqa: E402

docs = {p.stem: pickle.load(open(p, 'rb'))
        for p in Path('eval/corpus/perturbed').glob('*.pkl')}
n0_wires = {d: ARMS['tdf_nocaret0'](deepcopy(doc)) for d, doc in docs.items()}
fails = json.load(open('eval/results/failures.json'))['failures']
rescued = sum(1 for r in fails
              if r['gold'] and r['gold'] in n0_wires.get(r['doc_id'], ''))
print(f'\ngold now present on nocaret0 wire for '
      f'{rescued}/{len(fails)} previously-failing records')