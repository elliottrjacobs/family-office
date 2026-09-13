---
name: tax
description: Use for tax questions and reports; review evidence, assumptions, and
  prior decisions.
metadata:
  tier: strong
  default-context: full
  allowed-context:
  - none
  - household
  - full
  invocation: implicit
  args: <subject>
  commands:
  - lots
  - allocation
  - cashflow
  report-kind: tax
---

# Tax

Follow the skill skeleton in AGENTS.md.

Evaluate tax-sensitive choices from sourced basis, holding periods, account treatment, and authored tax context. Identify missing elections and filing facts. Make assumptions explicit and require professional confirmation of jurisdiction-specific conclusions.

Run the commands declared in metadata with --json. Use fo start for the report path and prior. Include Evidence, Analysis, Data gaps, and Next actions. Include What changed when a prior exists. Cite applicable corrections and explain how the proposed action complies.

Close the report with: Reply with corrections in your next task.
