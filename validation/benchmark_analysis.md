# Phase 9: Tokenizer Validation

Tested TDF on `samples` corpus using two different major OpenAI BPE tokenizers:
- `o200k_base` (GPT-4o)
- `cl100k_base` (GPT-4, GPT-3.5)

**Results (TDF without legend vs MD):**
- `o200k_base`: Savings ranged from 44.4% (`runbook.md`) to 72.0% (`operating_review.pdf`).
- `cl100k_base`: Savings ranged from 45.1% (`runbook.md`) to 71.8% (`operating_review.pdf`).

**Conclusion:** 
The token reduction percentages are extremely stable across BPE tokenizers. The core mechanism of stripping formatting punctuation (`|`, `-`) and compressing identical lines using `!D` dictionaries generalizes well. 

# Phase 8: Statistical & Dataset Analysis
- TDF's largest gains (60-70%) appear strictly on tabular/structured documents (e.g. `operating_review.pdf`).
- On prose-heavy out-of-training documents (e.g. `attention.pdf` from `samples_real`), savings drop significantly (9-13%).
- Claim 4 ("TDF is particularly effective for structured and table-heavy documents") is VERIFIED.

# Phase 11 & 12: LLMLingua & QA Comparison
- `bench_llmlingua.py` exists and successfully proved TDF preserves distinct content while LLMLingua mangles tables at similar compression rates.
- However, there is no end-to-end LLM QA test framework in the repository yet.
- The claim that TDF "preserves LLM question-answering accuracy" remains an extrapolation from "100% distinct content recall". It is highly probable, but not explicitly verified by a benchmark in this repo.
