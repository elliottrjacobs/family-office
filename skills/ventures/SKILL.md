---
name: ventures
description: Use for ventures questions and reports; review evidence, assumptions,
  and prior decisions.
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
  - cashflow
  - goals
  report-kind: ventures
---

# Ventures

Follow the skill skeleton in AGENTS.md.

Evaluate business unit economics, runway, concentration, reinvestment, governance, and household exposure. Separate company and household cash flows. Treat entity and tax changes as proposals needing jurisdiction-specific evidence.

Run the commands declared in metadata with --json. Use fo start for the report path and prior. Include Evidence, Analysis, Data gaps, and Next actions. Include What changed when a prior exists. Cite applicable corrections and explain how the proposed action complies.

Close the report with: Reply with corrections in your next task.
