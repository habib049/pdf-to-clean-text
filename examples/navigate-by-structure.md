# Navigate by structure: `--outline` then `--pages`

Same 30-page exam PDF. This time the question doesn't share vocabulary with the document, so `--find` isn't the
right first move — searching for words the document doesn't use just returns nothing.

**Question:** "Make a 10-question quiz covering the exam's six scenarios."

There's no single term to search for; this needs to know the document's shape first.

```bash
python scripts/pdf_to_clean_text.py exam.pdf --outline
```

Real output, first 15 of 138 lines (~1,800 tokens estimated, 7% of the full 25,052-token extraction):

```
p1 Claude Certified Architect Foundations
p2 Claude Certified Architect - Foundations
p2 Practice Question Set
p2 How the 60 questions are distributed
p2 Question formats you'll encounter
p3 Scenario 1: Customer Support Resolution Agent
p3 Question 1.1 · Multiple choice · select ONE · Domain 1
p3 Question 1.2 · Multiple choice · select ONE · Domain 1
p3 Question 1.3 · Multiple choice · select ONE · Domain 1
p4 Question 1.4 · Multiple choice · select ONE · Domain 1
p4 Question 1.5
p4 Question 1.6 · Multiple choice · select ONE · Domain 2
p5 Question 1.7 · Multiple choice · select ONE · Domain 2
p5 Question 1.8 · Multiple response · select TWO · Domain 2
p5 Question 1.9
```

From this, it's clear the six scenarios run pages 3–21 (the rest is the cover, intro and answer key — not
needed for writing new questions). Fetch just that range:

```bash
python scripts/pdf_to_clean_text.py exam.pdf --pages 3-21
```

Real output: 40,605 characters, ~13,535 tokens (estimated) — 54% of the full extraction, 81% less than native
reading, and it covers exactly the six scenarios a quiz needs without guessing at page numbers.

**The pattern:** outline for structure (a few percent of the tokens), then pages for content (only the ones
the task needs). Falls back to reading the whole document only if the outline still doesn't answer where to
look.
