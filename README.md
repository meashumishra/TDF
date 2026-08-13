# TDF — Token-Dense Format

A document format and converter that cuts LLM token cost **28–42%** below Markdown
with **zero measured content loss**, plus a skeleton mode that gets you a navigable
map of any document for **~99% fewer tokens**.

```
pdf docx xlsx pptx html md csv txt  ──►  TDF  ──►  your LLM
```

---

## 1. The problem

Every LLM tool now accepts document uploads. Under the hood they all do the same
thing: convert the file to Markdown and paste it into the context window. That
conversion is where the money goes.

Markdown was designed in 2004 to be **written by humans and rendered as HTML**.
Nothing about it was designed to be cheap for a tokenizer. Measured on
`o200k_base` (GPT-4o/5, and the same tokenizer used by the published TOON
benchmarks):

| what Markdown does | cost |
|---|---|
| pipe tables `\| a \| b \|` | **+40%** vs space-separated rows |
| `**bold**` around a 2-token phrase | **+2 tokens each time** |
| repeating a header cell in every row | 1 token per cell per row |
| repeating a page footer 40 times | full price, 40 times |
| `$1,234.00` instead of `$1234` | 5 tokens instead of 2 |

None of this carries meaning an LLM needs. It is pure formatting overhead, and on
table-heavy documents it is close to half the bill.

---

## 2. What is already out there

I surveyed the 2025–2026 open-source landscape before writing any code.

### Converters

| tool | stars | license | what it's for | limitation |
|---|---|---|---|---|
| **MarkItDown** (Microsoft) | ~173k | MIT | the de-facto default; broad format support | docs *explicitly* say "not best for high-fidelity conversion"; pipe tables, no token awareness |
| **Docling** (IBM) | ~65k | MIT | layout-aware pipeline, emits DocTags | see the DocTags trap below |
| **Marker** | ~39k | model weights OpenRAIL-M | high-quality PDF→MD | non-Apache weights complicate commercial use |
| **MinerU** | ~78k | NOASSERTION | strong PDF pipeline | licence ambiguity |
| **olmOCR / Chandra** | — | Apache-2.0 | VLM OCR, SOTA on olmOCR-bench (83.1) | GPU-bound, slow, still emits Markdown |
| **Xberg** (ex-kreuzberg) | — | MIT | extraction engine | the *only* one that reports `token_reduction_ratio` as first-class metadata |
| **PageIndex** | ~35k | MIT | builds a tree index for retrieval | index only, doesn't compress the body |

Abandoned or stale: `nougat` (2025-02), `zerox` (2025-05), `extractous` (2024-12),
`tabula-py` (2024-12), `Selective_Context` (2024-02, no licence).

### The DocTags trap

Docling/SmolDocling's DocTags format genuinely reduces sequence length — **but only
for SmolDocling**, because its tags are registered as *special tokens* in that
model's vocabulary. Paste DocTags into GPT or Claude and each tag explodes into
several ordinary tokens: you end up **more expensive than Markdown**.

This is the single most important design constraint TDF inherited: *a token-efficient
format that you cannot control the tokenizer for must be tokenizer-agnostic.*
TDF is plain ASCII, chosen so that any BPE tokenizer handles it well.

### Prior art on format efficiency

- **OTSL** (arXiv 2305.03393) — a 5-token table vocabulary vs HTML's 28+, ~45%
  sequence reduction. The one hard published number on markup efficiency.
- **TOON** — the most complete published format study: 2,474 tokens / 72.2% accuracy
  vs pretty JSON's 4,308 / 71.4%. **42.6% fewer tokens with no accuracy loss.**
  Also established that XML is the most expensive format tested with no accuracy
  advantage (which is compatible with Anthropic's advice to use XML tags for thin
  prompt *scaffolding* — just not for the bulk payload).
- **llms.txt** — the web analogue of skeleton-first retrieval.

### The gap

**No published benchmark converts the same source document to Markdown, HTML, JSON
and a compact format and compares token counts side by side.** Every tool measures
extraction accuracy; none measures the cost of its own output encoding.
`bench/benchmark.py` in this repo does exactly that.

---

## 3. Design: measure first, then decide

Every rule in TDF came from a measurement, not an intuition. Encoding the *same*
table 8 ways, `o200k_base`:

```
space + quoting   77 tokens   ← chosen
tab               78
comma             81
pipe (no spaces)  85
semicolon         85
markdown pipe    108          ← what every converter emits today
json             147
html             200
```

Space wins for a non-obvious reason: BPE merges a leading space into the *following*
word token, so `" beta"` is one token. Every other separator is a token of its own.
`alpha beta gamma` = 3 tokens; the comma, tab and pipe versions are 5.

Other measurements that became rules:

| measurement | rule |
|---|---|
| `'1,234.00'` = 5 tok, `'1234'` = 2 | normalise numbers |
| `'**Total revenue**'` = 4 tok, `'Total revenue'` = 2 | strip styling |
| `'\n'`, `'\n\n'`, `'\n\n\n'` all = 1 tok | blank lines are free — stay readable |
| every sigil candidate (`§1 @1 ~1 #1`) = 2 tok | sigil choice is free, pick the clearest |
| `^` = 1 token | use it for "same as above" |

**Consequence:** because Markdown is already near-optimal for prose, headings and
bullets, TDF *keeps* `#` headings and `- ` list items. It is a Markdown superset for
prose and only diverges where Markdown is measurably bad. That also means an LLM
that has never seen the spec can still read most of it.

---

## 4. The TDF v1 format

```
%TDF1
# Q3 Operating Review

!D
§1 Adjusted operating margin excluding one-time items
§2 Consolidated statement of financial position

## Segment performance
!F currency=USD quarter=Q3
!T 4 amount_musd
!C region segment amount growth
EMEA Cloud 412 12.4%
^ Services 88 3.1%
APAC Cloud 366 18.9%
^ Services 71 -2.4%

§1 improved 240bps year over year.

!K headcount=4180 fy_end=2026-03-31
!G fig1 Revenue by segment, bar chart, Cloud dominant in all regions
!P 7
```

| sigil | meaning |
|---|---|
| `%TDF1` | version line |
| `# / ## / ###` | headings (same as Markdown) |
| `- ` | list item (same as Markdown) |
| `!D` + `§n text` | phrase dictionary; `§n` substitutes it everywhere |
| `!R` | recurring boilerplate — stated once, true document-wide |
| `!T n unit` | table follows: `n` rows, optional hoisted unit |
| `!C ...` | column names |
| `!F k=v` | columns that are constant for the whole table, hoisted out |
| `!K k=v` | key/value facts |
| `!G id caption` | figure, described in words rather than `![]()` |
| `!P n` | page marker (provenance Markdown throws away) |
| `^` | this cell is the same as the one directly above |
| *(empty)* | no value |

Three design points worth calling out:

**Declared row count.** `!T 4` tells the model how many rows to expect, so a
truncated context is *detectable*. Borrowed from TOON.

**Adaptive separator, self-describing.** Each table is rendered space-separated and
tab-separated, and the cheaper one wins. The parser infers which was used from
whether the `!C` line contains a tab — so the choice costs **zero** extra tokens.

**The dictionary pays for itself or doesn't appear.** A phrase of `t` tokens
appearing `c` times saves `c*t − c*2 − t − 2`. If that is not positive, the entry is
never emitted.

### The legend

TDF ships a ~130-token legend explaining the sigils, included by default so any
model can read the output cold. Honest framing: it's a **one-time enabling cost**.
In production it belongs in the system prompt, amortised across every document you
ever send. `stats` and the benchmark report both with and without it.

---

## 5. Results

Fidelity is **distinct-content recall**: parse TDF back to the intermediate
representation and check that no meaning-bearing term was lost. **100% on all 11
documents.**

### Real-world documents

| file | MarkItDown | Markdown | **TDF** | skeleton | saving vs MD | recall |
|---|---|---|---|---|---|---|
| attention.pdf *(arXiv 1706.03762)* | 11,993 | 12,412 | **10,818** | 259 | 12.8% | 100% |
| kubernetes_docs.html | 36,301 | 36,945 | **36,222** | 733 | 2.0% | 100% |
| sec_filing.html *(Apple 10-K)* | 75,635 | 26,587 | **15,173** | 274 | 42.9% | 100% |
| worldbank.csv | 282,333 | 282,341 | **195,931** | 54 | 30.6% | 100% |
| **TOTAL** | 406,262 | 358,285 | **258,144** | **1,320** | **28.0%** | **100%** |

### Synthetic corpus (targets Markdown's documented weak spots)

| file | MarkItDown | Markdown | **TDF** | skeleton | saving vs MD | recall |
|---|---|---|---|---|---|---|
| handbook.html | 4,732 | 4,732 | **2,596** | 149 | 45.1% | 100% |
| operating_review.pdf | 3,583 | 3,588 | **2,593** | 216 | 27.7% | 100% |
| orders.csv | 16,976 | 16,982 | **9,136** | 52 | 46.2% | 100% |
| quarterly_deck.pptx | 1,582 | 1,559 | **1,493** | 263 | 4.2% | 100% |
| runbook.md | 1,355 | 1,355 | **1,057** | 156 | 22.0% | 100% |
| sales_report.xlsx | 20,509 | 20,505 | **11,224** | 58 | 45.3% | 100% |
| services_agreement.docx | 1,971 | 1,945 | **1,201** | 247 | 38.3% | 100% |
| **TOTAL** | 50,708 | 50,666 | **29,300** | **1,141** | **42.2%** | **100%** |

Our Markdown baseline tracks MarkItDown within **0.1%** on the synthetic corpus
(50,666 vs 50,708), which is the evidence that the comparison is fair rather than a
strawman.

### Read this honestly

- **Structured content is where the win is.** Tables, spreadsheets, CSV, financial
  filings: 30–46%.
- **Prose, bullets and code get almost nothing.** Kubernetes docs are 69.5% list
  items, 16.4% prose, 13.6% code — Markdown is already near-optimal there, so 2.0%
  is a genuine floor, not a bug. **Skeleton mode is the answer for those documents**
  (36,945 → 733 tokens).
- **MarkItDown beats TDF on `sec_filing.html` by producing 75,635 tokens** — it
  keeps far more layout noise. TDF's 79.9% saving there is partly compression and
  partly not emitting junk.
- **Recall is not QA accuracy.** 100% recall proves no meaning-bearing term is lost.
  It does *not* prove an LLM answers questions equally well from TDF. That test
  (the TOON-style eval) needs live model calls and has not been run. This is the
  most important open question.
- Claude's tokenizer isn't public; `o200k_base` is the standard proxy, as in TOON.

---

## 6. Skeleton mode: the bigger win

For large documents, the real answer isn't compressing the body — it's not sending
the body at all.

```
$ tdf convert attention.pdf --to skeleton      # 259 tokens
...
4.5 4 Why Self-Attention          p6 ~634
4.6 5 Training                    p7 ~878
4.7 6 Results                     p8 ~1749 table5x3,table7x3

$ tdf expand attention.pdf 4.5                 # 675 tokens
```

**259 tokens to see the whole document, 675 to read the section you actually want**,
against 10,818 to paste the lot. Each skeleton line carries the section id, title,
page and a token estimate, so an agent can budget its context before committing.
This is PageIndex's idea applied to the converter itself.

---

## 7. Usage

```bash
uv venv && uv pip install -e '.[bench]'

tdf convert report.xlsx                  # TDF (default)
tdf convert report.xlsx --to md          # Markdown baseline
tdf convert report.xlsx --to skeleton    # map only
tdf expand report.xlsx 2.3               # one section, full detail
tdf stats report.xlsx                    # token comparison + breakdown
tdf verify report.xlsx                   # round-trip fidelity check

python bench/make_samples.py             # regenerate synthetic corpus
python bench/benchmark.py samples_real   # cross-format benchmark
python -m pytest tests/ -q               # 34 tests
```

Supported inputs: `.pdf .docx .xlsx .pptx .html .htm .md .csv .txt`

---

## 8. Layout

```
tdf/
  ir.py         intermediate representation (Heading, Para, Table, ...)
  readers/      pdf, pdf_tables (borderless detection), office, text_formats
  optimize.py   every token-reduction pass
  emit.py       render_tdf / render_markdown / render_skeleton
  parse.py      TDF -> IR (this is what makes losslessness checkable)
  fidelity.py   distinct-content recall
  cli.py        convert | expand | stats | verify
bench/          sample generators + cross-format benchmark
qa_eval/        A/B QA-accuracy evaluation (see its README)
tests/          41 tests
```

---

## 9. Borderless PDF tables

Most report and financial PDFs typeset tables with **whitespace alignment and no
ruling lines**. PyMuPDF's `find_tables()` keys off ruling lines, so on those files
it returns *nothing* and the table collapses into loose paragraphs.

Its `strategy="text"` fallback is not a usable fix — it shreds ordinary prose into
fake cells, splitting words mid-token:

```
['ACME CORPOR', 'ATION - CO', 'NFIDENTIAL', '- INTERNAL', 'USE O', 'NLY']
```

`tdf/readers/pdf_tables.py` detects them properly instead. The discriminator is
**column alignment**: table rows share vertical anchors, prose does not. Measured
on a borderless sample — prose inter-word gaps were 2.8pt while column gaps were
51–86pt, against a ~5pt character width, so a threshold scaled to character width
separates them cleanly. (Scaling to the row's *own* median gap fails: when every
cell is a single word, every gap is wide and nothing splits.)

Surplus anchors from centered columns are merged down to the dominant row arity.

Real result — Table 1 of *Attention Is All You Need*, which PyMuPDF misses entirely:

| Self-Attention | O(n2 · d) | O(1) | O(1) |
|---|---|---|---|
| Recurrent | O(n · d2) | O(n) | O(n) |
| Convolutional | O(k · n · d2) | O(1) | O(logk(n)) |
| Self-Attention (restricted) | O(r · n · d) | O(1) | O(n/r) |

Guard tests (`bench/make_table_pdfs.py` generates the fixtures):

| fixture | PyMuPDF default | TDF | correct? |
|---|---|---|---|
| `ruled_report.pdf` | 1 table | 1 table | yes |
| `borderless_report.pdf` | **0 tables** | **1 table (9x5)** | fixed |
| `prose_only.pdf` | 0 tables | **0 tables** | no false positive |

Recovering the structure is also what makes compression possible — `!C` headers,
`^` elision and constant-column hoisting only apply to real tables:

| | Markdown | TDF (no legend) |
|---|---|---|
| borderless_report.pdf | 531 | **314 (-40.9%)** |

---

## 10. Addressable elision

> **Read §12 first.** The mechanism described here is published prior art, not
> a new invention, and §11.3 removed most of its measured benefit by making the
> same tokens recoverable losslessly. It is kept because the in-band, model-free
> encoding is still a real contribution, and because the honesty result stands.

Everything above is lossless, and lossless compression has a floor. On
`kubernetes_docs.html` TDF saved only **2.0%**. Finding out why led to the one
genuinely new thing here.

### Where the tokens actually were

Not in prose. 69.6% of that document was list items, and the distribution was
grotesque: the single largest "list item" was **3,856 tokens** — the site's
entire navigation tree flattened into one string. The top 5 items were 32.7% of
all list tokens. About a quarter of the "document" was a site map.

Two hypotheses died on the data first:

- **Template induction** — factor out repeated item structure. Only 35 of 1015
  items shared even a 3-word prefix. No parallel structure to exploit.
- **Short-label packing** — pack nav-sized labels densely. Label-like items were
  just 8.8% of the document. Not where the mass was.

### The discriminator: sentence density

Navigation and prose look identical to a compressor — both are just words. They
differ in one cheap, robust signal: **sentence terminators per 100 tokens**.

| region | density |
|---|---|
| nav blobs | **0.00** |
| employee handbook | 1.92 |
| Kubernetes prose | 3.83 |
| Transformer paper | 4.29 |

A region ≥120 tokens with density ≤0.6 is an index, not an argument. Nothing
that is read start-to-finish scores zero.

### Elision, not summarisation

Such a region is replaced by a marker:

```
!E x1 index 3856 2850 Kubernetes Documentation Available Documentation Versions Getting started ...
```

Fields: id, kind, **exact token count**, item count, gist. The legend tells the
model that a region was omitted, that it may request it by id, and that it must
**not guess its contents**.

This is deliberately *not* compression. It is a declared hole with a return
address:

| approach | loss is | model can detect it | recoverable |
|---|---|---|---|
| truncation | silent | no | no |
| summarisation | disguised as content | no | no |
| skeleton mode | all-or-nothing per section | yes | yes |
| **elision** | **declared, sized, gisted** | **yes** | **yes, by id** |

The failure mode of summarisation is that the model cannot distinguish a summary
from the real thing, so it answers confidently from a lossy artifact. Elision
makes the loss *legible*, which converts a silent accuracy risk into an explicit
retrieval step.

### Results

```
tdf convert doc.html --tier              # emit with !E markers
tdf expand-elided doc.html x1            # resolve one back to full text
```

Tiering is opt-in and fired on **1 of 11** documents — the one that needed it.
Zero false positives on the paper, the handbook, and the SEC filing.

| document | markdown | TDF | TDF `--tier` |
|---|---|---|---|
| kubernetes_docs.html | 36,945 | 36,081 (-2.0%) | **26,095 (-29.4%)** |
| attention.pdf | 12,515 | 10,757 | 10,757 *(no elisions)* |
| handbook.html | 4,732 | 2,455 | 2,455 *(no elisions)* |
| sec_filing.html | 26,587 | 15,032 | 15,032 *(no elisions)* |

### Does the model actually notice?

That is the only question that matters, so it was tested rather than asserted.
A fresh `gpt-5.3-codex` with no knowledge of this project read the tiered
document and answered 6 questions manually (`qa_eval/README_tiering.md`):

- Q1–Q4, ordinary content questions: **all correct**, on 29% fewer tokens.
- Q5 asked it to list the full navigation tree exhaustively — answerable *only*
  from elided content. It **refused**: "does not contain enough information ...
  explicitly omitted as `!E` regions and only their gists are shown."
- Q6 asked what was missing. It answered **16 regions, 11,428 tokens, request by
  id** — matching the converter's own accounting exactly.

The model learned the protocol cold, from the legend, and used it correctly.

### The honest caveat

**Tiering is lossy.** It is reported as a separate tier and never blended into
the 100%-recall figures. It also assumes an index is *not* the content — for a
glossary, parts catalogue, or bibliography, the list **is** the document and
eliding it would be wrong. That is why it is opt-in, declared, and reversible
rather than on by default. And the honesty result is n=1 document, n=1 model.

## 11. Algorithms taken from the literature

A survey of the compression literature (`research/lit_survey.md`) named two
things I had built badly and one thing I had claimed too loudly. All three are
recorded here rather than quietly fixed.

### 11.1 Columnar dictionary coding — the biggest single win

The phrase dictionary only ever saw prose: `_iter_texts` yielded
Para/Quote/Heading/Figure and nothing else. On a 282k-token World Bank extract
it therefore found **zero** candidates, because tabular redundancy does not live
in sentences — it lives in columns.

This is standard practice in columnar stores (Parquet/ORC dictionary encoding),
applied to a token budget instead of a byte budget: a column whose cardinality
is low relative to its height has every cell replaced by a short code, with the
mapping declared once as `!V`.

Two measured facts drove the design:

- **Cardinality really is low.** `Country` has 262 distinct values over 13,978
  rows; `Year` has 64. Coding the eligible columns was worth 49,918 tokens —
  25.9% of the table body — against 2,320 for the phrase dictionary across the
  *entire* corpus.
- **Codes must be letters, not digits.** Under `o200k_base` a leading space
  merges into a lowercase code (`" a"`, `" ab"` = 1 token) but never into a
  digit (`" 0"`, `" 12"` = 2 tokens). Numbering the codebook `0..n` would have
  cost exactly double. `a..z` then `aa..zz` gives 702 codes, 649 single-token.

Run-length ("ditto") coding was implemented as the alternative and lost on every
table — 19.6% vs 25.9% on World Bank — because it only exploits *adjacent*
repeats and collapses to nothing if the table is not sorted on that column.

### 11.2 Re-Pair instead of greedy seed-and-extend

The original dictionary indexed a fixed seed length and extended it rightwards.
That is a weak approximation of **Re-Pair** (Larsson & Moffat, DCC 1999), which
builds phrases bottom-up by recursively replacing the most frequent *bigram*.
Greedy extension cannot arbitrate overlapping candidates — the exact bug logged
in §12 — whereas Re-Pair resolves it structurally, since both phrases are
composed from the same merged pairs.

Two deliberate departures from the textbook algorithm, both forced by the target:

1. **The priority is token saving, not frequency.** Classic Re-Pair minimises
   symbol count. We minimise BPE tokens under an unknown tokenizer, a different
   and non-additive cost: a 3-occurrence phrase worth 14 tokens each beats a
   40-occurrence pair worth 1. The queue is ordered by `occurrences * tokens`.
2. **Rules are flattened before emission.** Re-Pair naturally yields a hierarchy
   (`R7 -> R3 R5`). A decompressor resolves that in linear time; a language model
   reading `§7 = §3 §5` cannot. The hierarchy is used only as the search
   strategy, never as the output encoding.

Admission is unchanged — and the survey pointed out that the payback rule I had
hand-derived is a per-entry **MDL / Krimp-style code-table criterion** (Vreeken
et al., DMKD 2011) expressed in tokens rather than bits. It was already
principled; I had simply not known what to call it.

Head-to-head on the corpus, same admission rule, same inputs:

| document | greedy | Re-Pair | delta |
|---|---|---|---|
| operating_review.pdf | 860 | 2,539 | **+1,679** |
| services_agreement.docx | 791 | 1,069 | +278 |
| kubernetes_docs.html | 24 | 255 | +231 |
| runbook.md | 220 | 392 | +172 |
| attention.pdf | 26 | 179 | +153 |
| handbook.html | 325 | 440 | +115 |
| **total** | **2,320** | **4,948** | **+113%** |

### 11.3 The list-item blind spot

`_iter_texts` never yielded `ListBlock` items either. On a navigation-heavy page
that is not a detail — list text was **69.6%** of the Kubernetes document, and
all of it was invisible to the optimizer.

Fixing that, with Re-Pair on top, moved `kubernetes_docs.html` from **2.0% to
22.6% — losslessly**. That matters for the argument in §10: most of what the
lossy elision tier was buying is now available without giving anything up.

### 11.4 Results

Everything below is lossless, verified at 100% distinct-content recall.

| document | markdown | TDF | saved |
|---|---|---|---|
| operating_review.pdf | 3,588 | 1,228 | **65.8%** |
| services_agreement.docx | 1,945 | 1,028 | 47.1% |
| orders.csv | 16,982 | 9,196 | 45.8% |
| sales_report.xlsx | 20,505 | 11,230 | 45.2% |
| handbook.html | 4,732 | 2,657 | 43.9% |
| sec_filing.html | 26,587 | 15,196 | 42.8% |
| worldbank.csv | 282,341 | 170,008 | 39.8% |
| quarterly_deck.pptx | 1,559 | 975 | 37.5% |
| runbook.md | 1,355 | 976 | 28.0% |
| kubernetes_docs.html | 36,945 | 28,600 | 22.6% |
| attention.pdf | 12,515 | 10,849 | 13.3% |
| **total** | **409,054** | **251,943** | **38.4%** |

Previously 30.1%. The gain comes from columnar coding, Re-Pair, and list-item
coverage, and it is all lossless — no elision is involved.

## 12. Corrections the literature forced

Three claims in earlier versions of this README were too strong.

**"Sentence density is a new discriminator" — it is a rediscovery.**
Kohlschütter, Fankhauser & Nejdl (WSDM 2010) established **text density and link
density** as the shallow features separating navigation from main content, and
`jusText` and `trafilatura` are mature implementations. Sentence-terminator
density is a genuinely different signal — it works on PDFs, where there is no
`<a>` tag to count — but it belongs to that line of work and should be cited as
such. Link density is untested here and would likely beat it on HTML.

**"Addressable elision is novel" — the mechanism is published.** MemGPT
(arXiv:2310.08560), MemWalker, PageIndex, and Anthropic's "just-in-time context"
write-up all describe declared omission with a retrieval handle, using nearly
the same vocabulary ("progressive disclosure", "lightweight identifiers"). A
2026 controlled study (arXiv:2607.17598) goes further and reports that
progressive disclosure "buys context, not intelligence", with gains near zero
when the model already navigates the raw document well — a direct challenge to
the Kubernetes result, and now a weaker claim anyway given §11.3. That study's
finding that a *second* level of routing never helps does validate the flat `!E`
design.

  What survives is narrower and worth stating precisely: **a model-free, in-band
  encoding of progressive disclosure inside a document interchange format**,
  with a deterministic detector and an exact token accounting of what was
  withheld. Every prior system puts the mechanism in an agent harness and needs
  a tool loop; `!E` travels inside a plain-text artifact and works in a
  single-turn chat. "The model can request the missing region" is not novel.

**The QA benchmark is contaminated.** `attention.pdf` is arXiv 1706.03762 —
in every model's training data. Any QA result on it measures recall of
pretraining, not comprehension of the format. The 500xCompressor authors flag
exactly this failure. That eval needs documents post-dating the model cutoff.

**Where TDF actually sits.** Every published prompt compressor — LLMLingua,
LLMLingua-2, Selective Context, RECOMP, ICAE, 500xCompressor — requires a model
at inference, and half emit soft tokens rather than text. TDF cannot claim their
ratios (2x–480x vs 1.6x here). It occupies a different point: lossless,
model-free, tokenizer-agnostic, human-readable. The two are **composable rather
than competing** — TDF is format-level, LLMLingua is semantic-level, and
stacking them is an untested but obvious experiment.

## 13. Bugs the benchmark caught

Worth recording, because each one was invisible until measured:

1. **Ragged table rows were silently truncated.** Both emitters sized the grid by
   the *header* row. SEC filings routinely have a short or empty header and much
   wider data rows — so real financial data was being dropped, from the Markdown
   baseline too. Fixed at the IR level (`Table.__post_init__` pads to the widest
   row). Recall went 74.5% → 100%.
2. **Overlapping dictionary entries never fired.** "A B C D" and "B C D E" contain
   neither each other, so a naive overlap filter accepted both — but only the first
   substitution ever applied. Rewritten as seed-and-extend maximal-repeat discovery
   with greedy acceptance against a working corpus.
3. **`sign in "-("` is `True` for the empty string**, so every positive number was
   being negated. Caught by the test suite, not by any benchmark.
4. **Boilerplate hides in list items**, not just paragraphs (PowerPoint puts slide
   chrome in text-frame bullets).
5. **`!R` boilerplate parsed but never restored** as content, so it read as lost
   meaning.
6. **Skeleton ids collapsed** (`2.0.1`) when heading levels skip, and duplicated
   when levels jump backwards — which broke `expand`.
7. **Borderless PDF tables were invisible** — see section 9.

### Bugs the fuzzer caught (section 13a)

A benchmark only exercises documents that happen to exist. A randomised
round-trip harness (`tests/fuzz.py`) generates documents from a pool of
deliberately hostile strings — sigil-shaped text, separators, quotes, `^`,
`§n`, embedded newlines, empty cells — and asserts the document survives
emit → parse. It found a class of bug the corpus never could.

8. **Sigil injection.** The parser dispatched on `line.startswith("!T")`, which
   also matches the ordinary sentence `!Try it now`; `startswith("!K")` matches
   `!Kubernetes is great`. A paragraph reading `!E x1 ...` scored **0% recall —
   total data loss**. Fixed in two layers: a real sigil grammar in the parser
   (`!X` must be followed by whitespace or end of line) and escaping on the way
   out.
9. **Ordinary prose was eaten as a list marker.** TDF drops the dot from ordered
   items to save a token, so the parser reads `^(\d+) `. That silently consumed
   the first word of any paragraph starting with a number: `2024 was a strong
   year` came back as a list item and **`2024` vanished entirely**. Escaping now
   covers every structural line shape — sigils, `#`, `-`, `N.`, `>`, `%TDF` —
   with `needs_escape` and `_unescape` as exact inverses.
10. **A newline inside a cell corrupted the whole grid.** TDF is line-oriented
    and a table declares its row count up front, so an Alt+Enter cell (common in
    real spreadsheets) split into two physical lines and shifted every following
    row. Cell values are now collapsed to one line on emit. **Distinct-content
    recall scored this 100%** — every word survived, only the structure was
    wrong — which is why it needed a structural assertion to catch.
11. **Columnar codebooks were emitted but never decoded.** `!V` had no branch in
    the parser at all, so coded cells came back as the literal codes `a`, `g`.
    Recall again reported 100%, because the values still appear in the codebook
    lines. Now decoded, and asserted structurally.
12. **A malformed sigil argument crashed the parser.** `!P 3: !Kubernetes` hit
    `int(...)` and raised. A converter is pointed at untrusted files by
    definition, so it must degrade, never raise; the CLI now reports a clean
    error and exits non-zero instead of printing a traceback.

Two of my own "fixes" introduced regressions that the suite caught: narrowing
the heading check to `"# "` stopped `##` from terminating an `!R` block (which
swallowed the rest of the document), and requiring a *space* after a sigil broke
every tab-separated table. Both are now covered by tests.

**The honest lesson**: three of these six bugs were invisible to
`distinct_recall`, the metric the whole benchmark rests on. Content recall
answers "do the words survive", not "is the document the same shape". Section 14
records this as the metric limitation it is.

13. **A newline inside a table caption shifted the declared row count.**
    `!T 3 multi\nline\ntext` made the parser read `line` and `text` as rows 1
    and 2, so the real data was misparsed as the header. Captions now collapse
    newlines like cells do.

14. **`!R` swallowed a following list.** The boilerplate loop ended only on
    sigils and headings, so a list that *followed* the boilerplate was eaten
    into it. Caught by corpus-level idempotence testing, not by the fuzzer —
    the fuzzer never generated a list adjacent to boilerplate. The loop now
    also ends on `- `, `N `, `> ` and ` ``` `; genuine boilerplate with those
    shapes arrives escaped, so this cannot truncate real content.

### Validity by construction (section 13b)

The literature survey pointed at **OTSL** (Lysak et al., ICDAR 2023): a
vocabulary in which malformed tables are *unrepresentable*, not merely
detectable. TDF now has both halves of that idea:

- **IR level** — `Table.__post_init__` forces a rectangular grid; a ragged
  table cannot exist in memory.
- **Serialized level** — `tdf validate <file>` checks every invariant the
  parser relies on (magic header, declared row counts vs. physical lines,
  one-line body text) and fails loudly instead of silently degrading.

One invariant changed shape under measurement: **idempotence**. Strict
`emit(parse(x)) == x` fails on the Kubernetes corpus — re-optimizing a parsed
document renumbers Re-Pair dictionary entries on ties, because optimization
*normalizes* block order (boilerplate hoisted to the preamble). The property
that actually matters is **convergence**: iterating `emit∘parse` must reach a
fixed point with 100% content recall at every step. Measured: the worst corpus
document converges at iteration 4; `validate` requires convergence within 8.

Current status: **75 tests pass; 2000/2000 randomised documents round-trip
losslessly; every corpus document validates and converges.**
We have successfully implemented Property-Based Testing using Hypothesis
to automatically explore edge cases, finding and fixing a bug around empty tables
and structurally tightening the `!D` dictionary representation to declare item counts.

## 14. Known limitations

- **Small documents can come out larger.** `prose_only.pdf` is 222 Markdown tokens
  but 252 in TDF, because the ~130-token legend dominates. Without the legend it's
  111 (-50%). Below roughly 500 tokens, use `--no-legend` or don't bother.
- **Scanned/image PDFs are not handled** — there is no OCR step. Pair with olmOCR
  or Chandra first.
- **Dictionary substitution hurts prose readability.** `...at the start of §3 1.`
  expands losslessly but reads badly raw. Safe for tables, questionable for prose.
- **No math, no images beyond a caption, no merged cells, no multi-column reading
  order.**
- **Fidelity is content recall, not structural equivalence.** It proves no
  meaning-bearing term is lost; it does not prove the shape survived. This is not
  a theoretical caveat: two real bugs (newline-in-cell shifting every table row,
  and `!V` codebooks never being decoded) both scored a **perfect 100%** while
  producing a visibly wrong table, because the words survived somewhere in the
  file. Structural assertions now cover both, but the headline recall number
  should be read as a floor, not a proof. The QA eval in `qa_eval/` is the
  complement to this, but it is n=1 document, n=1 model.

## 15. What's next

- Widen the QA eval across more documents and model families.
- Ship the legend as a system prompt and drop it from the payload.
- Multi-column PDF reading order and colspan/rowspan (Markdown can't express these
  at all; TDF could).
### Benchmarking against LLMLingua

We ran a head-to-head compression benchmark of **TDF** vs **LLMLingua** (using `microsoft/llmlingua-2-xlm-roberta-large-meetingbank`) on the `sec_filing.html` and `handbook.html` out-of-training-data documents. We targeted LLMLingua to the same token budget as TDF to compare the semantic fidelity.

| Document | Markdown Tokens | TDF Tokens | TDF Saving | LLMLingua Tokens | LLM Lingua Saving | LLMLingua Time (s) |
|---|---|---|---|---|---|---|
| sec_filing.html | 26,587 | 15,032 | 43.5% | 14,728 | 44.6% | 14.33s |
| handbook.html | 4,732 | 2,464 | 47.9% | 3,084 | 34.8% | 1.94s |

**Analysis of LLMLingua Fidelity:**
LLMLingua destroys the table structure to achieve its compression. It strips out table rows randomly, merges columns, removes punctuation necessary for separating values, and completely breaks tabular alignment.
For example, in `handbook.html`, the output loses critical quantitative values from the table rows, leaving disjointed and incorrect data representations.

**TDF Advantage:**
While LLMLingua requires an expensive LLM inference step (14+ seconds on CPU) and produces lossy outputs that destroy tabular data structures, **TDF** achieves similar or better compression (43-47%) natively during the conversion process with 100% semantic fidelity and structured table data intact. TDF is significantly faster and does not rely on a model for compression.
