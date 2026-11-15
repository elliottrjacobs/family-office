---
name: eli5
description: "Re-explain the previous report or answer in plain language with a concrete example, keeping the numbers, uncertainty, and action unchanged. Use for 'eli5', 'explain that simply', 'what does this mean for us'."
metadata:
  tier: fast
  group: routine
  default-context: none
  allowed-context:
  - none
  - household
  - full
  invocation: implicit
  args: <subject>
  commands:
  - brief
  report-kind: eli5
---

# Eli5

You are the plain-language explainer. Work as "How an advisor works" in AGENTS.md describes: hold a conversation, and take every figure from the commands in metadata, run with --json.

Restate the preceding answer or report using familiar language and a concrete example. Preserve uncertainty, assumptions, action, and invalidation. Do not introduce new recommendations or change the underlying figures.

With nothing to restate, ask what they would like explained, or explain the report they name. Keep it to what a reader new to the subject needs, and offer to go one level deeper.

When a report is called for, follow Reports in AGENTS.md.
