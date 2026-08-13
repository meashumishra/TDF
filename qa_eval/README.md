# QA-accuracy evaluation (A/B)

Tests whether a model *understands* TDF, not just whether terms survive.

- Source: `samples/sales_report.xlsx` (3 sheets, 600 order rows)
- Two fresh `gpt-5.3-codex` agents, no knowledge of this project.
  One got `doc_tdf.txt` (11,224 tok), one got `doc_md.txt` (20,505 tok).
- Both told to reason manually from the text — no scripting allowed.
- The TDF agent had only the embedded ~130-token legend to learn the format.

| question | truth | TDF | MD |
|---|---|---|---|
| total_rows | 600 | 600 OK | 600 OK |
| region_of_10260 `^` | APAC | OK | OK |
| product_of_10260 `^` | Bearing Standard | OK | OK |
| status_of_10029 `^` | backordered | OK | OK |
| top_product_by_amount | Flange Deluxe | OK | OK |
| top_product_total | 4,656,944 | 4,619,849 (-0.8%) | OK |
| cancelled_count | 153 | 153 OK | 152 (-0.7%) |
| order_with_max_qty | 10027 | OK | OK |
| max_qty | 40 | OK | OK |

**TDF 8/9, Markdown 8/9, on 45.3% fewer tokens.**

Each format missed a different question, and both misses are manual-arithmetic
slips while summing/counting 600 rows by hand — not comprehension failures.

The three `^` rows are the ones that matter: they are answerable *only* by
resolving a back-reference to the cell above. TDF got 3/3, which is the direct
evidence that `^` elision does not cost comprehension.

Caveat: n=1 document, n=1 model family. This is a sanity check, not a
peer-reviewed eval. Note also that this run corrected the ground truth — the
first attempt scored only sheet 1 (300 rows); both models correctly reported 600.
