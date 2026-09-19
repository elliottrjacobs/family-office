---
name: onboard
description: "Guided first-time setup interview that fills in household, account roles, investment policy, goals, tax context, spending categories, and watch universes. Use for 'set up my office', 'get started', or after adding accounts."
metadata:
  tier: balanced
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

Follow the skill skeleton in AGENTS.md.

Interview for household, policy, goals, tax context, categories, and universes. Account discovery belongs to fo setup; never ask the user to copy provider IDs or edit configuration manually. Confirm each discovered account's owner, type, and role (investment, cash, credit, loan, property, other). Write only authored profile fields from user answers and run fo doctor after each file. Do not persist live financial amounts in policy or goals.

Run the commands declared in metadata with --json. Use fo start for the report path and prior. Include Evidence, Analysis, Data gaps, and Next actions. Include What changed when a prior exists. Cite applicable corrections and explain how the proposed action complies.

Close the report with: Reply with corrections in your next task.
