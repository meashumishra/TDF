# Unoccupied Territory — What TDF Could Do That Nobody Is Doing

*Companion to `lit_survey.md`. Landscape re-verified 2026-08-24 against live
sources: TOON (25.2k★, JSON-only, ecosystem growing), MarkItDown (176k★,
Markdown-only, no token awareness), Docling (65.5k★, VLM-oriented DocTags),
LLMLingua family (model-dependent, lossy; team's public focus has moved to
KV-cache systems work: SCBench, RetrievalAttention, MInference).*

## The one-line thesis

Everyone is competing on *extraction quality* (Docling, Marker, MinerU) or
*serialization compactness* (TOON) or *lossy semantic pruning* (LLMLingua).
Nobody is working on the layer in between: **the document as a managed,
measurable, incrementally-updated object inside an agent's context.** That
layer is exactly what this repo already has unusual pieces of.

---

## Ranked opportunities

### 1. Format-native lazy context over MCP (the elision loop, closed)

`!E` markers declare sized, gisted omissions; `expand-elided` resolves them;
`skeleton` + `extract_sections` serve partial views. But today that loop is
closed by a human or a clever prompt. **No tool ships a document server where
the model itself navigates:** `open_document(path)` returns the tiered
skeleton, `expand(id)` streams back exactly that region with its declared
token count, `diff(version_b)` sends only `!DIFF`.

- Prior art check: Tooner (MCP proxy → TOON) minifies *tool responses*, not
  documents, and has no expansion protocol. Anthropic's just-in-time context
  guidance is agentic folklore, not a file format. PageIndex builds retrieval
  trees but emits no in-band omission markers. The lit survey's novelty claim
  survives — and becomes stronger as an interactive protocol.
- Why now: agents are the consumers; MCP is the distribution channel.
- Assets reused: tier.py, expand-elided, extract_sections, diff.py — all exist.
- First milestone: reference MCP server + a measured "tokens-to-answer"
  comparison vs stuff-the-whole-document and vs RAG on the same corpus.

### 2. Publish the accuracy-per-token frontier as a living benchmark

The preregistered harness (`eval/`) with decision rules set before results is
itself unusual. Productized — versioned corpus, multiple models, arms for each
mechanism (`!V`, `§n`, `^`, periodic headers), published curves + a badge —
this becomes *the* reference for the category, the way llm-perfLeaderboards
own theirs. TOON published one static benchmark; nobody maintains a living
accuracy-vs-tokens frontier for **document encodings** (as opposed to JSON
serialization).

- This also discharges the repo's single biggest liability: the README admits
  accuracy impact is unmeasured. Owning the benchmark converts the weakness
  into the moat.
- Prerequisite: finish the pending real-API run already sitting in raw.jsonl.

### 3. Cache-aware emission (KV-cache locality as a format property)

Providers bill cached prefix tokens at a steep discount, yet **no converter
considers cache topology**: codebooks and legends placed identically across
corpus files, stable block ordering, deterministic ids, and — the interesting
one — `tdf diff` emitted as a *minimal-delta update* so a nightly-rebuilt
document reuses most of the cached prefix instead of invalidating it.

- Why nobody does it: extraction tools think in single documents; cache
  thinking requires corpus-level and temporal reasoning. Both sides are
  missing the middle.
- Evidence of relevance: Microsoft's own LLMLingua follow-ups (SCBench et al.)
  all evaluate from the KV-cache perspective — at the eviction layer. The
  text-format layer above it is empty.
- Measurable claim: end-to-end cost including cache hits, not naive
  tokens-sent. That metric doesn't exist anywhere public either.
- Assets reused: diff.py (!DIFF is already a structural delta), deterministic
  emit (same doc → same bytes), validate.py fixed-point checks.

### 4. Structure-preserving chunking for RAG

Every major framework chunks on token windows and routinely cuts tables
mid-row, destroying column association — the exact failure mode the table-
serialization literature shows is catastrophic for QA accuracy. TDF's IR knows
where blocks and rows are; periodic headers (already implemented) can be
re-injected per chunk so every chunk is self-describing.

- Positioning: not "use our format," but "steal our chunker" — a drop-in
  better splitter for LangChain/LlamaIndex, which is also the widest possible
  distribution channel for everything else here.
- Nobody ships a semantics-aware chunker with round-trip guarantees.

### 5. Compression receipts (auditability)

`tdf verify` already computes recall ratios and the elision manifest. Emit a
signed receipt alongside any compressed context: source hash, encoder version,
recall numbers, list of elisions with sizes, page provenance. Regulators
(EU AI Act high-risk obligations) and enterprises buying document AI want
exactly this and can get it from nowhere else. Cheap to build, zero
competition, unglamorous but real differentiation in procurement.

---

## Deliberately not recommended (yet)

- **Query-conditional density** — LongLLMLingua occupies query-aware
  compression with a model in the loop; a model-free router is thinner
  differentiation until the accuracy harness lands.
- **Fine-tuning models to read TDF** — interesting research, wrong order:
  the format must first prove itself legend-only (the pending eval).
- **CJK/multilingual tokenizer hardening** — flagged in lit_survey.md as a gap
  *nobody* addresses, including TDF; necessary engineering, not a headline.

## Suggested sequence

1. Land the accuracy eval (unblocks #2, de-risks everything).
2. Ship the MCP lazy-context server (#1) — highest novelty-per-effort, all parts built.
3. Add cache-hit-aware cost reporting to bench (#3's measurement half).
4. Extract the chunker (#4) once hybrid emission lands (roadmap item that pairs naturally).
