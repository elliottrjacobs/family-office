---
name: all-weather
description: Use for all weather questions and reports; review evidence, assumptions,
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
  - score-portfolio
  report-kind: score
---

# All Weather

Follow the skill skeleton in AGENTS.md.

Apply the all-weather playbook from fo score-portfolio. Explain each judgment criterion using evidence, distinguish unknown from fail, and examine sensitivity to assumptions. The mechanical score never writes the verdict. Journal only when the user requests a recommendation; otherwise provide a scorecard for diligence.

Run the commands declared in metadata with --json. Use fo start for the report path and prior. Include Evidence, Analysis, Data gaps, and Next actions. Include What changed when a prior exists. Cite applicable corrections and explain how the proposed action complies.

Close the report with: Reply with corrections in your next task.
