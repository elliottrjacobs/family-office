---
name: scout
description: "Find new investment candidates by turning an idea into an explicit screen over SEC data and a universe. Use for 'find me stocks like X', 'screen for Y', 'what should I look at next'. Produces candidates, not recommendations."
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
  - screen
  - allocation
  report-kind: scout
---

# Scout

Follow the skill skeleton in AGENTS.md.

Translate the requested opportunity into an explicit screen concept, period, and universe. Explain selection bias, disqualifiers, portfolio overlap, and the next evidence needed. A screen result is a candidate, not a recommendation.

Run the commands declared in metadata with --json. Use fo start for the report path and prior. Include Evidence, Analysis, Data gaps, and Next actions. Include What changed when a prior exists. Cite applicable corrections and explain how the proposed action complies.

Close the report with: Reply with corrections in your next task.
