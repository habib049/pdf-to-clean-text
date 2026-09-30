# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- A `pdf-reader` agent (Haiku) for whole-document work: summaries, quizzes, study guides, tables of everything,
  translations. `SKILL.md` hands it a fixed four-line prompt (command, PDF, task, output file) rather than
  reading the document itself, so the main conversation never holds the document's text. The first time it sees
  a PDF it reads the whole thing and writes condensed notes plus a short card, cached by the file's content, and
  reuses them on later requests; for "every X" extraction it writes a script over the text instead of reading
  it; for translation or proofreading it works through the full text in chunks.
- `--map` prints the agent's card (about 150 words) when it exists, otherwise the outline; `--compiled-paths`
  prints where the card and notes are kept.
- `--check-notes` checks the agent's notes mechanically before it may mark them complete: every page with text
  has a note tagged with its page, every numbered heading label (`Question 5.9`, `Section 4.2`) appears, and the
  notes are at least 20% of the text's length. An earlier version without this gate let Haiku skip the
  introduction and the whole answer key (39% of the test document) and still report success, and separately
  produced a note with the wrong answer to a question — this checks structure, not correctness, so it would not
  have caught that second failure; the notes-writing instructions were rewritten instead to fix it
  ("record, don't interpret").
- `SKILL.md`'s whole-document route now delegates to `pdf-reader` immediately, instead of describing how to read
  the PDF directly for that case.

### Changed
- `SKILL.md` is about 650 tokens, down from about 1,500: errors, setup and limits moved to `reference.md`, which
  is read only when one of them comes up. It's loaded every time the skill is used, so this is paid on every
  question.

### Known gaps
- The agent design here has been exercised on one 30-page test document and iterated against two real failures
  (incomplete notes; a wrong answer reaching a generated quiz). It has not yet been run through the project's
  own eval suite, and the fixes for both failures have not been re-benchmarked end to end since being written.
  Treat this as a first cut, not a verified result.
- A figure whose caption docling didn't link (it varies by platform: linked on macOS, not on Linux) got a false
  "no caption found" warning. The nearest "Figure N" line beside the picture is now used.
- A clean install had no `onnxruntime`, so docling's OCR fell back to a PyTorch backend that downloads its models
  from modelscope.cn on the first scanned page (a 502 there failed a CI run). `requirements.txt` now asks for
  `docling[rapidocr]`, the official extra, which brings CPU `onnxruntime` and uses the models bundled in the wheel.
- CI on Linux failed with "operator torchvision::nms does not exist": `torch` and `torchvision` are now installed
  together from the CPU index. CI on macOS runs docling on the CPU, because docling's automatic choice of Apple's
  GPU (MPS) gave wrong results inside GitHub's virtual machines.

## [0.1.0] - 2026-09-21

First release.

### Added
- `pdf-to-clean-text` skill: converts a PDF to markdown with docling, with `<!-- page N -->` markers.
- `--find TERM` returns only the sections that contain a term, labelled with their start page.
- Watermark removal: short lines repeated at the same position on 60% or more of pages.
- Warnings for scanned (OCR'd) pages and for figures without a caption.
- Typed errors for missing, non-PDF, damaged, password-protected and empty files, and for network
  failures while docling's models are still being downloaded.
- Result cache keyed by file content and docling version, owner-only, capped at 200 entries;
  `--no-cache` to skip it.
- Claude Code plugin marketplace manifest, so the skill installs with `/plugin install`.

### Performance
- OCR runs only on pages without a text layer: a 30-page test document went from 289 s to about 30 s.
- Repeat reads of the same file come from the cache in under a second.

[Unreleased]: https://github.com/habib049/pdf-to-clean-text/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/habib049/pdf-to-clean-text/releases/tag/v0.1.0
