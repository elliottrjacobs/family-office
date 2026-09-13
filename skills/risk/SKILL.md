---
name: risk
description: Use for risk questions and reports; review evidence, assumptions, and
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
  - allocation
  - concentration
  - networth
  report-kind: risk
---

# Risk

Follow the skill skeleton in AGENTS.md.

Assess concentration, liquidity, leverage, correlation assumptions, and policy violations. Trace household consequences under explicit downside scenarios. Run allocation and concentration before reasoning; all assessment occurs in this session.

Run the commands declared in metadata with --json. Use fo start for the report path and prior. Include Evidence, Analysis, Data gaps, and Next actions. Include What changed when a prior exists. Cite applicable corrections and explain how the proposed action complies.

Close the report with: Reply with corrections in your next task.
