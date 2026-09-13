# Skill authoring

Canonical skills live under skills/ and use Agent Skills frontmatter: name,
description, and metadata. Keep the description under 250 characters and the
whole file at most 3000 bytes. Include metadata keys tier, default-context,
allowed-context, args, commands, and invocation; tier, default-context, args, and invocation are strings; allowed-context and commands are arrays.

Reference the office AGENTS.md skeleton rather than repeating it. Skills own
judgment rubrics and output sections. Provider names, host tool names, concrete
model names, and financial thresholds belong in the CLI or configuration.

The public .agents/skills/ and .claude/skills/ entries are relative symlinks to
skills/. An office uses fo skills sync to create physical rendered copies under
.agents/skills/ and symlinks under .claude/skills/. Supporting rubric files are
copied with the skill. Generated files are disposable and ignored in Git.

Model tiers map through office.toml. Claude skill models are rendered into
frontmatter. Codex workers carry model settings; main-session skills use the
session model. Never claim per-skill model switching in a Codex main session.
