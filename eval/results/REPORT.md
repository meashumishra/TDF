# TDF Accuracy-Per-Token Eval Report

No real evaluation run has been performed yet. A previous version of this file and `pareto.png` contained fabricated/simulated numbers (the harness's mock LLM client invented accuracies rather than requiring a real API key) that were never marked as synthetic and were indistinguishable from real results on inspection -- see the independent audit's NEW-1 finding. Both have been removed. `eval/runner/client.py` now requires a real API key and raises rather than fabricating a result; re-run the harness (`eval/runner/run.py`) to produce genuine numbers here.
