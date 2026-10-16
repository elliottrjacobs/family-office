---
name: realestate
description: "Evaluate a property purchase, rental, or sale: cash flows, vacancy, maintenance, financing, liquidity, and exit. Use for 'should we buy this house', 'rent versus buy', 'is this rental worth it', 'refinance'."
metadata:
  tier: balanced
  group: specialists
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
