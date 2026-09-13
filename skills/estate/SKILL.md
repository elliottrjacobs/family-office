---
name: estate
description: Use for estate questions and reports; review evidence, assumptions, and
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
  - networth
  - goals
  report-kind: estate
---

# Estate

Follow the skill skeleton in AGENTS.md.

Identify household continuity, beneficiary, title, insurance, and document gaps. Distinguish verified documents from intended arrangements. Prioritize questions for qualified counsel; do not imply legal validity from a checklist.

Run the commands declared in metadata with --json. Use fo start for the report path and prior. Include Evidence, Analysis, Data gaps, and Next actions. Include What changed when a prior exists. Cite applicable corrections and explain how the proposed action complies.

Close the report with: Reply with corrections in your next task.
