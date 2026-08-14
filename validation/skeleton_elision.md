# Phase 15 & 16: Skeleton Mode & Elision

1. **Skeleton Mode**
   - The benchmark logs confirm skeleton mode yields dramatic token reductions (e.g. 358,388 -> 1,325 tokens, a 99.6% reduction on `samples_real`).
   - Claim 11 ("TDF skeleton mode provides useful context reduction"): The token reduction is VERIFIED. However, whether it provides *useful* context reduction for a two-pass LLM retrieval workflow is NOT VERIFIED in the repository via a formalized test, though the architectural principles are sound.

2. **Addressable Elision**
   - Elision marks low-density structures with `!E`. 
   - By definition, elision is lossy (it drops data to save tokens). The README clarifies that Elision mode drops boilerplate.
   - Claim 12 ("Elision/tiering works correctly and safely"): VERIFIED that it shrinks token size and injects a distinct marker (`!E`), but similar to skeleton mode, the multi-turn LLM interaction to fetch the elided content is not tested end-to-end.
