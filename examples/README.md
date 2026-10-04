# Examples

Three real usage patterns, each with actual command output (not illustrative text) from a 30-page practice-exam
PDF used during development. See [`../BENCHMARK.md`](../BENCHMARK.md) for how the token numbers were measured.

| File | When to use it | Tokens for this PDF |
|---|---|---|
| [`targeted-question.md`](targeted-question.md) | One question, and it shares wording with the document | ~423 (measured) |
| [`navigate-by-structure.md`](navigate-by-structure.md) | One question, but the wording doesn't match, or `--find` missed | ~1,800–16,000 (estimated) |
| [`whole-document-task.md`](whole-document-task.md) | A summary, quiz, translation or anything covering the whole document | see the file's own caveat |

The first two are exact-text lookups: deterministic script output, same every run. The third hands the work to
the `pdf-reader` agent, which is model-generated and has not yet been re-benchmarked since its last fix (see
the CHANGELOG's "Known gaps") — that file is a usage pattern, not a performance claim.
