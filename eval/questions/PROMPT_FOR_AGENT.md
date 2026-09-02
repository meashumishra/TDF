# Task: write QA eval questions for 13 documents

You are writing evaluation questions for a document-compression benchmark
(TDF-R). The benchmark shows an LLM a document in several different text
encodings and asks it a factual question; a question is scored correct if
the model's answer matches (or contains, for most types — see below) the
gold answer. Your job is to write good questions, not to answer them
yourself with any special knowledge — every answer must come only from the
document text you're given.

## What to read

Each document below has already been rendered to plain Markdown at the
given path, **relative to the repository root**. Read the file at that
path — do not use any other source for the same document (see "Why the
provided text, not the original" below). This is 13 of the 14 documents
in the corpus that currently have no questions — the 14th
(`petstore_openapi`, a JSON OpenAPI spec) is intentionally excluded: TDF
has no JSON reader yet, so that document can't be run through the eval
harness at all regardless of what questions exist for it.

| doc_id | file to read |
|---|---|
| `k8s_services` | `eval/questions/prep/k8s_services.md` |
| `k8s_configmap` | `eval/questions/prep/k8s_configmap.md` |
| `rfc2616_http` | `eval/questions/prep/rfc2616_http.md` |
| `rfc1035_dns` | `eval/questions/prep/rfc1035_dns.md` |
| `alice_prose` | `eval/questions/prep/alice_prose.md` |
| `frankenstein_prose` | `eval/questions/prep/frankenstein_prose.md` |
| `pride_prose` | `eval/questions/prep/pride_prose.md` |
| `readme_requests` | `eval/questions/prep/readme_requests.md` |
| `readme_fastapi` | `eval/questions/prep/readme_fastapi.md` |
| `access_log` | `eval/questions/prep/access_log.md` |
| `code_doc_dataclasses` | `eval/questions/prep/code_doc_dataclasses.md` |
| `code_doc_decimal` | `eval/questions/prep/code_doc_decimal.md` |
| `github_terms` | `eval/questions/prep/github_terms.md` |

**Why the provided text, not the original source**: these documents were
deliberately perturbed before rendering — entity names and every number
were altered from the real RFC/novel/README/etc. This stops a model from
answering out of training-data memory instead of the document actually
shown to it. If you write a question using the real RFC 1035 section
numbers, or the real Alice-in-Wonderland dialogue, the answer will be
**wrong** against what the eval harness actually shows the model. Always
quote the exact text/numbers from the rendered file, never from what you
already know about these documents.

**The prose novels and RFCs are long.** You don't need to read every word.
Sample several sections spread across the document (beginning, middle,
end — or a few chapters/sections) rather than only the opening, so
questions aren't all clustered in one place.

## Question types and how each is scored

The scorer has two modes:

- **Strict** (`exact_identifier`, `leading_zero`, `deref_dict`): the
  model's answer must equal the gold answer exactly (case-sensitive,
  whitespace-normalized). Keep these answers short and unambiguous —
  a single value, code, or short phrase, not a sentence.
- **Lenient** (every other type): correct if the model's answer equals
  the gold answer case-insensitively, OR the gold answer appears as a
  substring anywhere in the model's answer. A short, precise gold answer
  is still better — "Argentina" is a better gold answer than "the country
  is Argentina" even under lenient scoring, because it can't accidentally
  match the wrong thing.

Only use a question type where the document actually supports it — don't
force a type that doesn't fit. Table-oriented types only apply to
`k8s_services`, `k8s_configmap`, `readme_fastapi`/`readme_requests` (if
they contain tables), `access_log` (treat log fields as columns), and the
code-doc files (if they contain structured API tables); the prose novels
and `github_terms` are pure text — use only the prose-appropriate types.

| type | what it tests | applies to |
|---|---|---|
| `exact_identifier` | verbatim short-phrase recall (strict match) | any |
| `negation` | distinguishing what's true from what's similar-but-false | any |
| `ordering` | first/last/sequence in the document | any |
| `row_association` | "what is X where Y is Z" (needs a table or list with a clear key) | tables |
| `column_association` | "which field/column has value Z" | tables |
| `numeric_comparison` | which entity has the largest/smallest numeric value | tables/logs with numbers |
| `multi_hop_table` | filter by one field, then find the max/min of another | tables |
| `cross_reference` | a fact that requires connecting two different sections/tables in the SAME document | any, only if the document actually has two related sections |
| `deref_code` | resolving an abbreviation/code the document itself defines (e.g. an HTTP status code list, a config key) | technical docs |
| `deref_dict` | exact recall of a phrase that repeats verbatim multiple times in the document (strict match) | any |
| `leading_zero` | a value with significant leading zeros (version numbers, IDs, log fields) — strict match, must preserve the zeros exactly | technical docs, logs |

**Do not invent `row_association`/`column_association`/etc. questions
against a "table" that's just prose with numbers in it** — only use them
where the document has an actual list of comparable records (a real
table, a structured list of fields, or repeated log lines).

## Quality bar (read this before writing)

1. **Every answer must have exactly one correct value in the document.**
   If a table has multiple rows that could equally answer "what is X where
   Y is Z", either pick a Y value that's unique, or don't ask the
   question. This is the single most common failure mode — check it for
   every question.
2. **Ground every answer in the text you read**, not in what you already
   know about RFCs, Python's stdlib, HTTP, or these novels. Quote exact
   wording/numbers from the file.
3. **Keep gold answers short** — a word, a number, a short phrase. Not a
   sentence, not a list, unless the question type specifically calls for
   verbatim phrase recall (`deref_dict`/`exact_identifier`).
4. **Avoid yes/no and opinion questions.** Every question must have a
   single, checkable, factual answer.
5. **For `negation` questions**, phrase them so there's exactly one
   defensible answer even though the category admits several — e.g. "Name
   one HTTP method defined in this document that is NOT GET" is fine
   (any non-GET method the model names should arguably be accepted, but
   since the scorer needs one gold string, pick the clearest alternative
   and phrase the question so a careful reader converges on it, e.g. by
   asking for "the method listed immediately after GET" instead of an
   open-ended "name one").

## How many questions

Aim for **8-12 questions per document**, spread across at least 4-5
different types. Fewer is fine for a thin document (e.g. the code-doc
files or a short README) — don't pad with low-quality questions just to
hit a number. More is fine for a rich one (an RFC, a novel) if you have
that many genuinely unambiguous questions.

## Output format

Produce **one JSON file** (or one array — either is fine) containing a
flat list of objects, each with exactly these five fields:

```json
{
  "id": "rfc1035_dns_exact_identifier_0",
  "type": "exact_identifier",
  "question": "According to this document, what is the maximum length in octets of a domain name?",
  "answer": "255",
  "doc_id": "rfc1035_dns"
}
```

- `id`: unique across your entire output. Use the pattern
  `{doc_id}_{type}_{n}` (n = a per-document counter, starting at 0) so ids
  are self-describing and collisions are easy to spot.
- `type`: one of the type names in the table above, exactly as spelled.
- `question`: a complete, self-contained question — the model answering it
  will see the document text but not this prompt, so don't reference "the
  table above" or "as discussed" without the document itself making that
  clear.
- `answer`: the gold answer, matching the strict/lenient scoring notes
  above.
- `doc_id`: exactly one of the 13 ids in the table at the top — no typos,
  this is validated on import.

Save your output as a single `.json` file. When you're done, it gets
imported with:

```bash
.venv/bin/python -m eval.questions.import_prepared --dry-run <your_file>.json   # preview
.venv/bin/python -m eval.questions.import_prepared <your_file>.json             # actually import
```

The import validates every field, checks every `doc_id` is real, checks
every `id` is unique against what's already in `questions.json`, and
reports which of the 13 documents (if any) your output didn't cover. It
never touches questions for any other document already in the file.
