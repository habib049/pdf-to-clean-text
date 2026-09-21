# Evaluations

Scenarios in the format from Anthropic's [skill authoring best practices](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices#build-evaluations-first).
There is no built-in runner: give each `query` to Claude with the skill installed and check the result against
`expected_behavior`.

They use the test PDF, which is generated rather than checked in:

```bash
python tests/make_test_pdf.py   # writes tests/test.pdf
```

**Status:** these have not been run yet. Anthropic recommends testing with Haiku, Sonnet and Opus, and each run
costs API credits. Results, once gathered, belong in the changelog.
