---
name: marks
description: "Score an idea or the market with the marks playbook. Use for 'marks score', 'where are we in the cycle', or 'second-level thinking and risk check in the style of Howard Marks'. Gives an evidence scorecard, never a mechanical buy or sell verdict."
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
  - score
  report-kind: score
---

# Marks

Follow the skill skeleton in AGENTS.md.

Apply the marks playbook from fo score. Explain each judgment criterion using evidence, distinguish unknown from fail, and examine sensitivity to assumptions. The mechanical score never writes the verdict. Journal only when the user requests a recommendation; otherwise provide a scorecard for diligence.

Run the commands declared in metadata with --json. Use fo start for the report path and prior. Include Evidence, Analysis, Data gaps, and Next actions. Include What changed when a prior exists. Cite applicable corrections and explain how the proposed action complies.

Close the report with: Reply with corrections in your next task.
