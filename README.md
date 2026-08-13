# TDF — Token-Dense Format

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Tests](https://github.com/meashumishra/TDF-Token-Dense-Format-/actions/workflows/ci.yml/badge.svg)](https://github.com/meashumishra/TDF-Token-Dense-Format-/actions/workflows/ci.yml)

A document format and converter designed specifically for LLMs, with **zero measured content loss**. Savings scale with how structured the document is: **28–66%** below Markdown on table-heavy and boilerplate-heavy documents (PDFs, spreadsheets, HTML), dropping to single digits on prose-heavy documents where Markdown was already near-optimal — see [Benchmarks](#benchmarks). It includes a *skeleton mode* to map documents for **~99% fewer tokens**, and robust parsing backed by property-based fuzzing.

```
pdf docx xlsx pptx html md csv txt  ──►  TDF  ──►  your LLM
```

![tdf stats demo](docs/demo.gif)

## The Problem

Every LLM tool accepts document uploads. Under the hood, they convert the file to Markdown and paste it into the context window. That conversion is where the money and context window goes. Markdown was designed in 2004 for human readability, not token efficiency. 

Pipes in tables (`|`), repeating header cells, and standard formatting drastically inflate token counts. For table-heavy documents, formatting overhead is almost half the total token cost.

## Why TDF?

TDF solves this by introducing a line-oriented, token-optimized, plain-text format specifically engineered for BPE tokenizers.

* **100% Fidelity (Lossless):** Unlike prompt compression tools (like LLMLingua) that destructively shrink text, TDF achieves its compression purely through format optimization, structural normalization, and dictionary coding. Data is never lost.
* **Instant Conversion:** Runs instantly without requiring a GPU or a local LLM inference step.
* **Advanced Table Handling:** Borderless PDF table detection, rectangular grid enforcement, and columnar dictionary coding (Parquet/ORC concepts applied to LLM tokens).
* **Addressable Elision:** TDF can identify low-density structural boilerplate (like giant website nav trees) and replace it with a token-cheap `!E` marker. The LLM can retrieve the original if needed.
* **Strict Validation:** A formal grammar and validator guarantee TDF outputs are structurally perfect. Malformed inputs result in safe fallbacks, never data loss.

## Benchmarks

We measured TDF against standard Markdown, MarkItDown (Microsoft's standard converter), and LLMLingua (a popular prompt compression model). 

**Token Compression vs Markdown:**

| Document | TDF Saving vs MD | TDF Saving vs MarkItDown | Recall (Fidelity) |
|---|---|---|---|
| operating_review.pdf | **65.8%** | **65.7%** | 100.0% |
| services_agreement.docx | **47.1%** | **47.8%** | 100.0% |
| orders.csv | **45.7%** | **45.7%** | 100.0% |
| quarterly_deck.pptx | **37.5%** | **38.4%** | 100.0% |
| handbook.html | **43.2%** | **43.2%** | 100.0% |
| runbook.md | **28.0%** | **28.0%** | 100.0% |

These are structured/table-heavy documents, where TDF's gains are largest. On prose-heavy, out-of-training documents savings are smaller — `sec_filing.html` (42.9%), `attention.pdf` (12.9%), `kubernetes_docs.html` (2.0%) — because there's less table/boilerplate overhead for TDF to strip out and Markdown is already close to token-optimal for plain prose. Full numbers: [`bench/results_samples_real.md`](bench/results_samples_real.md).

**TDF vs LLMLingua (Lossless vs Lossy):**

TDF's numbers below use `--no-legend` mode (the fairest match to LLMLingua's raw compressed output, which has no self-describing header either); with the default legend-on output, `handbook.html` saves 43.2% instead of 47.9% (see table above).

| Document | Markdown Tokens | TDF Tokens (Savings, no-legend) | LLMLingua Tokens (Savings) | LLMLingua CPU Time |
|---|---|---|---|---|
| sec_filing.html | 26,587 | 15,032 (43.5%) | 14,728 (44.6%) | 14.33s |
| handbook.html | 4,732 | 2,464 (47.9%) | 3,084 (34.8%) | 1.94s |

*LLMLingua destroys table structure, strips out rows randomly, merges columns, and drops critical values to achieve its compression. **TDF achieves similar or better compression (43-47%) natively during conversion with 100% semantic fidelity.***

## Installation

```bash
pip install tdf-converter
```

Or install from source:

```bash
git clone https://github.com/meashumishra/TDF-Token-Dense-Format-.git
cd TDF-Token-Dense-Format-
pip install .
```

## Usage

Use the CLI to convert your documents:

```bash
# Convert a document to TDF
tdf convert document.pdf --to tdf -o output.tdf

# Get a high-level summary skeleton (~99% smaller)
tdf convert large_report.docx --to skeleton

# Validate a TDF file against structural invariants
tdf validate output.tdf

# Print tokens and format stats for a file
tdf stats orders.csv
```

## How It Works

For a deep dive into the research, algorithmic decisions (Token-cost-weighted Re-Pair, Addressable Elision, Sentence Density tiering), and the exhaustive bug-hunting campaigns that hardened TDF, read the [Architecture & Research Notes](ARCHITECTURE.md).

## Known limitations

- **Small documents can come out larger.** `prose_only.pdf` is 222 Markdown tokens but 252 in TDF, because the ~130-token self-describing legend dominates. Below roughly 500 tokens, use `--no-legend`.
- **Scanned/image PDFs are not handled** — there is no OCR step. Pair with olmOCR or Chandra first.
- **Dictionary substitution hurts raw prose readability.** `...at the start of §3 1.` expands losslessly but reads badly to humans (though models handle it fine).
- **Fidelity is content recall, not structural equivalence.** It proves no meaning-bearing term is lost.

## License

MIT License. See [LICENSE](LICENSE) for details.
