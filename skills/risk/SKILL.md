---
name: risk
description: "Stress-test the household portfolio: concentration, liquidity, leverage, correlation assumptions, policy violations, and downside scenarios. Use for 'what is my biggest risk', 'too concentrated in X', 'what if markets fall 30%'."
metadata:
  tier: balanced
  group: specialists
  default-context: full
  allowed-context:
  - none
  - household
  - full
  invocation: implicit
  args: <subject>
  commands:
  - performance
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
