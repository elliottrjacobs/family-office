---
name: realestate
description: Use for realestate questions and reports; review evidence, assumptions,
  and prior decisions.
metadata:
  tier: balanced
  default-context: household
  allowed-context:
  - none
  - household
  - full
  invocation: implicit
  args: <subject>
  commands:
  - networth
  - cashflow
  report-kind: realestate
---

# Realestate

Follow the skill skeleton in AGENTS.md.

Compare property economics, vacancy, maintenance, financing, liquidity, and exit assumptions. Distinguish asking prices from closed comparables. State missing property evidence and use sourced cash flows for any return calculation.

Run the commands declared in metadata with --json. Use fo start for the report path and prior. Include Evidence, Analysis, Data gaps, and Next actions. Include What changed when a prior exists. Cite applicable corrections and explain how the proposed action complies.

Close the report with: Reply with corrections in your next task.
