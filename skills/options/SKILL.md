---
name: options
description: Use for options questions and reports; review evidence, assumptions,
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
  - positions
  - lots
  - quote
  report-kind: options
---

# Options

Follow the skill skeleton in AGENTS.md.

Explain payoff, assignment, expiry, liquidity, and tax consequences. Require sourced chain and volatility evidence for any strategy pricing; if unavailable, report the gap and give no fabricated premium or Greeks. Never execute a trade.

Run the commands declared in metadata with --json. Use fo start for the report path and prior. Include Evidence, Analysis, Data gaps, and Next actions. Include What changed when a prior exists. Cite applicable corrections and explain how the proposed action complies.

Close the report with: Reply with corrections in your next task.
