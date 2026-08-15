# TDF Diff Token Efficiency

This document evaluates the token efficiency of `tdf diff` compared to the alternative of pasting both documents into an LLM context.

| Changes | Both Docs Tokens | Diff Tokens | Savings |
|---|---|---|---|
| 0% | 2,082 | 10 | 99.5% |
| 1% | 2,082 | 10 | 99.5% |
| 5% | 2,086 | 74 | 96.5% |
| 10% | 2,095 | 207 | 90.1% |
| 20% | 2,103 | 427 | 79.7% |
| 50% | 2,138 | 1,053 | 50.7% |

## Change Detection Accuracy
The token reduction implies models will experience significantly fewer distractors. A future eval harness run on consecutive financial filings will measure exact QA recall vs raw text pasting.
