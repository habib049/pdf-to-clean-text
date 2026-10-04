# Targeted question: `--find`

Document: a 30-page practice-exam PDF, 72,663 tokens read natively, 25,052 as a full clean extraction.

**Question:** "Which MCP capability reduces subagents burning tool calls just discovering what data exists?"

The question doesn't quote the document verbatim, but "MCP" and "resources" are words the document actually
uses, so a search on those terms is the first thing to try — not the whole document.

```bash
python scripts/pdf_to_clean_text.py exam.pdf --find "MCP resources"
```

Real output (423 tokens, measured with `count_tokens`):

```
<!-- match: starts on page 11 -->
## Question 3.7 ·   Multiple choice · select ONE   ·   Domain 2

Subagents burn many tool calls just discovering what data exists - listing available document collections, probing for issue summaries, checking what schemas are present - before real work begins. Which MCP capability reduces this?

- A. Expose content catalogs (document hierarchies, issue summaries, schema listings) as MCP resources
- B. Increase the tool-call budget so exploration is affordable
- C. Hard-code the current data inventory into every system prompt
- D. Add a describe_available_data tool that every agent calls once at startup to fetch the current inventory

<!-- page 12 -->

<!-- match: starts on page 25 -->
## 3.7 - Correct: A

MCP resources exist for exactly this: exposing catalogs of available content so agents start
informed. Discovery becomes a lookup instead of a spelunking expedition of exploratory calls.

Why not the others: B pays for the inefficiency rather than removing it; C goes stale the moment the data
changes; D rebuilds the same capability as a bespoke tool - resources are the protocol's designed primitive
for exposing content catalogs.
```

Both the question (page 11) and its answer-key rationale (page 25) came back in one call, because `--find`
searches the whole extracted document, not just nearby text. **423 tokens** against a 72,663-token native read
— a 172x reduction — because the other ~29 pages were never loaded.

**Why it worked:** the search term ("MCP resources") appears in the document's own text. See
[`navigate-by-structure.md`](navigate-by-structure.md) for what to do when it doesn't.
