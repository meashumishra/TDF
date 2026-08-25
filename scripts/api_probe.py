"""Minimal connectivity probe for the eval API endpoint."""
import sys
import time

sys.path.insert(0, '.')
from eval.runner.client import generate

t0 = time.time()
try:
    r = generate('Reply with exactly: OK',
                 model='openai/gpt-oss-120b', temperature=0.0, seed=1)
    print('PROBE OK in', round(time.time() - t0, 1), 's ->', repr(r[:60]))
except Exception as e:
    print(f'PROBE FAILED after {time.time()-t0:.1f}s -> '
          f'{type(e).__name__}: {e}')