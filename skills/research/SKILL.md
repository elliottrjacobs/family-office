---
name: research
description: Use for research questions and reports; review evidence, assumptions,
  and prior decisions.
metadata:
  tier: balanced
  default-context: none
  allowed-context:
  - none
  - household
  - full
  invocation: implicit
  args: <subject> [--deep]
  commands:
  - fundamentals
  - quote
  - filings
  - lots
  report-kind: research
---

# Research

Follow the skill skeleton in AGENTS.md.

Assess business economics, competitive advantage, management allocation, growth durability, valuation scenarios, catalysts, and disconfirming evidence. Explain assumptions and data gaps. When --lens is provided, read lenses/<name>.md. When --playbooks is provided, run fo score for each named playbook and integrate evidence, not just tally scores.

Run the commands declared in metadata with --json. Use fo start for the report path and prior. Include Evidence, Analysis, Data gaps, and Next actions. Include What changed when a prior exists. Cite applicable corrections and explain how the proposed action complies.

Only with --deep, delegate evidence slices to fundamentals-analyst, competitive-analyst, valuation-analyst, risk-analyst, sentiment-analyst. First run compute commands and save results under the report part directory using fo report path --part inputs. Workers read those inputs and return bounded blocks without shell or writes. The orchestrator writes each result. Use fo report parts --kind <kind> --subject <subject> to list completed and missing blocks. Reuse completed parts, request only missing parts, and assemble the final report. On a host without workers, perform those slices sequentially.

Close the report with: Reply with corrections in your next task.
