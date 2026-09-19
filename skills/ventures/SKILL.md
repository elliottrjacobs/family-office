---
name: ventures
description: "Evaluate a private business or startup stake the household owns or may fund: unit economics, runway, governance, and household exposure. Use for 'my company', 'angel investment', 'should I put more into the business'."
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
