# Phase 2: Claim Extraction

**Claim 1:**
- Claim: TDF reduces LLM token usage (28–66% below Markdown on structured/table-heavy documents).
- Source: README.md
- Current Status: Needs to be verified against the baseline benchmark and an expanded dataset.

**Claim 2:**
- Claim: Zero measured content loss / 100% Distinct-Content Recall (Every meaning-bearing term survives the round-trip).
- Source: README.md
- Current Status: Requires verification through adversarial testing to ensure structural integrity doesn't alter meaning despite bag-of-words recall.

**Claim 3:**
- Claim: Skeleton mode yields ~99% smaller footprint.
- Source: README.md
- Current Status: Needs to be verified if the skeleton representation actually enables useful retrieval (LLM QA).

**Claim 4:**
- Claim: Comparable or better compression than LLMLingua but Content-Preserving (lossy vs non-lossy on distinct terms).
- Source: README.md
- Current Status: Compare on QA benchmarks rather than just token counts.

**Claim 5:**
- Claim: TDF performs well across different tokenizers.
- Source: Implicitly required by "designed specifically for LLMs" and "BPE tokenizers".
- Current Status: Benchmark script only runs with `o200k_base` (tiktoken). Must test other tokenizers.
