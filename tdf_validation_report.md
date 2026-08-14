TDF VALIDATION
==============

Core format:              PASS
Round-trip correctness:   PASS
Structural fidelity:      FAIL (Hypothesis fuzzing revealed structure loss like caption newline shifting and codebook drops, and table column width padding changes structure)
Semantic fidelity:        PASS
Token efficiency:         PASS
Tokenizer robustness:     INCONCLUSIVE (Only tested heavily on o200k_base proxy, others not tested)
LLM QA preservation:      PASS
Skeleton mode:            PASS
Elision mode:             PASS
Performance:              PASS
Security/robustness:      PASS

Overall:
PROMISING

Strongest evidence:
The benchmarks on `samples` and `samples_real` consistently show 28-66% token reduction compared to Markdown for structured documents, backed by a rigorous fidelity checker (`tdf.fidelity.compare`) and property-based testing (Hypothesis) that ensure no raw text tokens are lost.

Biggest weakness:
The claim of "100% Fidelity (Lossless)" and "Data is never lost" is overstated and contradicted by features like Addressable Elision (which drops entire structural blocks) and `Table.__post_init__` padding (which invents empty cells to force rectangular grids). Additionally, the fidelity metric only measures "distinct-content recall" (bag-of-words presence), which is blind to structural corruption.

Most important next experiment:
Test token savings and QA accuracy across multiple tokenizers (e.g., Llama 3, Gemini, Claude) to ensure the ASCII-based assumptions (like space separators saving tokens) hold universally, and run the GSM8K/BBH benchmarks as suggested in the lit survey to ensure number/symbol normalization doesn't break reasoning.

README claims that must change:
1. "100% Fidelity (Lossless)... Data is never lost" -> Must be qualified. Normal mode has 100% *distinct-content recall*, but Addressable Elision is explicitly lossy, and structural whitespace/formatting is intentionally discarded.
2. "zero measured content loss" -> Should clarify that this refers to the specific `distinct-content recall` metric, not bit-for-bit lossless compression.
3. The LLMLingua comparison calls TDF completely "lossless", which conflates content recall with structural preservation.
