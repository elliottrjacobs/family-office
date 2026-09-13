---
name: briefing
description: Use for briefing questions and reports; review evidence, assumptions,
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
  - sync status
  - brief
  - quote
  report-kind: briefing
---

# Briefing

Follow the skill skeleton in AGENTS.md.

Produce a concise read-only briefing from the last review, coverage status, holdings, and cached quotes. Run every command with --read-only. Use no web search or worker delegation. Separate stale or unavailable evidence from current facts.

Run the commands declared in metadata with --json. Use fo start for the report path and prior. Include Evidence, Analysis, Data gaps, and Next actions. Include What changed when a prior exists. Cite applicable corrections and explain how the proposed action complies.

Close the report with: Reply with corrections in your next task.
