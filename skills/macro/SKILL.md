---
name: macro
description: "Read economic conditions from dated data series: growth, inflation, labor, rates, and liquidity, with scenarios and portfolio transmission. Use for 'what is the economy doing', 'recession risk', 'rates outlook'."
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
  - macro
  report-kind: macro
---

# Macro

Follow the skill skeleton in AGENTS.md.

Separate observed economic data from forecasts. Compare growth, inflation, labor, liquidity, and policy scenarios; state revisions and publication dates. Explain transmission channels and what would change the scenario.

Run the commands declared in metadata with --json. Use fo start for the report path and prior. Include Evidence, Analysis, Data gaps, and Next actions. Include What changed when a prior exists. Cite applicable corrections and explain how the proposed action complies.

Close the report with: Reply with corrections in your next task.
