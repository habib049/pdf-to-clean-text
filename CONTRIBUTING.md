# Contributing

Bug reports and pull requests are welcome.

## Reporting a bug

Open an issue using the bug report template. The most useful thing you can attach is a PDF that
reproduces the problem. If the document is private, describe it instead: page count, whether it is
scanned, and whether it has tables, columns or a watermark.

## Making a change

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
pytest
```

The first test run downloads docling's models (about 0.5 GB). After that the suite takes about 25 seconds.

- The skill itself is `skills/pdf-to-clean-text/`: `SKILL.md` and one script. Keep it that small.
- A behaviour change needs a test in `tests/test_extract.py`. The fixture PDF comes from
  `tests/make_test_pdf.py`, so no binary files are checked in.
- If the output format changes, bump `CACHE_VERSION` in the script so old cached results are ignored.
- Keep `SKILL.md` within the [Agent Skills specification](https://agentskills.io/specification) and
  check it with [skills-ref](https://github.com/agentskills/agentskills/tree/main/skills-ref):
  `skills-ref validate skills/pdf-to-clean-text`.
- If you change `.claude-plugin/`, run `claude plugin validate .`.
- Add a line under `[Unreleased]` in `CHANGELOG.md`.

## Claims about token savings

Numbers in the README are measured with Anthropic's `count_tokens` endpoint, not estimated. Please keep
it that way, and say which documents a number came from.
