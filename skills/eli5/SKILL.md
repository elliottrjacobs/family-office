---
name: eli5
description: Use for eli5 questions and reports; review evidence, assumptions, and
  prior decisions.
metadata:
  tier: fast
  default-context: none
  allowed-context:
  - none
  - household
  - full
  invocation: implicit
  args: <subject>
  commands:
  - brief
  report-kind: eli5
---

# Eli5

Follow the skill skeleton in AGENTS.md.

Restate the preceding output using familiar language and a concrete example. Preserve uncertainty, assumptions, action, and invalidation. Do not introduce new recommendations or change the underlying figures.

Run the commands declared in metadata with --json. Use fo start for the report path and prior. Include Evidence, Analysis, Data gaps, and Next actions. Include What changed when a prior exists. Cite applicable corrections and explain how the proposed action complies.

Close the report with: Reply with corrections in your next task.
