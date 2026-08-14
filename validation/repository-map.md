# Phase 1: Repository Reconnaissance

## Architecture Components

1. **IR (Intermediate Representation)**
   - Location: `tdf/ir.py`
   - Responsibility: Abstract data model for document elements (Doc, Block, Para, Table, ListBlock, etc.).
   - Assumptions: Documents form a hierarchy of Block elements.
2. **Parser**
   - Location: `tdf/parse.py`
   - Responsibility: Parses raw TDF string back to IR.
   - Input: TDF string.
   - Output: `Doc` IR object.
   - Known limitations: Assumes syntactically valid TDF; falls back on bad parses.
3. **Renderer / TDF Encoder**
   - Location: `tdf/emit.py`
   - Responsibility: Translates IR into TDF tokens (and markdown, skeleton).
   - Input: `Doc` object.
   - Output: TDF string.
4. **TDF Decoder**
   - Same as parser (`tdf/parse.py`).
5. **Fidelity Metrics**
   - Location: `tdf/fidelity.py`
   - Responsibility: Compares two IR trees (typically original vs round-trip) using distinct vocabulary/token recall.
   - Metrics: `distinct_recall`.
6. **CLI**
   - Location: `tdf/cli.py`
   - Responsibility: Command-line interface for `convert`, `stats`, `validate`.
7. **Validation**
   - Location: `tdf/validate.py`
   - Responsibility: Checks structural validity invariants (rectangular tables, logical lengths).
8. **Benchmark**
   - Location: `bench/benchmark.py`, `bench/bench_llmlingua.py`
   - Responsibility: Compares tokens and performance against LLMLingua and MarkItDown.
9. **Tests**
   - Location: `tests/` (`test_tdf.py`, `test_properties.py`)
   - Responsibility: Unit testing and Hypothesis property-based testing.
