# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- `--warmup` downloads docling's models (about 0.5 GB) up front by converting a tiny built-in PDF, so the first
  real document isn't the one that stalls. docling's own `docling-tools models download` isn't used: it saves to
  `~/.cache/docling`, but conversions read the Hugging Face cache, so the models would be fetched twice.
- README: install CPU-only PyTorch on Linux (a 187 MB wheel instead of the CUDA build).

### Fixed
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
