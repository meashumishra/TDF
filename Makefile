.PHONY: test corpus perturb perf reproduce

test:
	python -m pytest tests/ -q

# Phase 6: fetch/synthesise new corpus families, then fold into perturbed/
corpus:
	python -m eval.corpus.expand
	python -m eval.corpus.perturb

perf:
	python scripts/perf_benchmark.py --max-kb 1024

# One-command reproduction of the locally-runnable evidence chain.
# (Accuracy re-runs additionally require an API endpoint: see
# eval/results/REPORT.md provenance and EVAL_MAX_TOKENS guidance.)
reproduce: test corpus perf