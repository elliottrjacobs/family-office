---
name: technicals
description: Use for technicals questions and reports; review evidence, assumptions,
  and prior decisions.
metadata:
  tier: balanced
  default-context: none
  allowed-context:
  - none
  - household
  - full
  invocation: implicit
  args: <subject>
  commands:
  - quote
  report-kind: technicals
---

# Technicals

Follow the skill skeleton in AGENTS.md.

Assess trend, volatility, support, resistance, and invalidation only from dated price-series evidence. A current quote is insufficient to infer a chart. Report unavailable history rather than constructing indicators from memory.

Run the commands declared in metadata with --json. Use fo start for the report path and prior. Include Evidence, Analysis, Data gaps, and Next actions. Include What changed when a prior exists. Cite applicable corrections and explain how the proposed action complies.

Close the report with: Reply with corrections in your next task.
