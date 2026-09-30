# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- `--outline` prints each heading with its page (about 7% of the 30-page exam's tokens), and `--pages 3-5` prints
  only those pages, so a question that shares no words with the text can still be answered without reading
  everything.
- `SKILL.md` routes by what the task needs: read short documents whole, search or navigate a longer one for a
  targeted question, read a whole document once for gist work.
- `--warmup` downloads docling's models (about 0.5 GB) up front by converting a tiny built-in PDF, so the first
  real document isn't the one that stalls, and runs the OCR path once too, so a broken OCR install shows up there
  rather than on the first scanned page. docling's own `docling-tools models download` isn't used: it saves to
  `~/.cache/docling`, but conversions read the Hugging Face cache, so the models would be fetched twice.
- README: install CPU-only PyTorch on Linux (a 187 MB wheel instead of the CUDA build).

### Changed
- Blank lines and doubled spaces are dropped from the output: 41% fewer lines on the 30-page exam, about 5% fewer
  tokens once the Read tool's per-line numbering is counted.
- The result cache is keyed by a hash of the script itself instead of a hand-bumped version number, so a change
  to the output can't be served stale from the cache.

### Fixed
- A figure caption set beside the figure (as in some two-column layouts), rather than above or below it, wasn't
  found by the caption fallback.
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
