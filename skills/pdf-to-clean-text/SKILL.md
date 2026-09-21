---
name: pdf-to-clean-text
description: Extracts a PDF's content as clean markdown with page markers, so it can be summarized, analyzed, quoted or queried for 3 to 10 times fewer tokens than reading the PDF natively, which sends an image of every page. Use when the user shares a PDF (report, paper, contract, invoice, scan) and wants to know what is in it, especially when it is long or has tables, multiple columns, a watermark or scanned pages. Returns tables as markdown, links figure captions to figures, strips watermark lines repeated across pages, retrieves just the sections a question needs, and flags pages whose OCR text should not be trusted. Not for merging, splitting, rotating, watermarking or filling PDF forms, or exporting tables to CSV or Excel.
license: MIT
compatibility: Needs Python 3.10+, shell access, and pip install -r requirements.txt (docling, pypdfium2); the first run downloads about 0.5 GB of models. Built for Claude Code. Won't work where packages can't be installed, such as the Claude API code execution tool.
metadata:
  author: habib049
  version: "0.1.0"
---

# PDF to clean text

Reading a PDF natively sends every page as text plus an image. This reads the text locally instead, and
the warnings replace the image as the safety net: they name the pages where text alone can't be trusted,
so you look at those pages' images and no others.

## Workflow

```
- [ ] 1. Convert, and read the info and warning lines
- [ ] 2. Read the whole document, or only the sections the question needs
- [ ] 3. Act on each warning
- [ ] 4. Answer, citing pages
```

**1. Convert.** Paths are relative to this skill's folder. Name the output after the PDF so two documents
never share a file:

```bash
python scripts/pdf_to_clean_text.py report.pdf > /tmp/report.md 2> /tmp/report.log
grep -E '^(info|warning|error):' /tmp/report.log
```

The `info:` line gives the page count and size in tokens. stdout holds only the document; stderr holds the
diagnostics, and the `grep` drops stray library output. Exit code 0 is success, 1 a problem with the PDF,
2 bad usage.

The first conversion of a file takes about a second per page, and the very first run of all can take
several minutes while docling downloads its models, so allow a long timeout. Results are cached by file
content, so running the script again on the same PDF, including with `--find`, takes under a second. The
cache stores the extracted text on disk; add `--no-cache` for a sensitive document.

**2. Read what the task needs.** Decide by the size in the `info:` line.

- **About 8,000 tokens or fewer** (roughly 10 dense pages): read the whole `.md` file. Searching would cost
  more in extra steps than it saves.
- **Longer:** fetch only the relevant sections.

  ```bash
  python scripts/pdf_to_clean_text.py report.pdf --find "question 3.9" --find "refund policy"
  ```

  This prints every section containing any of the terms (a section runs from one `##` heading to the next),
  each labelled with the page it starts on, at most 10. Matching is case-insensitive and ignores hyphens,
  but it is literal: pick words the document itself uses, such as a heading, identifier, name or number.
  "reimbursement" will not find a section titled "Refunds". If nothing matches, try the document's likely
  wording; if too much matches, use a more specific term; if the sections don't answer the question,
  search again before reading more.

Read the whole file only when the task covers the whole document (summarize it, review it end to end), and
then in chunks.

**3. Act on each warning.** The output can look clean while being wrong, so don't skip these.

| Warning | What to do |
|---|---|
| `page N: scanned page, text came from OCR and was not verified` | The page's text may be garbled. When quoting it, say it came from OCR. Check names, amounts and dates against the page image, reading only that page of the original PDF. |
| `page N: figure with no caption found` | The figure's content is not in the text. If the question depends on it, view that page's image rather than guessing. |
| `removed lines repeated across pages: [...]` | Watermark-like lines were removed. If the user says something is missing, check here first. |

**4. Answer.** Pages are separated by `<!-- page N -->` markers; cite the page a claim comes from. Figures
appear as their caption followed by `<!-- image -->`, since the image itself is not extracted.

## Errors

Relay the message as written; it is already plain English. Then:

| Error | Next step |
|---|---|
| password-protected | There is no password option. Ask for an unlocked copy. |
| No file / not a PDF | Check the path, and that the file really is a PDF. |
| damaged or incomplete | Nothing can be read from it. Ask for a fresh copy. |
| no extractable text | Probably blank or an unreadable scan. View the pages as images instead. |
| could not reach Hugging Face | A network problem, not a bad PDF: the models aren't downloaded yet. Ask the user to connect, then run `--warmup` once and retry. |
| `... isn't installed. Run: pip install ...` | See Setup. Ask before installing. |

## Limits

- Figures are captions only; a chart with no caption is invisible in the text.
- One bad page fails the whole conversion; there is no partial result.
- Paragraph breaks from docling are not always faithful, so don't read meaning into a line break.
- Nothing is redacted. Clean is not the same as safe to share.

## Setup

From this skill's folder:

```bash
pip install -r requirements.txt
```

This installs docling, which brings in torch (several GB). Then download the models once, so the first real
PDF isn't the one that stalls; it needs a network, takes a few minutes, and fetches about 0.5 GB:

```bash
python scripts/pdf_to_clean_text.py --warmup
```

Tell the user the sizes and ask before installing or downloading on their behalf. On Linux, suggest
installing CPU-only PyTorch first (`pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu`),
which is far smaller than the default build.
