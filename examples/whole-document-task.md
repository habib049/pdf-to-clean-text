# Whole-document task: the `pdf-reader` agent

> **Caveat before reading this one:** unlike the other two examples, this isn't a reproducible, measured
> number — it's a usage pattern. The `pdf-reader` agent is model-generated and has been exercised on one test
> document, with two real failures found and fixed during that process (see the CHANGELOG's "Known gaps"). It
> has not been re-benchmarked end to end since. Treat the shape of this example as correct; don't quote its
> numbers as a verified result.

**Task:** "Make a 10-question quiz from exam.pdf, covering all six scenarios, with a cited answer key."

For whole-document work like this (also: study guides, tables of everything, translation, proofreading),
`SKILL.md` tells Claude to skip reading the PDF itself and delegate immediately, with a fixed four-line prompt:

```
CMD: python /path/to/scripts/pdf_to_clean_text.py
PDF: /path/to/exam.pdf
TASK: Make a 10-question quiz from exam.pdf, covering all six scenarios, with a cited answer key.
OUTPUT: /path/to/quiz.md
```

The agent (configured to run on Haiku) then, on its own:

1. Checks `--compiled-paths` for cached notes from a previous run on this exact file. None yet, so it builds
   them: reads the whole document, writes condensed (not summarized) notes tagged by page, and runs
   `--check-notes` until every page and numbered heading is accounted for.
2. Writes the quiz from the notes, citing pages, spreading correct answers across letters rather than
   clustering on one.
3. Checks its own output against the notes before saving it.
4. Reports back in under 100 words — path, contents, method used, any warnings — without pasting the quiz or
   the notes into the reply.

The main conversation ends up holding the four-line delegation prompt and a short report: not the document,
not the intermediate notes, not the generated quiz. On a later request against the same PDF ("make it harder",
"add five more"), the notes are already built, so that step is skipped.

**No `pdf-reader` agent installed?** The skill still works — `SKILL.md` falls back to reading the document
yourself in `--pages` chunks, which costs more main-conversation tokens but needs no agent.
