# Benchmark

How this skill's numbers were measured, so you can reproduce or challenge them. Two kinds of number appear
below: **measured** (an actual `count_tokens` API call) and **estimated** (character count ÷ 3, this project's
own measured ratio on a 30-page document: 75,982 characters was 25,052 tokens). Every row says which it is.

## Full-document reads vs. native PDF reading

Native reading means handing Claude the PDF file directly: Claude Code sends each page as extracted text *and*
as a rendered image, because the image is what keeps it from missing a chart, a signature or a scanned page.
The image is the expensive part — about 62% of the native cost on the documents below.

Measured with `count_tokens` on `claude-opus-5` (Sonnet 5 gave identical counts on the 30-page exam):

| Document | Native (text + images) | This skill | Saved |
|---|---|---|---|
| 30-page exam, dense text, one scanned page | 72,663 | 25,052 | 65.5% (2.9x) |
| 6-page report, one scanned page, two images | 10,109 | 1,053 | 89.6% (9.6x) |
| 2-page résumé | 4,569 | 1,494 | 67.3% (3.1x) |
| 2-page résumé (second document) | 4,365 | 1,250 | 71.4% (3.5x) |

A full read tops out around 65% savings on dense text. The removed 62% is the page images; what's left is the
document's actual content, which can't shrink further without losing it. Four documents is a small sample —
measure your own before quoting a number, and see [Reproducing this](#reproducing-this) below.

## Reading less: targeted and structural lookups

Once the text is extracted, the next lever is not reading all of it. Two routes, both exact text (no model
summarization, no lossy step):

| Lookup | Tokens | vs. native | vs. full skill read |
|---|---|---|---|
| `--find "question 3.9"` (measured, `count_tokens`) | 423 | 99.4% (172x) less | 98.3% (59x) less |
| `--outline` (estimated, char-count) | ~1,800 | 97.5% (41x) less | 92.8% (14x) less |
| `--pages 3-21` for a 19-page section (estimated) | ~14,300 | 80.3% (5.1x) less | 42.9% (1.75x) less |

`--find` is a literal, case-insensitive keyword search over section headings; it works when the question shares
vocabulary with the document (7 of 7 did, in testing against a question set written independently of this
skill — an eighth question used a word the document never contains, and correctly returned nothing). `--outline`
and `--pages` are the fallback when it doesn't: read the document's heading structure for a few percent of its
tokens, then fetch only the pages a question needs.

## Quality, not just tokens: vs. docling alone and vs. pymupdf4llm

Token count isn't the only axis — a cheaper extraction that silently drops a table is worse, not better.
Measured on the file `tests/make_test_pdf.py` builds: 6 pages with a repeated header and footer, a diagonal
`DRAFT` watermark, an unruled table, a captioned figure, a one-off quote in the top margin, and one image-only
(scanned) page. It's a stress test, not a typical document.

| | docling alone | this skill (docling + its layer) | pymupdf4llm alone |
|---|---|---|---|
| Header / footer / page numbers | removed | removed | left in on every page |
| `DRAFT` watermark | left in, 5 pages | removed | left in, letters leak into table cells |
| One-off margin quote | kept | kept | kept |
| Table | clean markdown | clean markdown | mangled |
| Figure caption | linked to figure | linked (`r.figures`) | glued onto a paragraph |
| Page boundaries | none | `<!-- page N -->` | none |
| Scanned page | OCR'd, no warning | OCR'd, warning | silently dropped |

[pymupdf4llm](https://github.com/pymupdf/RAG) is included because it's the obvious lightweight alternative —
no model download, pure geometry heuristics. On this file it isn't a substitute: it has no OCR, no learned
layout detection, and no table-structure model, so it guesses structure from font size and position alone.

## What isn't benchmarked yet

The `pdf-reader` agent (whole-document work: summaries, quizzes, translation, handed to a cheaper model) has
been exercised on one 30-page document and fixed against two real failures found doing that, but has **not**
been run through this project's own eval suite (`evals/`) or benchmarked end to end since those fixes. Numbers
for it will land here once that's done — see the CHANGELOG's "Known gaps" entry. Don't repeat agent-path numbers
as if they were measured; they aren't yet.

## Reproducing this

You need an `ANTHROPIC_API_KEY`; `count_tokens` is free (no completion is generated).

```bash
# 1. Extract a PDF both ways and save the outputs
python skills/pdf-to-clean-text/scripts/pdf_to_clean_text.py your.pdf > /tmp/clean.md

# 2. Count tokens for the clean extraction
curl https://api.anthropic.com/v1/messages/count_tokens \
  -H "x-api-key: $ANTHROPIC_API_KEY" -H "anthropic-version: 2023-06-01" -H "content-type: application/json" \
  -d '{"model":"claude-opus-5","messages":[{"role":"user","content":[{"type":"text","text":"'"$(python -c 'import json,sys;print(json.dumps(open("/tmp/clean.md").read())[1:-1])')"'"}]}]}'

# 3. Count tokens for native reading: send the PDF itself as a document content block
curl https://api.anthropic.com/v1/messages/count_tokens \
  -H "x-api-key: $ANTHROPIC_API_KEY" -H "anthropic-version: 2023-06-01" -H "content-type: application/json" \
  -d '{"model":"claude-opus-5","messages":[{"role":"user","content":[{"type":"document","source":{"type":"base64","media_type":"application/pdf","data":"'"$(base64 -i your.pdf)"'"}}]}]}'
```

Compare the two `input_tokens` values. For `--find`/`--outline`/`--pages`, repeat step 2 with that command's
output instead of the full extraction.

**What changes the numbers on your document:** page count obviously, but also font size and line density (more
text per page raises the extraction's share, lowering the ratio since there's less fat to trim), how many
scanned or image-heavy pages it has (these cost the same both ways, since the image goes to Claude either way),
and how well your question's wording matches the document's for `--find`.
