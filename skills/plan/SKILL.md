---
name: plan
description: Use for plan questions and reports; review evidence, assumptions, and
  prior decisions.
metadata:
  tier: balanced
  default-context: full
  allowed-context:
  - none
  - household
  - full
  invocation: implicit
  args: <subject>
  commands:
  - goals
  - cashflow
  - networth
  report-kind: plan
---

# Plan

Follow the skill skeleton in AGENTS.md.

Turn household goals into ordered decisions, dependencies, and measurable checkpoints. Compare scenarios and constraints. Identify information needed from qualified professionals and do not invent legal or tax facts.

Run the commands declared in metadata with --json. Use fo start for the report path and prior. Include Evidence, Analysis, Data gaps, and Next actions. Include What changed when a prior exists. Cite applicable corrections and explain how the proposed action complies.

Close the report with: Reply with corrections in your next task.
