# Phase 5: Attack the Fidelity Metric

Tested the `tdf.fidelity.compare` function with semantic-reversal edge cases.

1. **Sentence Reversal**
   `Alice reports to Bob.` vs `Bob reports to Alice.`
   - Results in `distinct_recall = 1.0` (100%).
   - The metric operates on unique vocabulary tokens. It entirely ignores word order. Thus, semantic destruction (like swapping subject and object) is NOT caught by the fidelity checker if the same words exist in the document.

2. **Table Value Reversal**
   `10 | 20` vs `20 | 10`
   - The fidelity metric uses `split()` and set comparison. If a table's columns are swapped, the content-token recall remains 1.0 (100%) because "10" and "20" still exist in the output block.

**Conclusion:** 
The fidelity metric guarantees that no vocabulary/tokens are lost (a necessary condition for lossless transmission), but it is **not** a measure of semantic fidelity or structural equivalence. Content-token recall does not equal semantic preservation.

The README changes already committed ("100% distinct-content recall") are accurate and the term "semantic fidelity" should be avoided when referencing the `compare()` output.
