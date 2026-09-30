# pdf-to-clean-text

[![tests](https://github.com/habib049/pdf-to-clean-text/actions/workflows/tests.yml/badge.svg)](https://github.com/habib049/pdf-to-clean-text/actions/workflows/tests.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

A Claude skill that reads a PDF as markdown instead of letting Claude read it natively: 3 to 10 times fewer
tokens in my tests, and it tells you which parts not to trust.

When Claude reads a PDF directly, every page is sent twice, as extracted text and as an image. The image is
what keeps it from missing anything, and it's most of the cost. This skill extracts the text locally with
[docling](https://github.com/docling-project/docling), lets Claude read only the sections a question needs,
and flags the pages where text alone can't be trusted (scanned pages, uncaptioned figures) so Claude looks at
those images and no others.

## Numbers

Measured with the free `count_tokens` endpoint on `claude-opus-5` (Sonnet 5 gave identical counts on the 30-page exam).

| Document | Native (text + images) | This skill | Saved |
|---|---|---|---|
| 30-page exam (dense text, one scanned page) | 72,663 | 25,052 | 65.5% (2.9x) |
| &nbsp;&nbsp;same, one question via `--find` | 72,663 | 423 | 99.4% (172x) |
| 6-page report (one scanned page, two images) | 10,109 | 1,053 | 89.6% (9.6x) |
| 2-page résumé | 4,569 | 1,494 | 67.3% (3.1x) |
| 2-page résumé | 4,365 | 1,250 | 71.4% (3.5x) |

Reading a whole document tops out around 65% on dense text: the page images are 62% of the native cost and
that is what's removed, but the remaining text is the document's actual content and can't shrink without
losing it. Beating that means reading less, which is what `--find` is for. At Opus 5's $5 per million input
tokens, the 30-page exam saves about $0.24 per full read and about $0.36 per `--find` lookup.

When a question doesn't share words with the text, `--outline` and `--pages` do the same job by structure. On
the 30-page exam (estimated from character counts, not `count_tokens`): the outline is about 1,800 tokens, 7%
of the document, and the question pages alone (`--pages 3-21`, what a quiz on it needs) about 14,300, 57%.

Four documents is a small sample, and I haven't watched Claude choose search terms in a live session; I picked
terms myself from each question's wording, and 7 of 7 found the answer's section (an eighth question used a
word the document never contains, and correctly found nothing). Measure your own documents before quoting a
number.

**Speed.** The 30-page exam takes about 30 seconds the first time and 0.3 seconds when read again (results are
cached by file content). OCR is about 95% of docling's run time, so it only runs on pages with no text layer:
one page of 30 here, which took the first read from 289 seconds to about 30. The very first run also downloads
docling's models, around 0.5 GB.

## What it adds on top of docling

docling does the hard part: layout, reading order, tables, OCR, dropping headers and footers. Testing it on a
document built to hit every case turned up what it doesn't do, which is what this adds:

1. **Watermarks are stripped.** A diagonal `DRAFT` stamp comes through as a body line on every page. Short
   lines that recur at the same position on 60% or more of the pages (in documents of 4+ pages) are removed.
   A line that doesn't repeat is never touched, so a one-off pull quote near a margin survives.
2. **Scanned pages are flagged.** docling OCRs them silently and reports success even when the result is
   garbled. Every scanned page produces a warning.
3. **Reading less.** `--find "term"` returns just the sections that contain it, each with the page it starts
   on. `--outline` lists the headings with their pages, and `--pages 12-14` returns just those pages. Blank lines
   and doubled spaces are dropped, since a model gets nothing from them.
4. **Page markers** (`<!-- page N -->`), so a warning about page 6 points somewhere and a quote can be cited.
5. **Typed errors instead of tracebacks.** docling raises the same generic error for a missing file, a non-PDF
   and a password-protected one. Here they are separate, with a message you can show a user as-is, and a
   network failure is reported as a network failure rather than as a bad PDF.
6. **Text left as written.** docling's markdown export rewrites `&` as `&amp;` and `max_tokens` as
   `max\_tokens`, which breaks searching for real identifiers; that is switched off.

One Python file of about 260 lines of code (about 420 with comments and docstrings), tests aside.

## Install

**Claude Code (plugin marketplace):**

```
/plugin marketplace add habib049/pdf-to-clean-text
/plugin install pdf-to-clean-text@pdf-to-clean-text
```

**Or copy the skill folder** into `~/.claude/skills/` (every project) or `.claude/skills/` (one project), and
the reader agent into the matching `agents/` folder:

```bash
git clone https://github.com/habib049/pdf-to-clean-text
cp -r pdf-to-clean-text/skills/pdf-to-clean-text ~/.claude/skills/
mkdir -p ~/.claude/agents && cp pdf-to-clean-text/agents/pdf-reader.md ~/.claude/agents/
```

Without the agent the skill still works, but whole-document tasks are read in the main conversation instead of
being handed off.

**Then install its dependencies** (either way):

```bash
pip install -r ~/.claude/skills/pdf-to-clean-text/requirements.txt   # or the plugin's copy
python ~/.claude/skills/pdf-to-clean-text/scripts/pdf_to_clean_text.py --warmup
```

`--warmup` downloads docling's models (about 0.5 GB, a few minutes, needs a network once) so that your first real
PDF isn't the one that stalls. After it, everything works offline. Python 3.10 or newer. Claude asks before
installing anything if the dependencies are missing.

**On Linux, install the CPU-only PyTorch first.** docling needs torch, and the default Linux build bundles
NVIDIA's CUDA libraries and is far larger; the CPU wheel is 187 MB:

```bash
pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
```

**Where it works:** Claude Code and other agents with a local shell. It does not work on the Claude API's code
execution tool, which has no network access and can't install packages. I developed and tested it on macOS
(Apple silicon) with Python 3.12; CI also runs the tests on Linux.

## Use

```bash
python skills/pdf-to-clean-text/scripts/pdf_to_clean_text.py report.pdf > report.md 2> report.log
grep -E '^(info|warning|error):' report.log

# only the sections that mention a term, instead of the whole document
python skills/pdf-to-clean-text/scripts/pdf_to_clean_text.py report.pdf --find "refund policy" --find "3.9"

# the headings with their pages, then only the pages you need
python skills/pdf-to-clean-text/scripts/pdf_to_clean_text.py report.pdf --outline
python skills/pdf-to-clean-text/scripts/pdf_to_clean_text.py report.pdf --pages 12-14

# the short card the reader agent wrote for this PDF, or the outline if it hasn't yet
python skills/pdf-to-clean-text/scripts/pdf_to_clean_text.py report.pdf --map

# where the reader agent keeps this PDF's card and notes, keyed by the file's content
python skills/pdf-to-clean-text/scripts/pdf_to_clean_text.py report.pdf --compiled-paths

# whether those notes cover every page and heading, or were cut down to a summary
python skills/pdf-to-clean-text/scripts/pdf_to_clean_text.py report.pdf --check-notes
```

`--find` prints every section containing any of the terms (a section runs from one `##` heading to the next),
each labelled with the page it starts on, capped at 10. It's a plain case-insensitive match that ignores
hyphens: it finds words that are in the text, not meanings that aren't, so "reimbursement" won't find a
section titled "Refunds".

stdout is the document and nothing else; diagnostics go to stderr as `info:`, `warning:` and `error:` lines.
Exit code 0 on success, 1 on a problem with the PDF, 2 on bad usage. `--no-cache` skips the result cache.

```python
import sys; sys.path.insert(0, "skills/pdf-to-clean-text/scripts")
from pdf_to_clean_text import extract

r = extract("report.pdf")
r.text       # markdown, pages separated by <!-- page N --> markers
r.warnings   # ["page 6: scanned page, text came from OCR and was not verified", ...]
r.figures    # [Figure(page=3, caption="Figure 1: Revenue by quarter")]
```

Imported, it leaves your logging alone and reuses one docling converter per process.

## How the skill behaves

`SKILL.md` routes by what the task needs. A PDF of a few pages is read whole. A question about part of a longer
one goes to `--find`, or `--map` then `--pages`. Whole-document work (a summary, a quiz, a table of everything, a
translation) goes straight to the `pdf-reader` agent, which runs on Haiku, with a four-line prompt: the command,
the PDF, the task and an output file. The agent picks its method: for a gist task it writes a short card and
condensed notes the first time it sees a PDF (cached by the file's content) and works from those; for "every X"
extraction it writes a script over the text instead of reading it; for translation or proofreading it works
through the full text in chunks. It checks its own citations, writes the result to the file and reports back in
under 100 words, so the main conversation never holds the document. Claude falls back to a page's image only where
a warning says the text can't be trusted.

`SKILL.md` stays short (about 650 tokens) because it's loaded every time the skill is used; errors, setup and
limits are in `reference.md`, read only when one of them comes up.

**Status of the agent:** exercised on one 30-page test document and fixed against two real failures found while
doing that (incomplete notes; a note with the wrong answer to a question), but not yet run through the project's
own eval suite or re-benchmarked end to end since those fixes. Treat it as a first cut.

```
pdf-to-clean-text/
├── .claude-plugin/            marketplace.json, plugin.json (for /plugin install)
├── agents/pdf-reader.md       the reader agent (Haiku) for whole-document work
├── skills/pdf-to-clean-text/  the skill: SKILL.md, reference.md, requirements.txt, scripts/pdf_to_clean_text.py
├── tests/                     pytest suite and the generator for its test PDF
├── evals/                     evaluation scenarios (not yet run; see evals/README.md)
└── .github/                   CI and issue template
```

The skill follows the [Agent Skills specification](https://agentskills.io/specification) and Anthropic's
[authoring best practices](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices),
and passes `skills-ref validate` and `claude plugin validate`.

## What the layer changes, on a test file

Measured on the file `tests/make_test_pdf.py` builds: 6 pages with a repeated header and footer, a diagonal
DRAFT watermark, an unruled table, a captioned figure, a one-off quote in the top margin and one image-only
page. It's a stress test, not a typical document.

| | docling alone | with this layer | pymupdf4llm alone |
|---|---|---|---|
| Header / footer / page numbers | removed | removed | left in on every page |
| DRAFT watermark | left in, 5 pages | removed | left in, letters leak into table cells |
| One-off margin quote | kept | kept | kept |
| Table | clean markdown | clean markdown | mangled |
| Figure caption | linked to figure | linked (`r.figures`) | glued onto a paragraph |
| Page boundaries | none | `<!-- page N -->` | none |
| Scanned page | OCR'd, no warning | OCR'd, warning | silently dropped |

pymupdf4llm is there because it's the obvious lightweight alternative; on this file it isn't a substitute.

## Known limits

- **A bad page fails the whole run.** docling converts a document as one unit, so there's no partial result.
  A damaged or truncated PDF is refused outright rather than read partially.
- **OCR quality isn't measured.** On the test file, OCR garbled a line where the watermark crossed the scan
  (`se d r  d  p   yar`). The warning says a page was OCR'd, not that it went wrong.
- **The watermark grid is 20pt.** A stamp that drifts across a grid boundary between pages won't group, and
  survives. Only lines of 40 characters or fewer are candidates, so a long repeated notice stays in.
- **Figures are captions only.** A chart with no caption produces a warning, not a description. docling links a
  caption to its figure through its layout model, which behaved differently on Linux than on macOS for the same
  page, so when there's no link the nearest "Figure N" line touching the picture is used instead.
- **docling joins hyphenated words** split across lines (`large-\nscale` becomes `largescale`) and sometimes
  merges or splits paragraphs. `--find` ignores hyphens so searches still work; body text is otherwise left
  as docling produced it.
- **No password entry, page ranges or JSON output.**
- **docling picks Apple's GPU (MPS) automatically on macOS.** That works on a real Mac, but inside a virtual
  machine, including GitHub's macOS runners, it produced wrong layout results and a crashing table stage. If
  you see that, set `DOCLING_DEVICE=cpu`. The CI workflow does.
- **The first run needs a network** to fetch docling's models. If docling's check-in with Hugging Face fails
  later (flaky network), the conversion is retried from the local cache.
- **Nothing is redacted.** "Clean" doesn't mean safe to share. The result cache stores the extracted text in
  plain form under `~/.cache/pdf-to-clean-text/` (owner-only permissions, at most 200 entries); use
  `--no-cache` for sensitive documents.
- **Everything runs locally**; this code never uploads a PDF. The OCR engine's library, onnxruntime, ships its
  own telemetry client, which I saw active in a crash report. I haven't tested whether `ORT_DISABLE_TELEMETRY=1`
  (a variable name found in the library) turns it off, so if that matters to you, check it yourself.

### A crash that's worked around

On macOS, onnxruntime can abort the process at exit after the work is done: exit code 134 and a "Python quit
unexpectedly" dialog. It was intermittent: I saw it in roughly 1 of every 5 to 8 runs that used OCR. It's a race between its telemetry shutdown and one of its
own threads, not something in this code. The command line and the test suite now exit directly once their output
is flushed, which skips that shutdown (registered exit handlers still run). If you import `extract()` into your
own long-running process you can still hit it when that process exits; ending it with `os._exit` avoids it.

## Tests

```bash
pip install -r requirements-dev.txt
pytest
```

Fifty-two tests, about 25 seconds after the first run. They generate the test PDF and run docling for real,
so there are no checked-in binaries and nothing is mocked in the end-to-end checks. The fixture is synthetic:
reproducible, not representative. See [CONTRIBUTING.md](CONTRIBUTING.md) before sending a change.

## License

MIT, see [LICENSE](LICENSE). The dependencies are permissive too: docling (MIT), pypdfium2 (BSD-3-Clause or
Apache-2.0), RapidOCR (Apache-2.0), onnxruntime (MIT), torch (BSD-style). The model weights docling downloads are Apache-2.0 and
CDLA-Permissive-2.0 according to their Hugging Face model cards.
