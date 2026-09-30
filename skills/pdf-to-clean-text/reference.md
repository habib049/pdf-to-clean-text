# Reference

## Errors

Relay the message as written; it is already plain English. Exit code 1 means a problem with the PDF, 2 bad usage.

| Error | Next step |
|---|---|
| password-protected | There is no password option. Ask for an unlocked copy. |
| No file / not a PDF | Check the path, and that the file really is a PDF. |
| damaged or incomplete | Nothing can be read from it. Ask for a fresh copy. |
| no extractable text | Probably blank or an unreadable scan. View the pages as images instead. |
| could not reach Hugging Face | A network problem, not a bad PDF: the models aren't downloaded yet. Ask the user to connect, then run `--warmup` once and retry. |
| `... isn't installed. Run: pip install ...` | See Setup. Ask before installing. |

## Setup

From this skill's folder: `pip install -r requirements.txt`. This installs docling, which brings in torch
(several GB). Then download the models once, so the first real PDF isn't the one that stalls; it needs a network,
takes a few minutes and fetches about 0.5 GB:

```bash
python scripts/pdf_to_clean_text.py --warmup
```

Tell the user the sizes and ask before installing or downloading on their behalf. On Linux, suggest CPU-only
PyTorch first (`pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu`), which is far
smaller than the default build. The first conversion ever can take minutes, so allow a long timeout.

## Cache and sensitive documents

Extracted text is cached on disk by file content, and so are the `pdf-reader` agent's card and notes
(`--compiled-paths` prints where). For a sensitive document, add `--no-cache` to every command: nothing is kept,
and `--map` shows the outline because no card can exist. Don't hand a `--no-cache` document to `pdf-reader`,
which keeps notes on disk; read `--pages` in chunks yourself.

## Limits

- Figures are captions only; a chart with no caption is invisible in the text.
- One bad page fails the whole conversion; there is no partial result.
- Paragraph breaks from docling are not always faithful, so don't read meaning into a line break.
- The reader's notes are condensed: exact wording comes from `--pages`, not from the notes.
- Nothing is redacted. Clean is not the same as safe to share.
