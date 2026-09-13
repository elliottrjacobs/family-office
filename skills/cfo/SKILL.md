---
name: cfo
description: Use for cfo questions and reports; review evidence, assumptions, and
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
  - spend
  - cashflow
  - goals
  report-kind: cfo
---

# Cfo

Follow the skill skeleton in AGENTS.md.

Assess liquidity, recurring cash flow, spending trends, debt service, and goal funding. Separate transfers and exceptional items from operating spending. Prioritize actions by household consequence and distinguish missing accounts from zero balances.

Run the commands declared in metadata with --json. Use fo start for the report path and prior. Include Evidence, Analysis, Data gaps, and Next actions. Include What changed when a prior exists. Cite applicable corrections and explain how the proposed action complies.

Close the report with: Reply with corrections in your next task.
