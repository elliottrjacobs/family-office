---
name: journal
description: "Record an investment decision with its thesis, invalidation conditions, and conviction so it can be reviewed later. Use for 'log this decision', 'journal that I bought X', 'write down my thesis'."
metadata:
  tier: fast
  default-context: none
  allowed-context:
  - none
  - household
  - full
  invocation: explicit
  args: <subject>
  commands:
  - journal add
  - journal list
  report-kind: journal
---

# Journal

Follow the skill skeleton in AGENTS.md.

Interview for subject, action, thesis, invalidation, conviction, and source. Use fo journal add to record the decision and return its ID. Use machine clauses only when the metric and units are supported; retain qualitative invalidation as prose.

Run the commands declared in metadata with --json. Use fo start for the report path and prior. Include Evidence, Analysis, Data gaps, and Next actions. Include What changed when a prior exists. Cite applicable corrections and explain how the proposed action complies.

Close the report with: Reply with corrections in your next task.
