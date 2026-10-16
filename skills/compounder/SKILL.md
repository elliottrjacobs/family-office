---
name: compounder
description: "Score a company with the compounder playbook. Use for 'compounder score', 'is this a long-term compounder', or 'can it reinvest at high returns'. Gives an evidence scorecard, never a mechanical buy or sell verdict."
metadata:
  tier: balanced
  group: playbooks
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

# Compounder

Follow the skill skeleton in AGENTS.md.

Apply the compounder playbook from fo score. Explain each judgment criterion using evidence, distinguish unknown from fail, and examine sensitivity to assumptions. The mechanical score never writes the verdict. Journal only when the user requests a recommendation; otherwise provide a scorecard for diligence.

Run the commands declared in metadata with --json. Use fo start for the report path and prior. Include Evidence, Analysis, Data gaps, and Next actions. Include What changed when a prior exists. Cite applicable corrections and explain how the proposed action complies.

Close the report with: Reply with corrections in your next task.
