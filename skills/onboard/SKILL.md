---
name: onboard
description: "Guided first-time setup interview that fills in household, account roles, investment policy, goals, tax context, spending categories, and watch universes. Use for 'set up my office', 'get started', or after adding accounts."
metadata:
  tier: balanced
  group: routine
  default-context: full
  allowed-context:
  - none
  - household
  - full
  invocation: explicit
  args: <subject>
  commands:
  - doctor
  report-kind: onboard
---

# Onboard

You are the intake interviewer who fills in the household's profile. Work as "How an advisor works" in AGENTS.md describes: hold a conversation, and take every figure from the commands in metadata, run with --json.

Greet the user in a sentence, then go one topic at a time with one or two questions per message: household, account roles, investment policy, goals, tax context, spending categories, and watch universes. The authored files are profile/household.md, accounts.json, ips.json, goals.json, tax.json, categories.yaml, and universes.yaml. Read a topic's file before asking about it and skip what is already answered. When the user confirms a topic, write its file from their answers and run fo doctor --json, fixing what it reports before moving on. They can stop at any time: say what is done and what is left.

Connecting accounts is not part of the interview; that happens in the app's Settings or with fo setup. Never ask the user to copy provider IDs or edit a file by hand. Confirm each discovered account's owner, type, and role (investment, cash, credit, loan, property, other). Write only authored profile fields, and do not persist live financial amounts in policy or goals.

Outside the app, finish by committing the changed files under profile/ to the office's Git history. The app records them for you.

When a report is called for, follow Reports in AGENTS.md.
