---
name: pdf-to-clean-text
description: Reads a PDF as clean text instead of page images, for a fraction of the tokens - search it, read chosen pages, or hand whole-document work (summaries, quizzes, translations) to a cheap reader agent. Use whenever the user shares a PDF and wants to know or do something with its content. Flags pages whose text can't be trusted. Not for editing, merging, splitting or filling PDFs.
license: MIT
compatibility: Python 3.10+, shell access, and pip install -r requirements.txt. Built for Claude Code.
metadata:
  author: habib049
  version: "0.1.0"
---

# PDF to clean text

The script is `scripts/pdf_to_clean_text.py` in this skill's folder; call it by its absolute path. Every command
converts the PDF if needed (about a second per page, then cached by file content) and prints `info:` (pages,
size in tokens) and `warning:` lines on stderr. For errors, setup and limits, read [reference.md](reference.md).

**A few pages long:** read the whole conversion (`python SCRIPT FILE.pdf`) and skip the rest of this.

**A question about part of it:** `python SCRIPT FILE.pdf --find "term"` prints the sections containing the term.
It's literal, so use words the document uses (a heading, number, name). After two misses, or when the question
shares no words with the text, run `--map` (a short card of the document, or its headings with their pages),
then `--pages 12-14`.

**Whole-document work** (summary, quiz, study guide, a table of everything, translation, proofreading): call the
`pdf-reader` agent straight away. Don't convert, map or read the PDF first, and don't check its result yourself:
keeping all of that out of this conversation is the point. Give it exactly this prompt; it has its own procedure:

```
CMD: python <absolute path of scripts/pdf_to_clean_text.py>
PDF: <absolute path of the PDF>
TASK: <the user's request, word for word>
OUTPUT: <absolute path of the file to write>
```

The agent builds notes from the PDF the first time and reuses them later (they're cached by file content, so
"notes from an earlier run" means this same file), and it checks its own citations. Relay its report,
including any warnings in it. Open OUTPUT only if the user asks you to change it. No `pdf-reader` agent? Read
`--pages` in 10-page chunks yourself.

**Warnings,** for the pages you used:

- `scanned page, text came from OCR`: may be garbled. Say so when quoting it, and check names, amounts and dates
  against that page's image.
- `figure with no caption found`: its content isn't in the text. View that page's image if the answer needs it.
- `removed lines repeated across pages`: watermark-like lines were dropped. Look here if something seems missing.

**Cite pages** as the `<!-- page N -->` markers number them: the PDF's own numbering, which can differ from the
numbers printed on the pages.
