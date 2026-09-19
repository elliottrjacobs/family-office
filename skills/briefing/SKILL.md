---
name: briefing
description: "Quick read-only status from cached data: holdings, sync coverage, last review, and quotes. Use for 'brief me', 'morning briefing', 'where do things stand'. No web search and no new analysis."
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
