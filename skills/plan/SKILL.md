---
name: plan
description: "Turn household goals into an ordered plan with scenarios, dependencies, and checkpoints: retirement, college, a home purchase, a sabbatical. Use for 'are we on track', 'when can we retire', 'plan for X'."
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
