---
name: review
description: Use for review questions and reports; review evidence, assumptions, and
  prior decisions.
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
  - review
  - journal list
  report-kind: review
---

# Review

Follow the skill skeleton in AGENTS.md.

Run fo review; a breach exit code means inspect its result. Evaluate breached decisions and those due for verdict. Ask for a verdict only where judgment is needed, record it with fo journal close, and inspect calibration without claiming causality.

Run the commands declared in metadata with --json. Use fo start for the report path and prior. Include Evidence, Analysis, Data gaps, and Next actions. Include What changed when a prior exists. Cite applicable corrections and explain how the proposed action complies.

Close the report with: Reply with corrections in your next task.
