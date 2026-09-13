---
title: Family Office - Plan
type: feat
date: 2026-09-12
artifact_contract: ce-unified-plan/v1
artifact_readiness: implementation-ready
product_contract_source: ce-plan-bootstrap
execution: code
deepened: 2026-09-12
---

# Family Office - Plan

**Target repo:** `elliottrjacobs/family-office` (this checkout). Paths under `office/` refer to the private office root, which lives outside this repo.

## Goal Capsule

- **Objective:** Replace the v1 prompt-only plugin with a Python CLI (`fo`) that owns every deterministic fact and computation, a private git-tracked office that is the single source of truth, and a roster of thin skills served to Claude Code and Codex (OpenAI's agent, now shipped as the ChatGPT desktop app, the Codex CLI, the Codex IDE extension, and Codex cloud) from one copy.
- **Authority hierarchy:** this plan, then `AGENTS.md` conventions written in U2, then the draft v2 plan at `docs/plans/references/family-office-v2-draft.md` (reference only; this plan supersedes it where they differ, see Departures from the draft).
- **Stop conditions:** never read, copy, or commit anything from the real office (the iCloud vault "Jacobs Family Office") except through `fo migrate-v1` when Elliott runs it; never add a code path that writes to a brokerage, bank, or card provider; never track a path under `office/` in this repo; stop and ask if a phase's acceptance check cannot be met without changing a Key Technical Decision.
- **Execution profile:** clean rebuild in the existing `family-office` repository. Preserve the original implementation at the `v1-archive` tag before removing its files from the implementation branch. Build phases A through F on `codex/family-office`, with verified commits per unit and phase checkpoints in CI. The default branch retains the original implementation until the replacement is ready; no working hybrid or backward compatibility is required. Carry forward only verified behavior, rubrics, and migration knowledge from the archive. Preserve planning and reference documents. The product, repository, and package remain named `family-office`; `fo` remains the CLI. Version numbers are release metadata, not part of the product name. `session-settled: user-directed` (clean rebuild and unchanged product name; rejected alternative: incremental replacement with a working hybrid).
- **Tail ownership:** the implementing agent owns tests, CI, docs, connection setup, account discovery, profile configuration, and live diagnostics. Elliott supplies only credentials/browser consent when required, chooses the office git remote, and owns the v1 cutover decision. Pending live access does not block implementation against synthetic fixtures; live validation and reconciliation remain required before cutover. Do not hand Elliott manual JSON edits, account-ID lookups, or command checklists. `session-settled: user-directed` (2026-09-13: automate setup and verification; rejected alternative: a user-operated smoke-test checklist).

---

## Product Contract

### Summary

Build v2 as two artifacts: a public package (`fo` CLI, JSON schemas, playbooks, skills, adapters, CI) and a private office scaffolded by `fo init`. Every fact has one home: authored facts in `office/profile/`, derived facts in append-only JSONL under `office/data/` and `office/notebook/`, with SQLite as a rebuildable index. Skills spend the model only on judgment and always start from `fo brief` and `fo prior`. `AGENTS.md` is the canonical instruction file, `CLAUDE.md` imports it, and one physical skill copy serves both hosts.

### Problem Frame

v1 is 27 skills totalling 312 KB of prompt text with no code behind them beyond five standalone scripts. The audit of this checkout found:

- The same 3.1 KB tool-priority block is pasted into all 27 skills and is 27% of the corpus (35% with the sub-agent paragraph). Four drifting copies of the same table exist.
- 18 of 27 report-producing skills never read their own prior report, so a second run of `/equity-research NVDA` cannot say what changed. Recommendation `Invalidation:` lines are write-only. Journal entries carry `Status: OPEN` that nothing updates.
- `CLAUDE.md` mandates reading `memory/feedback_*.md` before any recommendation. No skill reads it and nothing creates it.
- The Codex mirror is a search-and-replace of the Claude files: `AGENTS.md` points at `.Codex/skills/`, the briefing skill fans out with `Codex -p --model Codex-sonnet-4-6`, and the `.agents/skills/sync` copy is a stale fork that hand-edits sync-owned files.
- Portfolio value is stored in six places; `scripts/consistency_check.py` exists to police that duplication, and its household scrub patterns are ignored by a variable-name bug.
- Every script hardcodes `python3.10`, which is not installed on the Mini. There is no `pyproject.toml`, lockfile, or test suite for the money math.
- `scripts/schwab/auth.py` claims to renew the refresh token but only rewrites a fake expiry. Schwab refresh tokens die seven days after the browser flow and `schwab-py` has no renewal path.
- Secrets live in `profile/api-keys.json` written at mode 0644 by three scripts that also use it as mutable state.

The real office today is an iCloud Obsidian vault (not a git repo). A Node webapp under launchd reads nine v1 profile files there; Elliott has said it does not need to be carried forward. The draft v2 plan assumes a gitignored SQLite store, which would hide household data from Codex cloud and from any second machine.

Full audit detail is in Appendix A.

### Requirements

**Truth and store**

- R1. Each fact has exactly one home. Authored facts live in `office/profile/`; derived facts live in machine-written files under `office/data/` and `office/notebook/`. No skill or script copies a live number into an authored file.
- R2. Derived data is canonical as git-tracked, append-only JSONL. SQLite is a rebuildable index that `fo reindex` regenerates from the JSONL and is gitignored; values computed from editable rules, such as transaction categories, live only in the index. Corrections to bad rows are appended `void` events, never rewrites.
- R3. Positions and balances are append-only snapshots keyed by `as_of` (RFC 3339 UTC) and a sortable `run_id`. Completeness is recorded per provider per run together with the account ids that provider returned. "Current" selects the newest complete snapshot for an account, then only the rows belonging to that snapshot; a missing symbol means the position is gone, and a covered account may have zero positions. A same-day re-sync with an identical complete snapshot records `unchanged_since` pointing to the prior complete snapshot instead of appending rows; readers resolve that reference while retaining the new coverage check time.
- R4. Personal data has no path inside the public repo. A CI lint fails if any path under an office layout is tracked.
- R5. Secrets (API keys, tokens, the SimpleFIN access URL, the Schwab account-hash map, and any office push credential) live only in `office/secrets/`, are never read from the environment, written atomically at mode 0600 in a 0700 directory, and are never printed or logged by `fo`, including under `--json` and `--dry-run`; account numbers appear only as last four digits. Non-secret settings live in the tracked `office/office.toml`.

**CLI**

- R6. Every deterministic operation (fetch, sync, arithmetic, categorisation, screening, bookkeeping, path and frontmatter generation) is a `fo` command with `--json` output and a non-zero exit on failure.
- R7. No `fo` command and no provider module can place an order or move money. The provider protocol has no write methods, enforced by an introspection test.
- R8. `fo doctor` validates environment, config, schemas, token expiry, sync age, store integrity, and skill-copy freshness, and exits non-zero on any failure.
- R9. Every read-side `fo` command works offline from the tracked JSONL when no provider credentials are present, reporting the oldest `as_of` among the accounts contributing to a figure and naming any provider whose newest complete run is older than the sync cadence; a market command with no key and no cached value exits non-zero with a `reason` field instead of guessing.

**Compounding**

- R10. `fo brief --level none|household|full [--for SUBJECT]` prints the household context at the requested level. Open decisions on the subject (with `--for`) and active corrections print at every level, including `none`; holdings, IPS, goals, and cash flow print only at `household` and `full`. The household brief targets 500 estimated tokens; mandatory corrections and subject decisions are never truncated to meet that target. When they require overflow, the command includes them in full and emits an overflow warning in both human and JSON output without treating overflow alone as a failure.
- R11. `fo prior SUBJECT` returns the latest prior report for a subject so a repeat run is a delta, and report frontmatter records `prior:`.
- R12. Every recommendation is journaled through `fo journal add` with a thesis and an invalidation condition; machine-checkable clauses use a small explicit grammar with typed metrics, and no skill edits `notebook/` directly.
- R13. `fo review` evaluates every open decision's machine clauses against current data, appends a machine record with the values used to `notebook/reviews.jsonl`, writes the dated markdown review from it, and reports calibration statistics (hit rate by conviction and source over closed decisions with a known outcome). The review lists breached decisions and open decisions older than `[notebook].verdict_days` (default 180) under a Due for verdict heading, and the review skill records each verdict with `fo journal close`.
- R14. Standing corrections are appended with `fo corrections add --scope global|skill:<name>|subject:<SYM>` (default global), retired with `fo corrections retire`, and `fo brief` surfaces every active global correction plus those matching the running skill and the `--for` subject, at every level.

**Skills**

- R15. The roster is 11 core skills (`research`, `diligence`, `scout`, `macro`, `cio`, `cfo`, `tax`, `plan`, `journal`, `briefing`, `review`), 9 playbooks (`lead-edge-eight`, `compounder`, `lynch`, `fisher`, `greenblatt`, `piotroski`, `powers`, `marks`, `all-weather`), 6 specialists (`options`, `technicals`, `risk`, `realestate`, `ventures`, `estate`), 2 utilities (`onboard`, `eli5`), and 5 sub-agents (`fundamentals-analyst`, `competitive-analyst`, `valuation-analyst`, `risk-analyst`, `sentiment-analyst`). Disposition of every v1 skill is in Appendix B.
- R16. Each `SKILL.md` is at most 3 KB with a description of at most 250 characters, follows the shared skeleton owned by `AGENTS.md`, declares its `fo` commands and invocation mode in `metadata`, and contains no provider names, API priorities, or numeric thresholds.
- R17. Fan-out happens only behind `--deep`, uses named worker agents available on both hosts, and never spawns a host CLI as a subprocess.
- R18. Every report is written at the path and with the frontmatter returned by `fo report path`, passes `fo skill verify` before the skill ends, and `fo reports index` keeps the index current.

**Dual host**

- R19. `AGENTS.md` is the canonical instruction file: the package ships the rules block, and the office `AGENTS.md` embeds it between markers (written by `fo skills sync`) followed by household notes, under 32 KiB combined and about 200 lines. `CLAUDE.md` contains `@AGENTS.md` plus Claude-only notes and nothing that duplicates `AGENTS.md`.
- R20. One physical skill copy per checkout serves both hosts: `.agents/skills/<name>/` is physical, `.claude/skills/<name>` is a relative symlink, and public-repo canonical files carry only Agent Skills spec fields.
- R21. Model routing is declared once per skill and sub-agent as a tier (`fast`, `balanced`, `strong`) and mapped to concrete models per host in one table in `office.toml`; `fo skills sync` renders host-specific fields from that table.
- R22. Sub-agents exist as `.claude/agents/*.md` and `.codex/agents/*.toml`, both generated from one canonical definition.
- R23. A host that loads only `AGENTS.md` (Codex cloud) can run any skill whose inputs are in the tracked store by printing its body with `fo skill <name>`, and can answer questions from the tracked JSONL; interactive skills and `--deep` are out of reach there (Appendix B).
- R24. `fo init` writes permission templates for both hosts (`.claude/settings.json`, `.codex/config.toml`) that allow `fo`, reads, and edits under `reports/`, deny reads of `secrets/` in Claude Code (Codex has no read deny, so `AGENTS.md` forbids it and nothing in the workflow needs it), and deny direct edits under `data/` and `notebook/`; edits under `profile/` are neither allowed nor denied, so they prompt, except during `onboard`, whose rendered `allowed-tools` pre-approves them for its turn.

**Operations and migration**

- R25. `fo schedule install` writes launchd jobs for sync, doctor, review, and index; no scheduled job invokes a model.
- R26. `fo doctor` warns from two days before Schwab refresh-token expiry and fails after it, with a macOS notification when scheduled.
- R27. `fo migrate-v1 PATH` imports a v1 office (profile JSON, journal entries, reports, memory feedback) into an empty v2 office without touching the source.

**Docs and release**

- R29. README states accurately what data leaves the machine and to whom; `SECURITY.md` lists every third party and what it receives.
- R30. CI runs ruff, pytest, gitleaks, the skill lints (size, forbidden content, parity), and the office-path lint on every push.

### Actors

- A1. Elliott, sole operator, on the Mac Mini (provider access, scheduler, git origin), a laptop, and occasionally Codex cloud, the ChatGPT web surface.
- A2. The advisor session: Claude Code or Codex running in the office directory with skills loaded.
- A3. The scheduler: launchd jobs on the Mini running `fo` only; no scheduled job invokes a model.

### Key Flows

- F1. Skill run
  - **Trigger:** A2 invokes a skill, for example the research skill on a ticker.
  - **Steps:** `fo start <skill> SUBJECT` (brief at the resolved level, prior, report path and frontmatter stub, per-command status); the `fo` compute commands the skill declares; reasoning, as a delta when a prior exists; write the report; `fo journal add` for any recommendation; `fo skill verify <report>`; one closing line inviting a correction, and when Elliott replies with one the skill records it with `fo corrections add`; on a checkout other than the Mini, `fo commit` then stages `reports/` and `notebook/`, commits, pulls with rebase, and pushes when a remote is set. On a non-zero `fo` exit the skill lists the command and reason under a Data gaps heading and never substitutes a searched number.
  - **Covered by:** R6, R9, R10, R11, R12, R14, R18.
- F2. Nightly sync and weekly review
  - **Trigger:** A3 at 02:00 daily and Sunday weekly.
  - **Steps:** `fo sync` takes the office lock, appends snapshots and transactions, and closes the run in `sync_log`; `fo reindex`; `fo reports index`; commit the permitted changes in `data/`, `notebook/`, and `reports/`, then pull with rebase and push when a remote is configured; `fo doctor` (notifies on failure); Sunday `fo review` appends to `notebook/reviews.jsonl` and writes the markdown review; the review skill is run by hand when judgment is needed. Git operations remain under the office lock, refuse unrelated dirty tracked files, and stop without pushing on a rebase conflict; merged data is reindexed before subsequent reads.
  - **Covered by:** R3, R8, R13, R25, R26.
- F3. Second machine or Codex cloud
  - **Trigger:** A1 opens the office repo somewhere without credentials.
  - **Steps:** `uv sync`; `fo doctor` reports offline mode; `fo skills sync` renders skills (local hosts only; `fo doctor` warns rather than fails until it runs); every read command answers from the tracked JSONL with `as_of`; Codex cloud follows `AGENTS.md` and `fo skill <name>`.
  - **Covered by:** R9, R20, R23.
- F4. v1 cutover
  - **Trigger:** A1 runs `fo migrate-v1` against the vault.
  - **Steps:** `fo migrate-v1 --dry-run` prints counts and ambiguities; the real run writes authored files, one initial snapshot dated from v1's own `data_as_of`, transactions, decisions, and reports into an empty office; `fo doctor` passes and every v1 balance reconciles per source (brokerage positions to `holdings.json`, each account and debt file to its `fo networth --by account` row); any v1 sync job still scheduled on the Mini is unloaded and the vault becomes read-only reference.
  - **Covered by:** R27.

### Acceptance Examples

- AE1. Covers R11. Given a fixture office with one prior research report on ACME, when the research skill runs again on ACME, then the new report's frontmatter names the prior path and the body has a "What changed" section.
- AE2. Covers R13. Given an open decision with the clause `price < 100` and a cached price of 95, when `fo review` runs, then the decision is flagged breached, the review record stores the value 95 with its `as_of` and source, and the markdown review lists it.
- AE3. Covers R21. Given `[models.claude] fast = "haiku"` in `office.toml`, when `fo skills sync` runs, then the office copy of the journal skill carries `model: haiku` and the public canonical file does not.
- AE4. Covers R9. Given no `secrets/` directory and tracked JSONL, when `fo brief --level household` runs, then it prints the household context, the oldest `as_of` among the contributing accounts, and any provider whose newest complete run is older than the sync cadence.
- AE5. Covers R3. Given a recorded Schwab response, when `fo sync --provider schwab` runs twice on the same local day, then the second run appends zero position rows and records `unchanged_since` for the first run, both runs appear in `fo sync status`, and `current_positions` returns one row per holding with no account flagged stale.
- AE6. Covers R26. Given a token file whose refresh expiry is 36 hours away, when `fo doctor` runs, then it exits 0 with a warning naming the hours remaining; at 0 hours it exits non-zero.
- AE7. Covers R7. Given the provider package, when the introspection test runs, then no class exposes a method matching `order|trade|transfer|withdraw|deposit|place|submit`.
- AE8. Covers R18. Given a dry-run research report, when `fo skill verify` runs on it, then it passes only if the path matches the convention, the frontmatter validates, `prior:` is set when a prior existed, every `decision_ids` entry resolves, and the closing line is present.
- AE9. Covers R14. Given an active correction that forbids a named recommendation on ACME, when the research skill runs on ACME in each host, then the report's recommendation section cites the correction and complies (phase E manual check).

### Scope Boundaries

- Any write action against a brokerage, bank, or card. Outside this product's identity, permanently.
- A web or mobile UI, including the existing v1 webapp: v2 neither migrates nor feeds it, and it can be retired at cutover.
- Multi-user or multi-household support.
- A medical advisor. `office/medical/` is a folder the `cfo` skill may read for receipts; nothing else in v2.0.

#### Deferred to Follow-Up Work

- Scheduled or Slack-delivered briefings. `/briefing` runs by hand in v2.0.
- Supabase or any cloud mirror of the store. Tracked JSONL covers the second-machine and cloud read cases.
- Gemini deep research, Apify, context7, and MCP-based data sources. The provider layer is direct HTTP; a host's native web search is the last-resort research tool.
- Plan and Plaid as a bank aggregator. SimpleFIN ships; Plaid is a later provider behind the same protocol.
- Publishing the public repo as an installable plugin for both hosts. Manifests are written in U3 but marketplace publication is a release task after v2.0.
- Transaction categorisation fallback with a cheap model for uncategorised rows. Rule-based categorisation ships; the model fallback is off and unbuilt.

### Decisions for Elliott

None block implementation. Each has a default the plan assumes; change the default before the affected phase.

- D1. Office git remote (before Phase B). Default: a local git repo on the Mini with no remote. Under that default the whole office, reports included, is readable only on the Mini (a step back from the iCloud vault every Apple device can open today), and R23, F3, KTD11, and the cloud parts of U14 are delivered only when a remote exists. Codex cloud and a laptop need a private GitHub remote, which puts positions, balances, and household notes on GitHub under a private repo; the push credential is then a write-enabled deploy key scoped to that repo, stored under `secrets/` and wired through the office's local `core.sshCommand`.
- D2. Office root location (before Phase B). Default: `~/office` on local disk, outside iCloud. Git and SQLite under iCloud sync corrupt; Obsidian can open `~/office` as a second vault for reading reports.
- D3. Concrete model names per tier (before Phase E). Defaults: Claude `haiku` / `sonnet` / `opus`; Codex `gpt-5.6-luna` / `gpt-5.6-sol` / `gpt-6-astra`. Astra is unavailable in Codex cloud, so cloud falls back to the balanced tier.
- D4. Keep `eli5` and `onboard`, which the draft roster does not list (before Phase E). Default: keep both, as R15 states; they are under 1 KB each and cost nothing when unused.

---
## Planning Contract

### Key Technical Decisions

- KTD1. **Two repos; the office is the root project and depends on the public package.** `office/pyproject.toml` pins `family-office` to a git tag; `uv sync` installs `fo`. Structural privacy: personal data never has a path in the public repo, which is what the v1 history rewrite was needed to fix. Rejected: one repo with gitignored data (v1's approach, which leaked). Rejected: sibling checkout with `PYTHONPATH`, because Codex cloud and a laptop clone need a self-contained office.
- KTD2. **Derived data is text-canonical; SQLite is an index.** `office/data/*.jsonl` and `office/notebook/decisions.jsonl` are the homes; `office/store.sqlite` is rebuilt by `fo reindex` and gitignored; price, fundamentals, filings, and macro caches live in a separate gitignored `office/cache/cache.sqlite` that `reindex` never touches, because a cache is refetchable only within provider rate limits, not rebuildable. The Mini is the single writer of `data/` (`fo sync` refuses to append `data/` on any other host); its nightly job commits `data/`, `notebook/`, and `reports/`, then pulls with rebase and pushes when a remote exists. Any checkout may append `notebook/` and write `reports/`, closing a skill run with `fo commit`, and `fo init` writes `.gitattributes` with `merge=union` for the append-only JSONL files and `notebook/corrections.md` so concurrent appends merge. Rationale: "one home per fact" holds (the index is a cache), git history becomes a free time series, every host that can `git pull` sees current data, and the drift lint disappears because nothing is copied. Rejected: gitignored SQLite as the home (draft plan), which hides data from cloud and a second machine. Rejected: committing the SQLite file, which diffs badly and needs WAL checkpoints before every commit.
- KTD3. **`AGENTS.md` is canonical; `CLAUDE.md` is `@AGENTS.md` plus Claude-only notes.** Claude Code reads `CLAUDE.md`, not `AGENTS.md`; Codex reads `AGENTS.md`, not `CLAUDE.md`; both vendors document exactly this pattern. Neither file is generated from the other: the package ships its rules block as data, `fo init` writes it between markers at the top of the office `AGENTS.md` above the household notes, `fo skills sync` refreshes only that block and stamps the package version, and the doctor check `agents.fresh` fails when it is stale. `AGENTS.md` stays under 32 KiB (Codex truncates) and about 200 lines. Rejected: generating `AGENTS.md` from `CLAUDE.md` (draft plan and v1), which produced the `.Codex/skills` garbage.
- KTD4. **One physical skill copy per checkout.** In the public repo, `skills/<name>/SKILL.md` is canonical and spec-pure (`name`, `description`, `metadata`, optional `allowed-tools`); `.claude/skills/*` and `.agents/skills/*` are relative symlinks for development. In the office, `fo skills sync` renders the installed package's skills into `.agents/skills/<name>/` (physical, Codex-discoverable), links `.claude/skills/<name>` to them, injects Claude fields (`model`, `effort`, `argument-hint`, `allowed-tools`, and `disable-model-invocation` from `metadata.invocation`) from `office.toml`, and writes `agents/openai.yaml` with `policy.allow_implicit_invocation` from the same key. Codex ignores unknown frontmatter keys, so the same file serves both. Plugin-style install is not the office distribution path because the copies need this injection; the manifests serve people who want only the skills. `fo skills sync` copies every file under `skills/<name>/` (lenses and other supporting files included) and renders only `SKILL.md`; `fo init` runs it as its last step. Rendered copies are gitignored in the office; `skills.fresh` warns when the checkout was never rendered (fresh clone, Codex cloud) and fails only when a stamp exists and is stale. Per-entry symlinks are proven on this machine for both hosts. Rejected: two hand-maintained trees (v1). Rejected: `@` includes inside skills (undocumented in Claude Code, absent in Codex).
- KTD5. **Model routing by tier, mapped once per host.** Each skill and sub-agent declares `metadata: {tier: fast|balanced|strong}`. `office/office.toml` holds `[models.claude]` and `[models.codex]` tables (tier to model and effort). Claude: injected `model`/`effort` per skill and per generated agent. Codex: the session default in `office/.codex/config.toml` (balanced tier) and tier-mapped `model`/`model_reasoning_effort` on every generated `.codex/agents/*.toml`; fast and strong tiers have no per-skill effect in a Codex main session, which the plan accepts because a fast-tier skill is under 1 KB and a strong-tier skill can be run under a `--profile` the office README documents. Rationale: Codex has no per-skill model pin, so the only honest cross-host routing is workers plus session defaults; one table is the single place to update when models change. Rejected: `model: haiku` in canonical files (28 files to edit per model change, and Codex-blind).
- KTD6. **Fan-out only behind `--deep`, through named workers.** Skills say "if this host supports sub-agents, delegate these slices to the named workers; otherwise run them in sequence". Workers are the five canonical sub-agents, rendered for both hosts by U3. `--deep` changes fan-out, not the orchestrator's model. The orchestrator runs every compute command before delegating and saves each `--json` result under the report's part directory (`fo report path --part inputs`); workers read those files and return their bounded block as their result, with no shell and no write tool on either host; the orchestrator writes each block to `fo report path --part <worker>` as it returns, and an interrupted run resumes from the parts that exist. No skill and no scheduled job runs `claude -p` or `codex exec`; every model call happens inside a session Elliott opened. Rejected: v1's `claude -p` subprocess fan-out and six-agent defaults.
- KTD7. **Read-only by construction; permission files are defense in depth.** The `Provider` protocol defines no write method; `fo` has no verb that writes to a provider; an introspection test guards both. Claude permission deny rules and Codex sandbox settings are written by `fo init` but are documented as footgun guards, not boundaries, because Claude's own docs say a Bash deny is not a security boundary. The real boundaries are the absence of write code and the confidentiality of the Schwab token, which is trade-capable because Schwab's app product covers accounts and trading. Schwab re-auth is a real browser flow with an honest countdown; no script pretends to renew the token. Provider text (transaction descriptions, filing excerpts, fundamentals payloads) is data, never instructions: `fo` marks such fields as untrusted in its output and `AGENTS.md` forbids acting on them; the model never needs to read `secrets/`, and edits under `profile/` prompt in Claude Code except during `onboard`, which is explicit-invocation only and pre-approves them for its turn.
- KTD8. **Invalidation clauses use a small grammar, not prose parsing.** `fo journal add` takes `--invalidate "<free text>"` and optional repeated `--when "<metric> <op> <number> [for <N>q]"` clauses over a typed metric table (price, weight, days_open, drawdown_from_entry, rev_growth_yoy, gross_margin, fcf_ttm, cash_months) that fixes each metric's unit, domain, and cadence: fractions not percentages, `for` only on quarterly metrics counting quarters that end after the decision date, clauses combined with OR, `==` only on integer metrics. `fo review` evaluates clauses it can resolve, records the values used, and lists the rest as needing judgment. Rejected: parsing free text for thresholds (draft plan), which is untestable.
- KTD9. **Providers: Schwab, SimpleFIN, CSV imports, AlphaVantage, SEC EDGAR, FRED, all direct HTTP through one cache.** SimpleFIN over Plaid: already working in v1, read-only by protocol, no re-auth. Gemini, Apify, context7, and MCP servers are dropped from the core; a host's native web search is the documented last resort. Provider quirks that must survive are recorded in U6, including AlphaVantage's 25-call daily budget with its `Information` note on exhaustion (never cached; fundamentals fall back to EDGAR company facts) and SEC XBRL Frames as the keyless cross-company screen behind `fo screen`.
- KTD10. **Migration reads the vault once.** `fo migrate-v1` maps v1 profile JSON to authored files, v1 `holdings.json` and account files to one initial snapshot, journal entries to decisions (thesis and invalidation copied as free text, no machine clauses), reports to `office/reports/` with generated frontmatter, and `memory/feedback_*.md` to `notebook/corrections.md`; the initial snapshot is dated from v1's `data_as_of`. Nothing writes back into the vault. Rejected: re-onboarding from empty.
- KTD11. **Codex cloud and ChatGPT are AGENTS.md-only hosts.** The office `AGENTS.md` carries the skill skeleton and the `fo skill <name>` printer so any host without skill loading can still follow a skill whose inputs are in the store. Read commands run offline from tracked JSONL; whatever `fo brief` prints reaches the host's model provider like any prompt, which the README privacy statement says. This works only with a GitHub remote for the office (D1) and a cloud setup script running `uv sync`; the cloud environment holds no secrets and no market cache, so market-dependent skills report data gaps there, and the clone it holds is the entire office checkout.
- KTD12. **Runtime: Python 3.12 via uv, Typer CLI, stdlib sqlite3, JSON Schema files validated with `jsonschema`.** The Mini has uv-managed 3.12 and no 3.10. Pydantic is not required; the implementer may adopt it for the store layer if it shortens the code.
- KTD13. **Playbooks are YAML with mechanical and judgment criteria; the scorer never writes a verdict.** Order: `lead-edge-eight`, `piotroski`, `greenblatt`, `compounder` (mechanical-heavy, fastest to test), then `lynch`, `fisher`, `powers`, `marks`, `all-weather`. Overrides in `office/playbooks/overrides/` merge over library defaults.
- KTD14. **Report paths and frontmatter are generated, not typed.** `fo report path --kind K --subject S` returns the canonical path and a frontmatter stub with `prior:` filled in. This removes the v1 failure where skills wrote into each other's directories.
- KTD15. **Office root discovery.** `fo` resolves the office from `--office`, then `$FO_OFFICE`, then an upward search from the working directory for the tracked `office.toml` beside `profile/`, so a clone without secrets still resolves. Sessions run inside the office directory so both hosts load its instruction files and skills.

### Departures from the draft plan

- Store: text-canonical JSONL plus SQLite index instead of gitignored SQLite as the home (KTD2). Consequence: `fo reindex` and `fo export` are new commands; the derived-tables list in the draft's section 5.2 becomes the JSONL file list in U5.
- Instruction files: `AGENTS.md` canonical and imported by `CLAUDE.md`, not generated the other way (KTD3). `scripts/gen_agents.py` is dropped.
- Shared skill behaviour: owned by `AGENTS.md` and by `fo` output (`fo start` prints the brief, prior, and frontmatter stub), not by `_shared/` files pulled in with `@` (KTD4).
- Model routing: tiers plus a per-host mapping table instead of `model: haiku|sonnet|opus` in frontmatter (KTD5). The draft's `[models] synthesis/research/extract` keys become `[models.claude]` and `[models.codex]` tier tables.
- Invalidation: explicit clause grammar instead of parsing prose (KTD8).
- Roster: adds `review` (named in the draft's scheduling table but missing from its roster), `onboard` (the draft has no path from an empty office to a filled IPS), and `eli5`; folds `debt` into `cfo`; sector skills become research lenses (Appendix B).
- Python 3.12, not 3.11; the draft's "three ELI5 HTML files" are one file, `family-office-system.html`, which moves under `docs/explainers/`.
- Migration is designed in Phase B (schema must accept v1 data) even though it executes at the end of Phase D.
- Skill copies in the office are rendered by `fo skills sync` rather than shipped as a second tracked tree.
- No scheduled model calls: the draft's optional headless briefing is dropped; `/briefing` is a one-call skill run by hand in either host.
- Settings split: the draft's single `config.toml` becomes a tracked `office.toml` (models, hosts, schedule, timezone) plus an ignored `secrets/` (keys, tokens, account-hash map), so a clone without secrets still finds the office and renders skills.
- Skeleton entry and exit are commands: `fo start` replaces the draft's three opening calls and `fo skill verify` checks the report before the skill ends.
- Decisions are an event log with two stored states (open, closed) rather than the draft's four mutable statuses, so `fo review` appends instead of rewriting lines.
- Screening stays deterministic: `fo screen` over SEC XBRL Frames replaces the draft's implicit reliance on web search or Gemini for candidate discovery.

### Draft plan open decisions

| Draft decision | Recommendation | Basis |
|---|---|---|
| 1. SQLite only vs Supabase mirror | SQLite index over tracked JSONL; no Supabase | KTD2 covers cloud and second-machine reads without a service |
| 2. Codex parity now or later | Now, but by design (canonical `AGENTS.md`, one skill copy, generated agents), not by generation from Claude files | Elliott uses both hosts; v1's generated mirror could not run |
| 3. Providers to keep | Direct HTTP only; drop Gemini, Apify, context7, MCP | Removes four secrets and three MCP dependencies from every skill; host web search remains |
| 4. SimpleFIN vs Plaid | SimpleFIN | Working in v1, read-only by protocol, no weekly re-auth |
| 5. Playbook order | lead-edge-eight, piotroski, greenblatt, compounder, then the judgment-heavy five | Mechanical criteria are testable against fixtures first |
| 6. Briefing delivery | Not scheduled; `/briefing` runs by hand in either host and writes a local report | No headless model runs in v2.0 |
| 7. Medical | Folder only | Out of v2.0 identity; bookkeeper may read receipts later |
| 8. Migration | Import v1 once; the vault becomes read-only reference | The vault holds years of history |
| 9. Model routing defaults | Tier tables with the D3 defaults | Names change; tiers do not |
| 10. Package layout | Office is the root project depending on the public package | Only layout that works for Codex cloud and a laptop |

### Assumptions

These are agent inferences made without confirmation; correct any before the affected phase.

- Codex usage is primarily local (the Codex CLI, the ChatGPT desktop app, the Codex IDE extension) on the Mini, with Codex cloud as a read-only secondary path.
- The office has no git remote until Elliott decides D1; the design must not depend on one, and the deliverables that need one (R23, F3, KTD11, the cloud parts of U14) are conditional on it.
- The v1 skills not in the draft roster (`debt`, `medical`, `sync`, `weekly-review`, `screener`, `alts-scout`, `sector-*`, `equity-research`, `mgmt-diligence`) are folded or renamed as Appendix B states; none survives as a separate skill.
- Elliott is the sole operator; no shared-machine or multi-user permission model is needed.
- `schwab-py` remains the Schwab client library; if its alpha API changes, U6 wraps a plain `httpx` client instead.
- Reports and notebook files are committed to the office repo; imports, medical, caches, secrets, the SQLite index, and rendered skill copies are not.
- The v1 vault stays untouched by v2 except as a migration source.
- Codex applies a trusted project's `.codex/config.toml` over the global config, so the office's `workspace-write` sandbox overrides Elliott's global `danger-full-access` setting; if a Codex release changes that layering, the office README note in U3 must change.

---
### High-Level Technical Design

**Data flow and ownership.** Account providers are read only by `fo sync`; market providers are fetched lazily through the cache; everything else reads the store, and only `fo` writes the notebook.

```mermaid
flowchart TB
  subgraph providers [Providers, read-only]
    SCHWAB[Schwab]
    SFIN[SimpleFIN]
    CSV[imports/ CSV]
    MKT[AlphaVantage, EDGAR, FRED]
  end
  SYNC[fo sync] --> JSONL[(office/data/*.jsonl<br/>append-only, tracked)]
  SCHWAB --> SYNC
  SFIN --> SYNC
  CSV --> SYNC
  MKT --> CACHE[(cache/cache.sqlite<br/>ignored, lazy fetch, never reindexed)]
  JSONL --> REINDEX[fo reindex] --> IDX[(store.sqlite index<br/>ignored, rebuildable)]
  PROFILE[(office/profile/<br/>authored, tracked)] --> COMPUTE
  IDX --> COMPUTE[fo networth, allocation, goals, lots, score ...]
  CACHE --> COMPUTE
  COMPUTE --> BRIEF[fo brief / fo prior]
  BRIEF --> SKILL[skill run in Claude Code or Codex]
  SKILL --> REPORTS[(office/reports/<br/>frontmatter, tracked)]
  SKILL --> JADD[fo journal add] --> DEC[(notebook/decisions.jsonl)]
  DEC --> REVIEW[fo review] --> REVIEWS[(notebook/reviews/)]
  REVIEW --> DEC
  REVIEW --> RVJ[(notebook/reviews.jsonl)]
  SKILL --> CADD[fo corrections add] --> CORR[(notebook/corrections.md)]
  CORR --> BRIEF
  REPORTS --> INDEX[fo reports index] --> BRIEF
  JSONL --> COMMIT[nightly commit, pull, push on the Mini]
  REPORTS --> FCOMMIT[fo commit on other checkouts]
  DEC --> FCOMMIT
```

**Distribution to both hosts.** One canonical source per artifact; rendering is a `fo` command, never a hand-copy.

```mermaid
flowchart TB
  subgraph public [public repo family-office]
    AG[AGENTS.md rules block, shipped as package data]
    CL[CLAUDE.md = @AGENTS.md + Claude notes]
    SK[skills/&lt;name&gt;/SKILL.md<br/>spec-pure + metadata.tier]
    AGT[agents/&lt;name&gt;.md canonical sub-agents]
    PB[playbooks/library/*.yaml]
  end
  subgraph office [office checkout]
    CFG[office.toml<br/>models.claude / models.codex tables]
    SYNCS[fo skills sync]
    PHYS[.agents/skills/&lt;name&gt;/ physical, rendered]
    LNK[.claude/skills/&lt;name&gt; relative symlink]
    CAG[.claude/agents/*.md<br/>model per tier]
    XAG[.codex/agents/*.toml<br/>model + reasoning effort per tier]
    OAG[office AGENTS.md = rules block + household notes<br/>CLAUDE.md = @AGENTS.md]
    PERM[.claude/settings.json and .codex/config.toml<br/>written by fo init]
  end
  SK --> SYNCS
  AG --> SYNCS
  AGT --> SYNCS
  CFG --> SYNCS
  SYNCS --> PHYS --> LNK
  SYNCS --> CAG
  SYNCS --> XAG
  SYNCS --> OAG
  CLAUDE[Claude Code] --> LNK
  CLAUDE --> CAG
  CLAUDE --> OAG
  CODEX[Codex CLI / app] --> PHYS
  CODEX --> XAG
  CODEX --> OAG
  CLOUD[Codex cloud, ChatGPT] --> OAG
  CLOUD --> PRINT[fo skill &lt;name&gt; prints the body]
```

**Skill run skeleton.** Every skill follows this sequence; the skill file adds only its judgment rubric and output sections.

```mermaid
sequenceDiagram
  participant U as Elliott
  participant S as Skill (either host)
  participant F as fo
  U->>S: /research NVDA --lens semis
  S->>F: fo start research NVDA
  F-->>S: brief (notebook context at level none), prior, report path + frontmatter stub
  S->>F: fo fundamentals NVDA / fo filings NVDA / fo quote NVDA
  F-->>S: JSON
  S->>S: reason; delta if prior exists
  S->>U: writes report at the returned path
  S->>F: fo journal add --subject NVDA ... --when "price < 95"
  F-->>S: decision id
  S->>F: fo skill verify <report>
  F-->>S: pass, or the failing checks
  S->>U: one closing line asking for a correction
  U-->>S: reply with a correction (optional)
  S->>F: fo corrections add "..."
  S->>F: fo commit (on a checkout other than the Mini)
```

**Decision lifecycle.** `notebook/decisions.jsonl` is an event log (`created`, `reviewed`, `closed`, `reopened`); stored status is only open or closed, and breached or needs-judgment are flags on the latest review event. Only `fo journal` and `fo review` append.

```mermaid
stateDiagram-v2
  [*] --> open: fo journal add (created event)
  open --> open: fo review appends a reviewed event (flags breached or needs_judgment, values used)
  open --> closed: fo journal close --outcome hit|miss|neutral|unknown
  closed --> open: fo journal reopen
  closed --> [*]
```

### Output Structure

Public repo after Phase F (legacy implementation trees are removed in U1 after archiving; the historical explainer moves under `docs/`):

```text
family-office/
  pyproject.toml            uv, python >= 3.12, console script fo
  AGENTS.md                 canonical instructions (< 32 KiB)
  CLAUDE.md                 @AGENTS.md + Claude-only notes
  README.md  SECURITY.md  LICENSE  CHANGELOG.md
  .claude-plugin/plugin.json   .codex-plugin/plugin.json   .agents/plugins/marketplace.json
  .claude/skills/<name> -> ../../skills/<name>     (dev symlinks)
  .agents/skills/<name> -> ../../skills/<name>     (dev symlinks)
  skills/<name>/SKILL.md    28 canonical skills, spec-pure frontmatter
  agents/<name>.md          5 canonical sub-agents with tier
  src/fo/
    cli.py  config.py  office.py  doctor.py  init.py  skills.py  schedule.py  lock.py
    data/AGENTS.rules.md      rules block that fo init and fo skills sync write into an office
    store/   db.py  index.py  jsonl.py  authored.py  schemas/*.json
    providers/  base.py  cache.py  schwab.py  simplefin.py  imports.py  alphavantage.py  edgar.py  fred.py
    sync/    compute/    brief.py    start.py    notebook/    reports.py    playbooks/  schema.py  scorer.py  library/*.yaml
    migrate_v1.py
  scripts/lint_skills.py  scripts/lint_office_paths.py
  tests/  fixtures/office/  fixtures/office-stress/  fixtures/providers/  fixtures/skills/  fixtures/agents/  fixtures/v1-office/  test_*.py  skills/dryrun_*.py
  docs/plans/  docs/explainers/family-office-system.html  docs/skill-authoring.md  docs/office-layout.md
  .github/workflows/ci.yml
```

Office created by `fo init` (tracked unless marked):

```text
office/
  pyproject.toml  uv.lock  .gitattributes   depends on family-office @ tag; merge=union for append-only logs
  AGENTS.md  CLAUDE.md             household notes; import the package rules
  office.toml                      tracked: [office] timezone, [models.*], [hosts], [schedule]
  secrets/                         ignored, 0700: keys.toml, schwab-token.json, account-hash map, 0600 each
  profile/  household.md  ips.json  goals.json  tax.json  accounts.json  categories.yaml  universes.yaml
  data/  accounts.jsonl  positions.jsonl  balances.jsonl  transactions.jsonl  sync_log.jsonl  voids.jsonl
  notebook/  decisions.jsonl  reviews.jsonl  corrections.md  reviews/YYYY-MM-DD.md
  reports/<kind>/<subject>/YYYY-MM-DD-<slug>.md
  playbooks/overrides/*.yaml
  imports/  medical/               ignored
  store.sqlite  .fo.lock           ignored, rebuilt by fo reindex
  cache/cache.sqlite               ignored, refetchable, untouched by reindex
  .agents/skills/<name>/           ignored, rendered by fo skills sync
  .claude/skills/<name> -> ../../.agents/skills/<name>   ignored, rendered
  .claude/agents/*.md  .codex/agents/*.toml              ignored, rendered
  .claude/settings.json  .codex/config.toml               tracked, written by fo init
  launchd/*.plist                  written by fo schedule install
  hooks/pre-commit                 tracked, activated by fo init via core.hooksPath
```

---
## Implementation Units

Phases: A foundation (U1-U3), B store and sync (U4-U6), C compute and reports (U7, U10), D notebook, brief, and migration (U9, U8, U15), E skills (U11-U13), F operations and release (U14, U16). These are verification checkpoints on the clean implementation branch; units are listed in dependency order within each phase. The archive supplies historical references after legacy paths are removed in U1.

### Unit Index

| U-ID | Title | Key files | Depends on |
|---|---|---|---|
| U1 | Package scaffold, doctor framework, fixture office, CI | `pyproject.toml`, `src/fo/cli.py`, `src/fo/doctor.py`, `tests/fixtures/office/`, `.github/workflows/ci.yml` | none |
| U2 | Canonical instruction files and skill authoring standard | `AGENTS.md`, `CLAUDE.md`, `docs/skill-authoring.md`, `scripts/lint_skills.py` | U1 |
| U3 | Skill, agent, and rules-block distribution (`fo skills sync`, adapters, manifests) | `src/fo/skills.py`, `src/fo/data/AGENTS.rules.md`, `tests/fixtures/skills/`, `tests/fixtures/agents/`, `.claude-plugin/`, `.codex-plugin/` | U1, U2 |
| U4 | Authored profile, `office.toml`, secrets, `fo init` | `src/fo/store/authored.py`, `src/fo/store/schemas/`, `src/fo/init.py`, `src/fo/config.py` | U1 |
| U5 | Derived store: JSONL tables, SQLite index, `fo reindex` | `src/fo/store/jsonl.py`, `src/fo/store/db.py`, `src/fo/store/index.py`, `src/fo/lock.py` | U4 |
| U6 | Providers, cache, `fo sync`, `fo auth` | `src/fo/providers/`, `src/fo/sync/`, `tests/fixtures/providers/` | U5 |
| U7 | Compute commands | `src/fo/compute/`, `tests/test_compute_*.py` | U5, U6 |
| U8 | `fo brief` and `fo start` | `src/fo/brief.py`, `src/fo/start.py` | U7, U9, U10 |
| U9 | Journal, invalidation grammar, `fo review`, corrections | `src/fo/notebook/` | U7 |
| U10 | Reports index, `fo report path`, `fo prior`, `fo skill verify` | `src/fo/reports.py` | U5 |
| U11 | Core and utility skills with dry-run harness | `skills/<core>/SKILL.md`, `tests/skills/` | U3, U8, U9, U10 |
| U12 | Playbooks: schema, scorer, library, skills | `src/fo/playbooks/`, `skills/<playbook>/SKILL.md` | U7, U11 |
| U13 | Specialists and `--deep` sub-agents | `skills/<specialist>/SKILL.md`, `agents/*.md` | U3, U11 |
| U14 | Scheduling, notifications, cloud setup | `src/fo/schedule.py`, `docs/office-layout.md` | U6, U9, U11 |
| U15 | v1 migration | `src/fo/migrate_v1.py`, `tests/fixtures/v1-office/` | U5, U9, U10 |
| U16 | Docs, security statement, release | `README.md`, `SECURITY.md`, `docs/explainers/`, `CHANGELOG.md` | all |

### U1. Package scaffold, doctor framework, fixture office, CI

- **Goal:** a runnable `fo` with `--version`, `init`, `doctor`, a doctor check registry every later unit adds to, a complete fake office, and green CI.
- **Requirements:** R4, R8, R30.
- **Dependencies:** none.
- **Files:** `pyproject.toml`, `src/fo/__init__.py`, `src/fo/cli.py`, `src/fo/doctor.py`, `src/fo/office.py`, `tests/fixtures/office/` (every authored file, a small `data/` set, two reports, three decisions), `tests/fixtures/office-stress/` (60 symbols, 30 lots, 10 open decisions, for budget gates), `tests/conftest.py`, `tests/test_cli.py`, `tests/test_doctor.py`, `scripts/lint_office_paths.py`, `.github/workflows/ci.yml`, `.gitignore`.
- **Approach:**
  1. uv project, `requires-python >= 3.12`, Typer, `--json` as a global option that switches every command's output.
  2. Doctor is a registry of named checks returning pass, warn, or fail with a one-line reason; units register checks in their own modules (KTD7, R8).
  3. Office discovery per KTD15; `fo init PATH` writes the office layout from templates (content filled in U4).
  4. CI runs ruff, pytest, gitleaks, `scripts/lint_office_paths.py`, and the skill lints from U2 once present. The office-path lint rejects repo-root office paths (`office.toml`, `data/`, `notebook/`, `secrets/`, and `profile/*.json`) and real office roots identified by an `office.toml` outside explicitly designated synthetic fixtures. Package assets under `src/fo/` and synthetic layouts under `tests/fixtures/` are permitted; fixture exemptions never exempt secrets scanning. The v1 `profile/` templates are deleted in U2.
  5. After verifying the published `v1-archive` tag, remove tracked legacy implementation trees from this feature branch, preserving the license, planning documents, and historical explainer under `docs/`. Do not touch ignored private files or the real office. U2 and U11 create new instruction and skill files; later references to deleting legacy files are satisfied by this clean-start removal.
- **Execution note:** packaging and CI; prefer install-and-run smoke verification over unit coverage.
- **Patterns to follow:** none in repo; mirror the fixture-office idea from the draft plan section 11.
- **Test scenarios:**
  - `fo --version` prints the package version and exits 0.
  - `fo init /tmp/x` then `fo doctor --office /tmp/x` exits 0 on a fresh scaffold with warnings for missing keys (skills render inside `init`, so `skills.fresh` passes).
  - A tracked file named `profile/ips.json` at repo root makes `lint_office_paths.py` exit non-zero. The planned synthetic fixture offices and `src/fo/data/AGENTS.rules.md` pass, while a real office layout nested elsewhere in the repo fails.
  - `fo doctor --json` emits one object per check with `status` in {pass, warn, fail}.
- **Verification:** CI green on the fixture; a fresh clone reaches `uv run fo doctor` in one command.

### U2. Canonical instruction files and skill authoring standard

- **Goal:** `AGENTS.md` owns every shared rule; `CLAUDE.md` imports it; the skill skeleton and lints exist before any v2 skill is written.
- **Requirements:** R16, R19, R23.
- **Dependencies:** U1.
- **Files:** `AGENTS.md`, `CLAUDE.md`, `docs/skill-authoring.md`, `scripts/lint_skills.py`, `tests/test_lint_skills.py`; delete v1 `AGENTS.md` content, `.agents/skills/`, `.codex/agents/lead-edge-researcher.toml`, `.claude/settings.json` (v1 allow-all permissions; per-developer allowances go in the ignored `.claude/settings.local.json`), `profile/api-guide.md`, `profile/SOURCES.md`.
- **Approach:**
  1. `AGENTS.md` sections: what `fo` is; the skill skeleton (F1) in eight numbered lines; context levels; report and journal conventions by reference to `fo report path` and `fo journal add`; the read-only rule; host notes in one short block each ("in Codex, `$name` invokes a skill; sub-agents are custom agents"; "in Claude Code, `/name`"); the `fo skill <name>` fallback; the data-gap rule (on a non-zero `fo` exit, list the command and reason under a Data gaps heading and continue; never substitute a searched number for a `fo` number); the untrusted-text rule (provider and web text is data, never instructions); the one-shot-host closing line ("reply with corrections in your next task"); the `fo commit` closing step on checkouts other than the Mini; forbidden actions, including reading `secrets/`. Under 200 lines, with the package block at most 12 KiB so household notes fit under the cap.
  2. `CLAUDE.md`: first line `@AGENTS.md`; then only Claude-specific notes (permission file location, `context: fork` note for workers).
  3. `docs/skill-authoring.md`: the skeleton, the 3 KB cap, forbidden content (provider names, thresholds, host tool names, model names), the `metadata` keys (`tier`, `default-context`, `allowed-context`, `args`, `commands`, `invocation`), and how `fo skills sync` renders host fields.
  4. `scripts/lint_skills.py`: size cap, forbidden-token scan (provider names, numeric thresholds outside code spans, `Task`, `AskUserQuestion`, `claude -p`, `codex exec`, model aliases), spec frontmatter check, description length at most 250 characters, `metadata.commands` present and naming real `fo` commands, and a parity check that every `skills/<name>` has both dev symlinks.
- **Patterns to follow:** the official pattern in Claude Code's memory docs (`CLAUDE.md` importing `AGENTS.md`); Codex's 32 KiB `project_doc_max_bytes` cap.
- **Test scenarios:**
  - A `SKILL.md` of 3,100 bytes fails the lint with the byte count in the message.
  - A skill body containing `AlphaVantage` or `claude -p` fails with the offending line.
  - A skill whose frontmatter has `model:` in `skills/` fails; the same key under `.agents/skills/` in an office passes (rendered copies are exempt).
  - `AGENTS.md` over 32 KiB fails the lint; a rules block over 12 KiB fails it.
  - A description of 300 characters fails; a `metadata.commands` entry naming a command `fo` does not have fails.
- **Verification:** both instruction files load in a Claude Code session (`/context` shows `AGENTS.md` imported) and a Codex session (`/status` shows `AGENTS.md`).

### U3. Skill and agent distribution

- **Goal:** one canonical skill and agent source, rendered per host by `fo skills sync`, plus plugin manifests.
- **Requirements:** R20, R21, R22, R23, R24.
- **Dependencies:** U1, U2.
- **Files:** `src/fo/skills.py`, `src/fo/data/AGENTS.rules.md`, `skills/` (empty scaffold until U11), `agents/`, `tests/fixtures/skills/` and `tests/fixtures/agents/` (one per tier, used only by tests), `.claude/skills/` and `.agents/skills/` dev symlinks, `.claude-plugin/plugin.json`, `.codex-plugin/plugin.json`, `.agents/plugins/marketplace.json`, `src/fo/templates/office/.claude/settings.json`, `src/fo/templates/office/.codex/config.toml`, `tests/test_skills_sync.py`.
- **Approach:**
  1. Skills ship as package data. `fo skills sync` reads `[models.claude]` and `[models.codex]` from the office config, copies every file under `skills/<name>/` into `office/.agents/skills/<name>/` and renders `SKILL.md` with Claude fields injected (`model` and `effort` from the tier, `argument-hint` from `metadata.args`, `disable-model-invocation: true` when `metadata.invocation` is `explicit`, `allowed-tools` limited to `fo`, reads, and edits under `reports/`, plus `profile/` for `onboard` only), writes `agents/openai.yaml` with `interface.display_name`, `short_description`, and `policy.allow_implicit_invocation` from the same key, and creates the relative symlink under `.claude/skills/`. Sync refuses to run when `.claude/skills/<name>` is a real directory (a v1 leftover) and fails when a rendered skill references an agent absent from `agents/`.
  2. Sub-agents render to `.claude/agents/<name>.md` (`model`, `tools` limited to `Read`, `Grep`, and `Glob`; no shell and no write tool) and `.codex/agents/<name>.toml` (`name`, `description`, `model`, `model_reasoning_effort`, `sandbox_mode = "read-only"`, `developer_instructions` from the canonical body).
  3. A version stamp file records the package version and config hash; the doctor check `skills.fresh` fails when either changed. The rules block ships as `src/fo/data/AGENTS.rules.md`: `fo init` creates the office `AGENTS.md` as that block between markers followed by a household section, `fo skills sync` refreshes only the block, and `agents.fresh` fails when it is stale. A `skills.unique` check fails if a skill name resolves to two different directories across the two host trees.
  4. `fo skill <name>` prints a skill body to stdout (R23) and exits non-zero listing valid names for an unknown one.
  5. Office permission templates: Claude allows `Bash(uv run fo *)`, `Bash(fo *)`, `Read`, `Edit(reports/**)`; denies `Read(secrets/**)`, `Edit(data/**)`, `Edit(notebook/**)`, `Bash(python *)`, `Bash(python3 *)`, `Bash(uv run python *)`, `Bash(curl *)`, `Bash(pip *)`, `Bash(git push *)`; `profile/` is on neither list because a Claude deny cannot be overridden by a skill's `allowed-tools`, so edits there prompt, except during `onboard`, whose rendered `allowed-tools` pre-approves `Edit(profile/**)` for its turn. Codex: `sandbox_mode = "workspace-write"`, `approval_policy = "on-request"`, `model` and `model_reasoning_effort` from the balanced tier; the office README states that Codex applies these only when the office is a trusted project and that they then override the global config (Elliott's global config is `danger-full-access` with approvals off), and that Codex has no read deny, so `AGENTS.md` forbids reading `secrets/` and nothing in the workflow needs it.
  6. Plugin manifests point both hosts at `./skills/` and `./agents/` for optional plugin-style installs.
- **Patterns to follow:** per-entry symlinks as used by `~/.agents/skills/` on the Mini; Codex agent TOML fields as documented in the Codex sub-agents reference; the `agents/openai.yaml` sidecar shape.
- **Test scenarios:**
  - With `fast = "haiku"` in `office.toml`, the rendered fast-tier fixture skill has `model: haiku`; the canonical fixture file has no `model` key.
  - Rendering with `[models.codex] strong = "gpt-6-astra"` gives the strong-tier fixture agent that model and effort in its TOML; the balanced fixture agent gets the balanced model.
  - A fixture skill with `invocation: explicit` renders `disable-model-invocation: true` for Claude and `allow_implicit_invocation: false` in `openai.yaml`; an implicit one renders neither.
  - After `fo init` the office `AGENTS.md` contains the rules block once with the household section intact; after a package version bump `agents.fresh` fails until `fo skills sync` runs.
  - Sync refuses when `.claude/skills/x` is a real directory and fails when a fixture skill references an agent absent from `agents/`.
  - A rendered Codex worker TOML has `sandbox_mode = "read-only"`, and no rendered `.claude/agents/*.md` lists `Bash` or an edit tool; a worker run in read-only mode on the fixture (`-wal` and `-shm` files removed first) answers from the prebuilt index or JSONL without writing.
  - A fixture skill's supporting file under its directory is present in the rendered tree and covered by `skills.fresh`.
  - On a checkout with no sync stamp, `skills.fresh` reports warn; after `fo init` it passes.
  - Changing config after a sync makes `fo doctor` report `skills.fresh: fail` until `fo skills sync` runs.
  - Every rendered symlink resolves to an existing directory.
  - `fo skill research` prints the exact canonical body; `fo skill nope` exits non-zero and lists valid names.
  - Rendered `SKILL.md` passes Codex's parser rules: name under 64 chars, description present, no unquoted colon problems.
- **Verification:** in an office, both hosts list the same skill names; a Claude session shows the injected model in the skill's frontmatter and a Codex session shows the skill under `/skills`.

### U4. Authored profile, `office.toml`, secrets, `fo init`

- **Goal:** every authored file has a JSON Schema, a loader with clear errors, an example, and a doctor check; secrets are handled correctly from day one.
- **Requirements:** R1, R5, R8.
- **Dependencies:** U1.
- **Files:** `src/fo/store/authored.py`, `src/fo/store/schemas/{household,ips,goals,tax,accounts,categories}.schema.json`, `src/fo/config.py`, `src/fo/init.py`, `src/fo/templates/office/**` (including `office.toml` and `hooks/pre-commit`), `tests/test_authored.py`, `tests/test_config.py`.
- **Approach:**
  1. Authored files per the Output Structure. `household.md` is prose plus one fenced JSON block the loader parses. `accounts.json` is the single account registry (id, institution, type, tax type, owner, scope, provider of record, `provider_ref`, last4) replacing v1's seven tables; `provider_ref` is a non-secret identifier (SimpleFIN account id, CSV account label) and is empty for Schwab accounts, whose hash is looked up by office account id in `secrets/keys.toml`. `profile/universes.yaml` holds named ticker universes for `fo screen --universe`.
  2. Tracked `office.toml` holds `[office]` (timezone), provider toggles, `[models.*]`, `[hosts]`, `[schedule]`; ignored `secrets/keys.toml` holds API keys, the SimpleFIN access URL, and the Schwab account-hash map; both are read once into one config object whose `--json` output masks every value loaded from `secrets/`; `fo` never reads provider keys from the environment.
  3. All secret writers use write-to-temp, `chmod 0600`, atomic rename, inside a 0700 `secrets/`. The Schwab token lives in `office/secrets/schwab-token.json`; setup tokens are read from a prompt or stdin, never a flag, so they stay out of shell history and the process list; `fo` never logs a secret value and prints account numbers as last four only.
  4. `fo init` writes examples, `.gitignore`, `.gitattributes` (`merge=union` for `*.jsonl` and `notebook/corrections.md`), both permission templates, and a pre-commit hook that blocks staged paths under `secrets/`, `cache/`, `imports/`, `medical/`, and the rendered skill trees and runs gitleaks when installed; it runs `git init` when the target is not inside a repository, sets `core.hooksPath` to the office `hooks/` directory, makes the initial commit, and finishes with `fo skills sync`.
  5. Doctor checks: `secrets.perms` (0600 files, 0700 directory), `secrets.ignored` (via `git check-ignore`), `secrets.ignored` fails with a not-a-repository reason outside git, and a warning when the office has a git remote that `[hosts].remote` does not name; before the first push to a new remote, `fo doctor` runs gitleaks over the office history, not only the tree.
- **Patterns to follow:** v1 `profile/SOURCES.md` two-tier idea (authored vs derived) carried into the schemas; v1 `scripts/expenses/categories.example.json` shape for `categories.yaml`.
- **Test scenarios:**
  - An `ips.json` with a band whose min exceeds max fails validation with the JSON pointer of the field.
  - `accounts.json` with duplicate ids fails.
  - `fo config --json` prints `"app_secret": "***"` for a configured Schwab app.
  - Writing a token file leaves mode 0600 and no temp file behind after a simulated crash between write and rename.
  - `fo init` twice is a no-op on existing files and reports what it skipped.
  - Office discovery succeeds from a subdirectory of a clone with no `secrets/`, and `fo doctor` reports offline mode.
  - A commit in a fixture office with a staged `secrets/keys.toml`, `imports/x.csv`, or `medical/x.pdf` is blocked by the hook.
  - No value in `accounts.json` or `accounts.jsonl` equals a Schwab account hash from the fixture secrets.
- **Verification:** `fo doctor` on the fixture passes every schema check and fails when a fixture file is corrupted in a test.

### U5. Derived store: JSONL tables, SQLite index, `fo reindex`

- **Goal:** the canonical derived files and their index.
- **Requirements:** R1, R2, R3, R9.
- **Dependencies:** U4.
- **Files:** `src/fo/store/jsonl.py`, `src/fo/store/db.py`, `src/fo/store/index.py`, `src/fo/lock.py`, `tests/test_store.py`.
- **Approach:**
  1. JSONL files: `accounts.jsonl` (provider-discovered accounts: provider, provider account id, matched office account id, first and last seen; not a copy of the registry), `positions.jsonl` (`as_of`, `run_id`, `account_id`, `symbol`, `qty`, `price`, `value`, `cost_basis`, nullable `lot_id` and `acquired_at`, `source`; lot fields are populated only from explicit provider/import lot evidence, never inferred from an average basis or a snapshot date), `balances.jsonl`, `transactions.jsonl` (stable transaction id, provider id and prior-id aliases, revision, account, `transacted_at`, posted date, amount, description, payee, memo, pending, symbol, source, raw, fingerprint; `raw` is an allowlisted projection of non-secret provider fields, not the original payload. Provider adapters omit credential URLs, account hashes, and full account numbers before persistence, including for unmapped accounts; the tracked registry stores only last4 and cannot supply full numbers for scrubbing. The writer and no-leak tests reject forbidden fields and sentinel values in nested content. A pending-to-posted transition or matched re-post appends a revision of the same stable transaction id, retaining changed provider ids as aliases; views keep the newest revision per (account, stable transaction id)), `sync_log.jsonl` (one line per provider per run with status, row counts, the account ids that provider returned, and `unchanged_since` when a same-day re-sync found no change), `voids.jsonl` (run or row key, reason, date). `as_of` is RFC 3339 UTC taken from the provider when it gives one, else the run start; `run_id` is a sortable ULID; `[office].timezone` in `office.toml` defines the local day. Categories are not stored here (they are index-only, U7). Files are append-only; a generic writer enforces a schema per file, and every writing command holds the exclusive `office/.fo.lock`.
  2. SQLite index built from the JSONL by `fo reindex`; tables mirror the files plus `decisions` and `reviews` (from the notebook event logs), `reports_index` (walked from `reports/`, rows removed for missing files), and `categories` (computed from `categories.yaml`, with the rules hash stored). Market caches live in `office/cache/cache.sqlite` (U6) and are never touched by reindex. The index carries a `schema_version` and rebuilds fully on mismatch, so there are no migrations. Rows from a provider run without a `complete` line and rows named in `voids.jsonl` are excluded. WAL mode. `fo` auto-reindexes when the index is missing, stale against any JSONL or notebook file or `reports/`, or on version mismatch, and in read-only mode (an unwritable office tree or `--read-only`) uses the index with `mode=ro` only when its source fingerprint and schema version are current, otherwise projects the tracked sources in memory without writing; it also falls back on any open error, and serves cached market values past TTL without writing.
  3. Views: `current_positions` and `current_balances` select the newest complete snapshot per account ordered by (`as_of`, `run_id`), resolve any `unchanged_since` reference to its non-void complete source, and read only that snapshot's positions and balances. Never carry forward a symbol absent from a newer snapshot. An account absent from its provider's newest completed coverage list retains its last known snapshot with a stale flag in `fo doctor` and `fo brief`. A voided or incomplete snapshot cannot be an unchanged reference target.
- **Patterns to follow:** the draft plan's table list in section 5.2 for column names; v1 `holdings.json` shape for the export.
- **Test scenarios:**
  - With no `secrets/` and the fixture JSONL, `fo reindex` then `fo positions --json` returns the latest snapshot with its `as_of`.
  - Appending a second snapshot changes `current_positions` and leaves the first snapshot intact. Starting with ACME and BETA, a later snapshot containing only BETA removes ACME from current totals; a complete empty snapshot removes both. A change to BETA still retains ACME when both are in the newer snapshot. An unchanged snapshot resolves its source without making either position disappear.
  - Two runs on the same local day yield one current row per holding with no stale flag; a provider run without a `complete` line is invisible to the views while the other provider's rows from the same run are current; a voided run makes `networth` revert to the prior run.
  - A transaction that re-posts appends a second row and the index shows only the newest revision per stable transaction id, including when the provider id changes; identical legitimate purchases with ambiguous fingerprints are not collapsed. A raw payload containing a full account number, account hash, or credential URL is rejected even when the account is absent from the registry.
  - Read-only mode on a tree with `-wal` and `-shm` removed answers every read command without creating files. With an existing index, append a newer complete snapshot or edit category rules, then verify read-only results match a fresh reindex rather than the stale index.
  - An account missing from a provider's latest complete run is flagged stale by `fo doctor` and keeps its last row in `positions.jsonl`.
  - Deleting `store.sqlite` and running any read command rebuilds it transparently; cache rows in `cache/cache.sqlite` survive a reindex; a `schema_version` mismatch triggers a full rebuild.
  - A second `fo sync` started while the lock is held exits non-zero without writing.
  - A JSONL line missing `as_of` is rejected by the writer.
- **Verification:** golden-file tests for every JSONL schema; reindex is idempotent (same row counts twice).

### U6. Providers, cache, `fo sync`, `fo auth`

- **Goal:** read-only providers behind one protocol and one cache, idempotent sync, honest authentication.
- **Requirements:** R3, R5, R7, R9, R26.
- **Dependencies:** U5.
- **Files:** `src/fo/providers/base.py`, `cache.py`, `schwab.py`, `simplefin.py`, `imports.py`, `alphavantage.py`, `edgar.py`, `fred.py`, `src/fo/sync/__init__.py`, `src/fo/auth.py`, `tests/fixtures/providers/*.json` (recorded responses), `tests/test_providers_readonly.py`, `tests/test_sync.py`, `tests/test_cache.py`.
- **Approach:**
  1. `Provider` protocol: `accounts()`, `positions()`, `balances()`, `transactions(since)`; market providers: `quote()`, `fundamentals()`, `filings()`, `series()`, `frames()` (SEC XBRL Frames: one concept across all filers for a period). No other methods. The introspection test asserts no provider module defines a method matching `order|trade|transfer|withdraw|deposit|place|submit`.
  2. Schwab via `schwab-py` with `enforce_enums=False`; account hashes from `accounts/accountNumbers` stored in `secrets/keys.toml`, never in source or tracked files; `schwab-py`'s token refresh writes through the same atomic 0600 writer; money-market symbols reclassified as cash; cash synthesised from balances; short quantities respected. `fo auth schwab` always runs the browser flow and records the real seven-day expiry; the doctor check `schwab.token` warns at two days and fails at zero.
  3. SimpleFIN: claim flow (`fo auth simplefin`), single `GET /accounts` with epoch-second window, `pending=1`, 30-day routine window, `--full` backfill capped at 90 days, match by bridge id, then by fingerprint (account, amount, `transacted_at` within three days, normalised description) so an unambiguous re-post under a new provider id appends a revision of the earlier stable transaction id instead of duplicating. Multiple fingerprint candidates remain unresolved and are reported for review rather than silently merged; a pending row is marked expired by an appended status event after three fetched windows whose `transacted_at` range covers it; account mapping by explicit id then conservative last-4, never keyword guessing. Provider text fields are marked untrusted in `--json` output.
  4. Imports: CSV parsers for Schwab positions export and Monarch transactions (`Date, Merchant, Category, Account, Original Statement, Amount`), dropped in `office/imports/`, consumed once and recorded in `sync_log`. Each account names one provider of record in `accounts.json`; an import for an account whose provider of record is live is refused unless `--before DATE`, and imported rows are fingerprint-deduplicated against existing ones.
  5. Cache: every market call goes through `cache.get(key, ttl, fetch)` in `office/cache/cache.sqlite`, separate from the index, with a per-provider daily request budget (`[providers.alphavantage].daily_limit`, default 25, counted per UTC day); an AlphaVantage 200 body carrying `Information` or `Note` is a provider error that is never cached, serving the cached value with a warning or exiting non-zero with `reason: rate_limited`; `fundamentals()` falls back to EDGAR company facts when the budget is spent; on a miss with no key the command exits non-zero with a `reason` field. TTLs: prices 15 minutes in market hours or until next open; fundamentals, filings, macro 24 hours. SEC requests send a `User-Agent`.
  6. `fo sync [--provider ...] [--dry-run] [--commit]` refuses to append `data/` unless this host is `[hosts].writer`, takes the office lock, appends snapshots and transactions with one `run_id` in a fixed file order ending with each provider's `sync_log` `complete` line (listing the accounts it returned), compares complete account snapshots, including the full position set and balances, using a content hash that excludes `as_of` and `run_id`; a changed snapshot appends all its rows, while an identical snapshot records the R3 reference without appending position or balance rows, reindexes, and with `--commit` commits `data/`, `notebook/`, and `reports/` (committing before pulling with rebase and pushing when `[hosts].remote` is set, under the same lock and dirty-tree/conflict rules as F2); `fo sync status` reads `sync_log.jsonl`. Failures in one provider do not block others; `--dry-run` output shows account numbers as last four only.
- **Execution note:** record real provider responses once by hand into fixtures (scrubbed), then develop against fixtures; the live path is smoke-tested manually by Elliott.
- **Patterns to follow:** v1 `scripts/simplefin/client.py` credential splitting and `normalize_txn`; v1 `scripts/schwab/sync.py` `classify_type` and `transform_position`; v1 `scripts/schwab/client.py` allow-list shape (as a second guard around `schwab-py`).
- **Test scenarios:**
  - Covers AE5. Recorded Schwab positions synced twice append rows once.
  - Covers AE7. Introspection test over `src/fo/providers/` finds no forbidden method names.
  - A SimpleFIN pending transaction that later posts with the same id supersedes the earlier row in the index; one absent from three covering windows gets an expired event.
  - A recorded Schwab transaction lands with only the last four digits in `raw`.
  - An AlphaVantage `Information` body is not cached, the cached value is served with a warning, the daily budget refuses the 26th call with `reason: rate_limited`, and `fundamentals` then answers from EDGAR company facts.
  - `fo sync` on a host that is not `[hosts].writer` exits non-zero without touching `data/`.
  - A SimpleFIN row that re-posts under a new id updates the existing row by fingerprint; an overlapping Monarch import for a SimpleFIN-owned account appends zero rows.
  - A simulated crash between `positions.jsonl` and `balances.jsonl` leaves a run with no `complete` line that the views ignore and the next run supersedes.
  - A money-market position becomes a cash balance, not an equity position.
  - Cache returns the stored value inside TTL and refetches after it; a provider error inside TTL returns the cached value with a warning.
  - `fo sync` with an expired Schwab token fails Schwab, still syncs SimpleFIN, and exits non-zero with both outcomes in `sync_log`.
  - `fo auth schwab` writes the token at mode 0600 and an expiry seven days out.
  - Covers AE6. Doctor warns at 36 hours to expiry and fails at zero.
- **Verification:** `fo sync --dry-run` on fixtures prints the rows it would append; `fo sync status --json` lists one entry per provider per run.

### U7. Compute commands

- **Goal:** every number a skill needs comes from a `fo` command with a stable `--json` shape.
- **Requirements:** R6, R9.
- **Dependencies:** U5, U6.
- **Files:** `src/fo/compute/{networth,positions,allocation,spend,cashflow,goals,lots,market}.py`, `src/fo/compute/categorize.py`, `src/fo/store/schemas/output/*.schema.json`, `tests/test_compute_*.py`, `tests/golden/*.json`.
- **Approach:**
  1. Commands: `networth [--as-of] [--by account|type|owner]`, `positions [--account] [--symbol]`, `allocation` (current weights vs IPS bands with drift flags), `spend --month [--category]`, `cashflow --months N`, `goals` (progress and required monthly contribution), `lots SYM` (holding period and gain from sourced lot records; explicit unknown fields and a data-gap reason when acquisition dates or basis are unavailable), `quote SYM...`, `fundamentals SYM`, `filings SYM [--form]`, `macro SERIES [--since]`, `screen --concept <us-gaap tag> --period <CYyyyy|CYyyyyQn> [--min|--max] [--universe NAME] [--limit N]` (ranked candidates with values and `as_of` from SEC XBRL Frames).
  2. Categorisation is rule-based from `profile/categories.yaml` (descriptor rules, payee overrides, account routing, transfer detection so internal moves are not spend), categories live only in the index, are recomputed on reindex when the rules hash changes, and `fo categorize` reports uncategorised rows.
  3. Every command validates its own `--json` output against a schema in tests; skill-facing JSON defaults to a summary view with `--full` for everything; human output is a table.
  4. Account read paths never touch a provider; market commands fetch lazily through the cache when a key is present and otherwise return the cached value with `as_of` or exit non-zero with a `reason` field.
- **Patterns to follow:** v1 `scripts/expenses/categorize.py` precedence (payee override, then descriptor rules, then needs-review) and `compute_monthly`; the allocation table in v1's `cio` skill for the human layout.
- **Test scenarios:**
  - `networth --by type` on the fixture matches the golden totals and sums to the grand total.
  - `allocation` flags a class whose weight is outside its IPS band and reports the drift in points.
  - `spend --month 2026-08` excludes transactions categorised as transfers and matches the golden figure.
  - `goals` reports "behind by X per month" for a fixture goal that is underfunded and "on track" for one that is not.
  - `lots ACME` labels sourced lots bought 400 and 100 days ago long- and short-term respectively. A position with only aggregate average basis and no acquisition date yields unknown lot/holding-period fields and a data-gap reason; it never fabricates a purchase date from snapshot or migration time.
  - `quote ACME` with no key and a cached price returns the price with its `as_of`; with no cache it exits non-zero with a message naming the missing key.
  - Every command's `--json` validates against its schema.
  - Editing a category rule and reindexing changes `spend` without changing `transactions.jsonl`.
  - `screen --concept Revenues --period CY2025 --min 1e9` on recorded Frames returns a ranked list and respects `--universe`.
- **Verification:** golden-file tests for all eleven commands; `fo <command> --json | jq` works for each.

### U8. `fo brief` and `fo start`

- **Goal:** the read-only opening every skill runs, in one call.
- **Requirements:** R10, R14.
- **Dependencies:** U7, U9, U10.
- **Files:** `src/fo/brief.py`, `src/fo/start.py`, `tests/test_brief.py`, `tests/test_start.py`.
- **Approach:**
  1. `brief --level none` prints only notebook context: open decisions on the subject when `--for` is given and the corrections in scope (global plus the running skill's and the subject's), never holdings or IPS, so research runs without household bias while still reading its own notes. `household` (target 500 estimated tokens): IPS bands and prohibitions, held symbols with weights, cash available, up to five general open decisions, every correction in scope, the oldest contributing `as_of`, and any provider whose newest complete run is older than the sync cadence. `--for SYM` adds the holding, a lots summary (count, total basis, short- and long-term split; `--full` lists the lots), and every open decision on that symbol, outside the five-decision limit. Mandatory corrections and subject decisions remain complete even when they require exceeding the token target; human and JSON output then include an overflow warning, and overflow alone does not cause a non-zero exit. `full`: household plus goals with status, tax picture, last 90 days cash flow, and all active corrections. No level prints an account number or a secret.
  2. `start <skill> <subject> [--level]` runs the brief at the skill's default context (from `metadata.default-context`, overridable within `allowed-context`), `fo prior`, and `fo report path` for the skill's report kind, and returns one JSON object with each part and a per-command status so a failure in one part is visible; it writes nothing.
  3. Token budget is measured with a simple word-based estimate in tests; the implementer may swap in a tokenizer if one is already a dependency.
- **Patterns to follow:** the draft plan section 6.4 levels; v1 report header conventions for the human-readable part.
- **Test scenarios:**
  - `brief --level none` with no `--for` prints only global corrections; with `--for ACME --skill research` it adds the open ACME decision, the research-scoped and ACME-scoped corrections, and no holdings line.
  - Covers AE4. With the fixture's Schwab run older than the sync cadence, `brief --level household` names Schwab as stale and reports the older `as_of`.
  - Budget tests on the ordinary fixture and on the stress fixture stay within 500 estimated tokens and name every held symbol when mandatory corrections and subject decisions do not require overflow.
  - A budget-overflow fixture contains corrections and more than five open decisions on ACME whose mandatory text alone exceeds 500 estimated tokens. `brief --level household --for ACME` includes every applicable correction and all open ACME decisions without truncation, warns in both human and JSON output, and exits 0 when no other error exists. The same fixture's `none` and `full` outputs preserve their required corrections and subject decisions.
  - `brief --level household --for ACME` includes the open fixture decision on ACME and a lots summary; `--full` lists the lots.
  - `brief --level full` includes the active corrections in order and the goals table, and never an account number or secret.
  - `start research ACME` returns brief, prior, and a report path under `reports/research/ACME/` with `prior:` filled; with the index unwritable it still answers from JSONL; with `fo prior` failing, the object carries that part's error and the other parts succeed.
  - `brief` with an unknown level, or `start` with a level outside the skill's `allowed-context`, exits non-zero.
- **Verification:** ordinary, stress, and overflow budget tests are part of CI; brief JSON including overflow warnings and `start` output validate against their schemas.

### U9. Journal, invalidation grammar, `fo review`, corrections

- **Goal:** the compounding engine: decisions with checkable invalidations, a review that checks them, and a corrections loop.
- **Requirements:** R12, R13, R14.
- **Dependencies:** U7.
- **Files:** `src/fo/notebook/journal.py`, `src/fo/notebook/clauses.py`, `src/fo/notebook/review.py`, `src/fo/notebook/corrections.py`, `src/fo/store/schemas/decision-event.schema.json`, `src/fo/store/schemas/review-record.schema.json`, `tests/test_journal.py`, `tests/test_clauses.py`, `tests/test_review.py`.
- **Approach:**
  1. `decisions.jsonl` is an event log: a `created` event carries `id`, `date`, `subject`, `action`, `thesis`, `invalidate` (free text), `when` (clause list), `price_at` and `price_at_as_of`, `conviction`, `context_level`, `source`, `report`; `closed` events carry `outcome` (`hit`, `miss`, `neutral`, `unknown`) and a note; `reopened` events carry a reason; `reviewed` events are appended by `fo review` with flags (`breached`, `needs_judgment`), the metric values used with their `as_of` and source, and an optional `judged_until` date set by the review skill to silence a needs-judgment flag until then. Stored status is only open or closed, derived from the latest event.
  2. Grammar per KTD8, backed by a metric table (name, unit, domain, cadence, source); a clause with an unknown metric, a percentage sign, an out-of-domain value, `for` on a non-quarterly metric, or `==` on a float metric is rejected at `journal add` time with a hint.
  3. `journal add|list [--open] [--subject]|close ID --outcome|reopen ID`; `review` evaluates every open decision, appends one `reviewed` event per decision and one summary line to `notebook/reviews.jsonl`, renders `notebook/reviews/YYYY-MM-DD.md` from those records (breaches, needs-judgment items not silenced by `judged_until`, a Due for verdict list of breached decisions and open decisions older than `[notebook].verdict_days`, calibration over closed decisions with a known outcome grouped by conviction and source), and prints breaches; exit code non-zero when a breach exists so the scheduler can notify. Re-running on the same day appends nothing new when values are unchanged.
  4. `corrections add "..." [--scope global|skill:<name>|subject:<SYM>]` appends a dated, numbered, scoped entry to `notebook/corrections.md`; `corrections retire N` marks one retired; `corrections list [--skill] [--for]` prints the active ones in scope.
  5. `fo commit` stages `notebook/` and `reports/`, commits, pulls with rebase, and pushes when `[hosts].remote` is set; it is the skeleton's last step on checkouts other than the Mini and creates no commit when clean. With a configured remote it still pulls and pushes pending commits, so a failed push can be retried without new file changes. It holds the office lock, refuses unrelated dirty tracked files, stops without pushing on a rebase conflict, and reindexes after merging.
- **Execution note:** implement the clause grammar test-first; it is the one piece of the notebook with real edge cases.
- **Patterns to follow:** v1 `journal` skill's intake questions (action, thesis, invalidation, conviction) for the human prompts in U11; the draft plan section 6.5 line schema.
- **Test scenarios:**
  - Covers AE2. Fixture decision with `price < 100` and cached price 95 gets a `reviewed` event flagged breached carrying 95, its `as_of`, and source; the markdown review names it.
  - `rev_growth_yoy < 0.20 for 2q` with fundamentals showing one quarter below is not breached; with two consecutive quarters below it is.
  - A clause with an unknown metric, `rev_growth_yoy < 20`, `price < 95 for 2q`, or `weight == 0.1` is each rejected at `journal add` with a hint naming the rule.
  - A decision with only free-text invalidation appears under needs judgment.
  - `journal close ID --outcome hit` appends a closed event; a second close is rejected; `reopen` restores open status.
  - Calibration over the fixture's closed decisions reports hit rate per conviction level matching a hand computation and excludes `unknown` outcomes.
  - Running `review` twice on the same day appends no second summary line; a needs-judgment flag with `judged_until` in the future is omitted from the markdown review.
  - `corrections retire 2` removes entry 2 from `corrections list` and from `fo brief`; `corrections list --skill research --for ACME` returns global, research-scoped, and ACME-scoped entries only.
  - A decision open for 200 days with no breach appears under Due for verdict; one open for 30 days does not.
  - `fo commit` in a fixture git office creates one commit touching only `notebook/` and `reports/`; when clean it creates no commit, but retries an earlier failed push. A dirty-data sync commits before rebasing; unrelated dirty tracked files block publication; rebase conflicts preserve local commits and prevent a push.
  - `review` exits 0 with no breaches and non-zero with one.
  - `corrections add` appends with today's date and does not reorder existing entries.
- **Verification:** `fo review --json` on the fixture matches a golden file; the review markdown renders the breach table.

### U10. Reports index, `fo report path`, `fo prior`, `fo skill verify`

- **Goal:** reports become queryable, get their paths from one owner, and are checked before a skill ends.
- **Requirements:** R11, R18.
- **Dependencies:** U5.
- **Files:** `src/fo/reports.py` (frontmatter parser, `reports index`, `report path`, `prior`, `skill verify`), `tests/test_reports_index.py`, `tests/test_prior.py`, `tests/test_report_path.py`, `tests/test_skill_verify.py`.
- **Approach:**
  1. Frontmatter parser tolerant of the v1 header (no frontmatter) so migrated reports index with generated fields.
  2. `reports index` walks `office/reports/`, upserts `reports_index` (path, kind, subject, created, model, context level, summary, frontmatter JSON), removes rows whose files are gone, records `reports_indexed_at`, and reports files it could not parse.
  3. `prior SUBJECT [--kind] [--exclude PATH]` refreshes the index when `reports/` is newer than `reports_indexed_at`, orders by (date, path), excludes the path being generated, and returns the newest matching entry as path plus frontmatter and summary; `--json` for skills.
  4. `report path --kind K --subject S [--slug] [--part WORKER]` returns `reports/<kind>/<subject>/<YYYY-MM-DD>-<slug>.md` (suffixing a counter when the path exists) and a frontmatter stub (`kind`, `subject`, `date`, `model` placeholder, `context_level`, `playbooks`, `prior` from `fo prior`, `summary`, `decision_ids`); `--part` returns the sidecar path for a `--deep` worker's block.
  5. `skill verify PATH` checks the path convention, frontmatter validity, `prior:` set when a prior existed, every `decision_ids` entry resolving in the notebook, a "What changed" heading when `prior:` is set, and the closing correction line; it is skeleton step 6 (before the closing line and `fo commit`) and a CI gate over dry-run output.
  6. Reports are never rewritten by `fo`; the index is derived.
- **Test scenarios:**
  - Fixture with two research reports on ACME dated 2026-06-02 and 2026-08-15: `prior ACME --kind research` returns the August one.
  - A report with malformed frontmatter is listed under parse errors and does not abort indexing.
  - A v1-style report without frontmatter indexes with `kind` inferred from its directory.
  - `prior` for an unknown subject exits 0 with an empty result under `--json`; `prior ACME --exclude <new path>` never returns the report being written.
  - Covers AE8. A dry-run report passes `skill verify`; removing its closing line or pointing a `decision_ids` entry at a missing id fails with the check named.
  - `report path --kind research --subject ACME` returns a path under `reports/research/ACME/` dated today with `prior:` set to the fixture's prior report. Repeating the call without writing returns the same path and creates no files; after the caller writes the report, another call returns a distinct suffixed path.
  - Deleting a report file and re-indexing removes its row.
- **Verification:** `reports index` twice yields the same row count; `prior` output validates against its schema.

### U11. Core and utility skills with dry-run harness

- **Goal:** the eleven core skills and two utilities as thin canonical files that follow the skeleton, proven by a scripted dry run on the fixture office.
- **Requirements:** R15, R16, R17, R18, R23.
- **Dependencies:** U3, U8, U9, U10.
- **Files:** `skills/{research,diligence,scout,macro,cio,cfo,tax,plan,journal,briefing,review,onboard,eli5}/SKILL.md`, `skills/research/lenses/{semis,biotech,energy,financials,software,consumer}.md`, `tests/skills/dryrun_research.py`, `tests/skills/test_dryrun.py`; delete `.claude/skills/*` v1 files and `.claude/agents/lead-edge-researcher.md`.
- **Approach:**
  1. Each skill: frontmatter (`name`, `description` with trigger phrases, `metadata: {tier, default-context, allowed-context, args}`), then the judgment rubric, the `fo` commands to run (also declared in `metadata.commands`), output sections, and the closing correction line. No skeleton restatement; the skeleton is cited as "follow the skill skeleton in `AGENTS.md`".
  2. Tiers: `strong` for `cio`, `tax`; `balanced` for `research`, `diligence`, `scout`, `macro`, `cfo`, `plan`, `review`, `briefing`, `onboard`; `fast` for `journal`, `eli5`. Default context: `none` for `research`, `diligence`, `macro`, `journal`, `eli5`; `household` for `scout`, `briefing`, `review`; `full` for `cio`, `cfo`, `tax`, `plan`, `onboard`. Invocation: `explicit` for `onboard` and `journal`; `implicit` for the rest. `scout` declares `fo screen` in `metadata.commands`.
  3. `research` takes `--lens` (a short rubric file under the skill directory, copied into the office by `fo skills sync`) and `--playbooks`; `--deep` delegates slices to the five workers per KTD6.
  4. `briefing` is one model call, run by hand, over `fo sync status`, `fo brief --level household`, the last review, and cached quotes; no web search, no fan-out.
  5. `onboard` interviews for each authored file, writes it, and runs `fo doctor` after each; `eli5` restates the last output in plain language.
  6. Dry-run harness: a script that runs `fo start` and the commands declared in `metadata.commands` for a skill against the fixture, writes a synthetic report at the returned path with valid frontmatter, journals one decision, runs `fo skill verify`, and runs a second time to assert the delta fields. It exercises the plumbing, not the model.
- **Patterns to follow:** v1 skill rubrics for domain content (`equity-research` sections, `cio` synthesis structure, `journal` intake questions), stripped of tool and provider text.
- **Test scenarios:**
  - Covers AE1. Dry run of `research` twice on ACME: second report frontmatter has `prior:` pointing at the first and the body contains a "What changed" heading.
  - Every core skill passes `scripts/lint_skills.py` (size, forbidden tokens, spec frontmatter, tier present).
  - `fo skills sync` renders all thirteen with the expected tier fields and both hosts list them.
  - `briefing` dry run makes no network call (providers stubbed to raise).
  - Covers AE3. The rendered journal skill carries the fast-tier model from `office.toml`; its canonical file has no `model` key.
  - Every dry-run report passes `fo skill verify`.
- **Verification:** lint and dry-run tests green; a manual run of `/research ACME` in each host on the fixture office produces a report that passes `fo skill verify` and a journal entry, and AE9's correction-compliance run passes in each host.

### U12. Playbooks: schema, scorer, library, skills

- **Goal:** nine checklist playbooks scored mechanically where possible, with the judgment criteria handed to a thin skill.
- **Requirements:** R6, R15, R16.
- **Dependencies:** U7, U11.
- **Files:** `src/fo/playbooks/schema.py`, `src/fo/playbooks/scorer.py`, `src/fo/playbooks/library/{lead-edge-eight,piotroski,greenblatt,compounder,lynch,fisher,powers,marks,all-weather}.yaml`, `skills/<each>/SKILL.md`, `tests/test_playbooks.py`, `tests/fixtures/office/playbooks/overrides/lead-edge-eight.yaml`.
- **Approach:**
  1. YAML per the draft plan section 6.6: `name`, `title`, `attribution`, `scope` (company, portfolio, market), `criteria[]` with `kind` mechanical or judgment, `metric`, `op`, `threshold`, `evidence[]`, and `verdict.format`.
  2. `fo score SYM --playbook NAME [--playbook NAME2]` resolves mechanical metrics from fundamentals, filings, and quotes, emits pass, fail, borderline, or judgment per criterion with evidence pointers, and never writes a verdict. `fo score-portfolio --playbook all-weather` uses allocation output. `fo playbooks list` shows library and override status.
  3. Overrides: `office/playbooks/overrides/<name>.yaml` deep-merges thresholds over the library file.
  4. Each playbook skill: run `fo score`, decide the judgment criteria from the evidence, write the scorecard at `fo report path --kind score`, journal only when asked. Under 1.5 KB each.
  5. Implementation order per KTD13.
- **Patterns to follow:** v1 `lead-edge-eight` skill for the eight criteria, thresholds, and forward-math description; move its thresholds into YAML and its prose into the judgment criteria text.
- **Test scenarios:**
  - `fo score ACME --playbook lead-edge-eight --json` returns eight criteria, each with a status and evidence pointers, and no verdict field.
  - A fixture override lowering the gross-margin threshold flips criterion 3 from fail to pass without touching the library file.
  - A YAML with an unknown metric fails schema validation naming the criterion.
  - `score-portfolio --playbook all-weather` reports each sleeve's weight against its target band.
  - A judgment criterion with unavailable evidence is reported as `judgment` with an empty evidence list, not as fail.
- **Verification:** all nine library files validate; the four mechanical-heavy playbooks have golden scorecards on the fixture.

### U13. Specialists and `--deep` sub-agents

- **Goal:** the six specialist skills and the five workers, rendered for both hosts.
- **Requirements:** R15, R17, R22.
- **Dependencies:** U3, U11.
- **Files:** `skills/{options,technicals,risk,realestate,ventures,estate}/SKILL.md`, `agents/{fundamentals,competitive,valuation,risk,sentiment}-analyst.md`, `tests/test_agents_render.py`.
- **Approach:**
  1. Specialists follow the skeleton with default contexts: `household` for `options` and `realestate`; `none` for `technicals`; `full` for `risk`, `ventures`, `estate`. `risk` always runs the allocation and concentration commands and never fans out.
  2. Workers are small and generic: each names its slice, the input files it reads from the report's part directory, and the bounded structured block it returns; tier `balanced`; no shell or write tool. The orchestrator runs every compute command before delegating, saves the outputs under `fo report path --part inputs`, writes each worker's block to `fo report path --part <worker>` as it returns, and resumes from parts that already exist. The canonical file has frontmatter `name`, `description`, `metadata: {tier}` and a body; U3 renders both host formats.
  3. `research --deep`, `diligence --deep`, and `cio --deep` name the workers they delegate to; every other skill has no `--deep`.
- **Patterns to follow:** v1 `lead-edge-researcher` agent for the "data, not judgment" framing; v1 `risk` skill scenarios for the specialist rubric, with the historical drawdown numbers moved into `fo` compute inputs or the IPS rather than prose.
- **Test scenarios:**
  - Each specialist passes the skill lint and renders in both hosts.
  - Rendered `.codex/agents/risk-analyst.toml` has `sandbox_mode = "read-only"` and the balanced-tier model and effort; the Claude copy lists only `Read`, `Grep`, and `Glob`.
  - `risk` skill body contains no fan-out language; `research` body gates fan-out behind `--deep`.
  - A `--deep` dry run with two of five parts pre-existing dispatches only the missing three, the orchestrator writes those three part files, and five are assembled.
- **Verification:** a manual `/research ACME --deep` in Claude Code spawns the named workers; in Codex the same request delegates to the custom agents; both produce one report.

### U14. Scheduling, notifications, cloud setup

- **Goal:** the boring work runs on a schedule with no model, and a human is told when something needs them.
- **Requirements:** R25, R26.
- **Dependencies:** U6, U9, U11.
- **Files:** `src/fo/schedule.py`, `src/fo/notify.py`, `src/fo/templates/launchd/*.plist`, `docs/office-layout.md`, `tests/test_schedule.py`.
- **Approach:**
  1. `fo schedule install` writes plists into `office/launchd/` and prints the `launchctl` commands: sync nightly 02:00 with `--commit` (and a push when `[hosts].remote` is set), doctor daily 07:30, review Sunday 08:00, and reports index after sync. Plists set `PATH` to include the office `.venv/bin`, invoke `uv run fo`, carry no secrets, and only the Mini installs the sync job; `plutil` checks run on macOS and `plistlib` elsewhere.
  2. `fo notify "<message>"` posts a macOS notification through `osascript`, passing the text as an argument rather than interpolating it into the script; doctor and review call it on warn or fail when `--notify` is set by the plist.
  3. `docs/office-layout.md` documents the second-machine and Codex cloud flow (F3): GitHub remote, cloud setup script `uv sync`, no secrets in the cloud environment (market commands answer from cache or report a data gap), and the note that the environment holds a clone of the entire office.
- **Execution note:** configuration and process wiring; verify by loading the plists on the Mini and checking `launchctl list`.
- **Patterns to follow:** the existing `com.jacobs.family-office-app.plist` shape (working directory, log paths) for the plist template.
- **Test scenarios:**
  - `schedule install` writes four plists (sync, doctor, review, index) and none invokes a model host.
  - Each plist validates with `plutil -lint`.
  - Doctor run with `--notify` and a failing check invokes the notifier once (stubbed).
  - A scheduled sync on a fixture git office produces one new commit touching only `data/`, `notebook/`, and `reports/`.
  - No plist contains a value loaded from `secrets/` and none names `claude` or `codex`.
- **Verification:** plists load without error on the Mini; the nightly sync writes a `sync_log` row the next morning.

### U15. v1 migration

- **Goal:** a one-shot import of the v1 office into the v2 layout that leaves the source untouched.
- **Requirements:** R27.
- **Dependencies:** U5, U9, U10.
- **Files:** `src/fo/migrate_v1.py`, `tests/fixtures/v1-office/` (a fake v1 vault with every file v1 writes), `tests/test_migrate_v1.py`.
- **Approach:**
  1. `fo migrate-v1 SRC [--dry-run]` reads v1 `profile/*.json` into the authored files (`family.json` and `goals.json` into `household.md` and `goals.json`; `investment-policy.json` and `risk-tolerance.json` into `ips.json`; `tax/*.json` into `tax.json`; the account files into `accounts.json` (the v1 `api-keys.json` Schwab hash map goes to the re-enter list for `fo auth`, never into a tracked file)), writes one initial snapshot dated from v1's `data_as_of` from `holdings.json` and the account balance files, converts `profile/transactions/**` into `transactions.jsonl` keeping v1 ids so the first live sync appends nothing, turns `journal/entries/*.md` into `created` events with free-text invalidation, `source: v1-migration`, `migrated_from`, and a `closed` event when the entry's last status line says so, copies `reports/**` and `briefings/**` under `office/reports/` with generated frontmatter, and turns `memory/feedback_*.md` bullets into `notebook/corrections.md`.
  2. The command refuses a non-empty target without `--force` and never rewrites `household.md` prose on a re-run; every mapping ambiguity (both v1 account vocabularies, entries with several status lines, missing conviction) is written to `office/notebook/migration-report.md` rather than guessed silently, together with how many v1 invalidation lines parse under the KTD8 grammar and the unparsed phrasings, the note that Schwab transaction history begins at the first v2 sync (v1 never stored it), and any v1 sync job found in `launchctl list` to unload.
  3. The migration prints its rollback steps (delete the new office; the vault is untouched) and the `launchctl` commands to unload any v1 job it found.
  4. Secrets are not migrated; the report lists which keys to re-enter with `fo auth`.
- **Execution note:** build against the fake v1 vault only; Elliott runs it once against the real vault with `--dry-run` first.
- **Patterns to follow:** the v1 audit's file inventory (Appendix A) for every source path and shape.
- **Test scenarios:**
  - Migration of the fake vault yields a `fo doctor` pass and the expected row counts in each JSONL.
  - A v1 journal entry with "Status: CLOSED" becomes a closed decision; one without becomes open.
  - A v1 report without frontmatter is indexed with `kind` from its directory and `date` from its filename.
  - `--dry-run` writes nothing and prints the same counts.
  - Post-run checks: the brokerage positions total equals `holdings.json` `total_portfolio_value`, each v1 account and debt file balance equals its `fo networth --by account` row, JSONL counts match the source inventory, and the index count equals the report files.
  - A recorded SimpleFIN sync after migration appends zero transaction rows.
  - A second run on the non-empty target is refused without `--force`.
- **Verification:** `fo migrate-v1 --dry-run` on the real vault (Elliott) reports zero unmapped accounts before a real run.

### U16. Docs, security statement, release

- **Goal:** accurate public docs and a tagged v2.0.0.
- **Requirements:** R29, R30.
- **Dependencies:** all.
- **Files:** `README.md`, `SECURITY.md`, `CHANGELOG.md`, `docs/explainers/family-office-system.html` (moved and updated), `docs/office-layout.md`, `docs/skill-authoring.md`.
- **Approach:**
  1. README: what `fo` is, install (`uv tool install` or office `uv sync`), the fifteen-minute path to `fo doctor` green, the skill roster with one line each, both hosts' invocation forms, and the privacy statement: data stays local; at query time prompt content (which may include holdings) goes to the configured model provider; tickers and queries go to the configured data providers.
  2. SECURITY.md: every third party (Anthropic or OpenAI as the session host, Schwab, SimpleFIN, AlphaVantage, SEC, FRED, GitHub when `[hosts].remote` is set) and what each receives, including that a Codex cloud environment holds a clone of the entire office checkout, not only the brief; the read-only design and its limits (the Schwab token is trade-capable; its confidentiality and the absence of write code are the controls); the untrusted-text rule; the token-expiry behaviour; the history-rewrite note carried from v1.
  3. Explainer updated for the v2 shape; CHANGELOG from the phase PRs; tag `v2.0.0`.
- **Test expectation:** none, documentation; verified by the definition-of-done walk-through.
- **Verification:** a fresh clone plus `fo init` plus real keys reaches `fo doctor` green in under fifteen minutes following the README only.

---
## Verification Contract

All commands run from the repo root against `tests/fixtures/office/` unless noted. Every gate runs in CI on every push.

| Gate | Command | Proves | Applies to |
|---|---|---|---|
| Unit and golden tests | `uv run pytest` | store, providers, compute, notebook, playbooks, migration, skill dry runs | U1-U15 |
| Lint and types | `uv run ruff check . && uv run ruff format --check .` | code style | all code units |
| Secrets scan | `gitleaks detect --source . --no-banner` | no secret in history or tree | all |
| Office-path lint | `uv run python scripts/lint_office_paths.py` | R4: no office path tracked | U1 onward |
| Skill lint | `uv run python scripts/lint_skills.py skills/ AGENTS.md` | R16, R19: size caps, forbidden content, spec frontmatter, dev symlink parity | U2 onward |
| Provider read-only | `uv run pytest tests/test_providers_readonly.py` | R7 (AE7) | U6 onward |
| Idempotent sync | `uv run pytest tests/test_sync.py -k idempotent` | R3 (AE5) | U6 onward |
| Store integrity | `uv run pytest tests/test_store.py -k "complete or void or lock"` | R3: incomplete runs invisible, voids honoured, lock exclusive | U5 onward |
| No-leak | `uv run pytest tests/test_no_leak.py` | R5: every `fo` command (human, `--json`, `--dry-run`, forced provider errors) run against sentinel secrets and account numbers prints no sentinel | U6 onward |
| Report verify | `uv run pytest tests/test_skill_verify.py tests/skills/` | R18 (AE8): every dry-run report passes `fo skill verify` | U10 onward |
| Brief budget | `uv run pytest tests/test_brief.py -k budget` | R10 household target of 500 estimated tokens; mandatory corrections and subject decisions preserved on overflow with a warning | U8 onward |
| Review breach | `uv run pytest tests/test_review.py -k breach` | R13 (AE2) | U9 onward |
| Skill dry run | `uv run pytest tests/skills/` | R11, R18 (AE1) plumbing without a model | U11 onward |
| Adapter render | `uv run pytest tests/test_skills_sync.py tests/test_agents_render.py` | R20-R22 (AE3) | U3, U13 |
| Fresh-office smoke | `uv run fo init /tmp/fo-smoke && uv run fo doctor --office /tmp/fo-smoke` | R8 scaffold reaches doctor | U1, U4 |
| Manual host check | run `/research ACME` in Claude Code and `$research ACME` in Codex inside the fixture office | both hosts load the same skill and produce an indexed report | phase E gate |
| Agent-run live check | `fo setup` discovers accounts, authenticates, syncs, and runs diagnostics on the Mini; agent validates provider outputs | providers work end to end | required before cutover; agent owns execution, Elliott supplies credential entry/consent only; pending access does not block fixture-based implementation |

Behavioural skill evaluation beyond the dry run is manual: one run per core skill in each host on the fixture office, checked for the skeleton steps in the transcript.

---

## Definition of Done

Global:

- Every gate in the Verification Contract passes in CI on the fixture office.
- A fresh clone, `fo init`, and real keys reach `fo doctor` green in under fifteen minutes following the README only.
- `/research`, `/cio`, `/tax`, `/lead-edge-eight`, `/risk`, and `/onboard` each produce correctly indexed output on the real office in Claude Code, and the same six run in Codex from the same office checkout; when D1 resolves to a remote, F3 is exercised on a second checkout.
- `fo review` flags a deliberately breached fixture decision; `fo migrate-v1 --dry-run` on the real vault reports zero unmapped accounts.
- No skill exceeds 3 KB; no provider has a write method; no office path is tracked; gitleaks is clean across history; `AGENTS.md` is under 32 KiB.
- Every dry-run report passes `fo skill verify`; no permission template allows edits under `data/`, `notebook/`, or `profile/` (the first two are denied, `profile/` prompts except during `onboard`); the no-leak gate proves no `fo` output contains a secret or a full account number.
- The v1 trees (`.claude/skills/*` v1 files, `.claude/agents/lead-edge-researcher.md`, `.claude/settings.json`, `.agents/skills/`, `.codex/agents/*.toml` v1 file, `scripts/*` v1 scripts, `profile/api-guide.md`, `profile/SOURCES.md`) are removed; nothing from an abandoned approach remains in the tree.

Per unit: the unit's test scenarios pass, its doctor checks are registered, the README or `docs/` page it affects is updated, and its files match the Unit Index.

---

## Appendix

### Appendix A. v1 assessment

Measured on commit `95bbeed` of this checkout (17 commits, last push 2026-08-27).

**Skills (27 files, 312 KB).**

- Boilerplate: a 3,110-byte tool-priority block is byte-identical in all 27 files (27% of the corpus); a 1,641-byte sub-agent paragraph is identical in 16 (35% combined); four copies of the same priority table exist across skills, `CLAUDE.md`, and `profile/api-guide.md`, already drifting (one adds NewsAPI, one adds a rate-limit note).
- Skills contradict their own mandatory priority: `cfo` and `weekly-review` fetch holding prices by web search, `macro` uses web search where FRED is mandated, `screener` declares Gemini primary, `realestate` and `ventures` open with "use web search for data gathering".
- Compounding: 18 report skills never read a prior report; only `cio` writes memory files and only `cio` reads them; `memory/feedback_*.md` is mandated by `CLAUDE.md`, read by no skill, created by nothing; `Invalidation:` lines are write-only; journal `Status: OPEN` is never updated.
- Deterministic share by skill: `sync` 95%, `risk` 80%, `briefing` and `technicals` and `debt` and `lead-edge-eight` about 75%, `cfo` and `options` about 70%, most others 35-65%, `eli5` 0%.
- Portability: the `.agents/skills` mirror is a search-and-replace (`Codex -p --model Codex-sonnet-4-6 --allowedTools`, `.Codex/agents/`), `AGENTS.md` points at `.Codex/skills/`, the `.agents/skills/sync` copy is an older revision that hand-edits sync-owned files, and every mirror keeps Claude-only frontmatter and tool names. The Codex agent TOML has no model despite claiming "locked to Sonnet".
- Tunables buried in prose: about 160 tickers across 16 hard-coded sector universes; debt, real estate, drift, and playbook thresholds; the "25 per day" rate-limit note repeated 28 times.
- `alts-scout` and `technicals` write into `reports/equity-research/`; no report-path registry exists.

**Scripts (16 files, 3,394 lines).**

- No packaging, lockfile, or interpreter pin beyond `python3.10` shebangs; only Python 3.9 and uv-managed 3.12 exist on the Mini; `schwab-py` is an unpinned alpha; two providers both register a top-level module named `client`.
- One test file with four offline assertions; nothing covers `build_holdings`, `transform_position`, `merge_transactions`, `resolve_account`, `compute_monthly`, or `categorize()`.
- Schwab: `auth.py` reuses the existing token file and writes `refresh_token_expires_at = now + 7d`, so it never renews; refresh tokens are non-rotating and `schwab-py` has no renewal path. Short positions are ignored. Unmapped accounts are silently dropped from totals. Two conflicting account-identity vocabularies exist (`joint_aaa` versus `joint_brokerage_aaa`).
- SimpleFIN: correct read-only client and claim flow; store keyed by a mutable slug; pending rows never reconciled if the bridge changes ids.
- Secrets: `profile/api-keys.json` holds Schwab app secret, SimpleFIN access URL with embedded credentials, and Gemini key, written non-atomically at 0644 by three scripts that also use it as mutable state; `_probe/` dumps hold full account numbers.
- `consistency_check.py`: household scrub patterns are loaded but never iterated; the structured check compares an all-brokerage total against a Schwab-only total and fails for any multi-custodian household.
- Portfolio value is stored in six places; "as of" is spelled eight ways.
- Worth carrying over: SimpleFIN client and claim flow, `normalize_txn`, `compute_monthly`, the account-resolution policy, Schwab `classify_type` and `transform_position`, the categorisation precedence and `categories.example.json` shape, the genericity lint idea.

**Instruction and permission files.**

- `.claude/settings.json` allow-lists `Bash`, `Edit`, `Write`, and `Task` outright, so the "Claude Code permission settings" that `SECURITY.md` names as a real boundary are not one.
- `README.md` says "for Claude Code" and schedules the briefing with `claude -p`; nothing documents how the Codex mirror is produced.
- The draft plan's "three ELI5 HTML files" is one file at repo root.

### Appendix B. Skill roster and v1 disposition

| v2 skill | Kind | Tier | Default context | From v1 |
|---|---|---|---|---|
| research | core | balanced | none | `equity-research`; `sector-tech`, `sector-energy`, `sector-finance`, `sector-biotech` become `--lens` files (`semis` and `software` split from tech; `consumer` is new) |
| diligence | core | balanced | none | `mgmt-diligence` |
| scout | core | balanced | household | `screener` + `alts-scout` |
| macro | core | balanced | none | `macro` |
| cio | core | strong | full | `cio` (fan-out only with `--deep`) |
| cfo | core | balanced | full | `cfo` + `debt` |
| tax | core | strong | full | `tax` |
| plan | core | balanced | full | goals half of v1 `cfo`; new |
| journal | core | fast | none | `journal` (entry via `fo journal add`; also the corrections entry point) |
| briefing | core | balanced | household | `briefing` (one call, no fan-out, no web search) |
| review | core | balanced | household | `weekly-review` (judgment half of `fo review`) |
| lead-edge-eight, compounder, lynch, fisher, greenblatt, piotroski, powers, marks, all-weather | playbook | balanced | none (all-weather: household) | `lead-edge-eight`; eight new |
| options, technicals, risk, realestate, ventures, estate | specialist | balanced | household, none, full, household, full, full | same names |
| onboard | utility | balanced | full | `onboard` (writes authored files, validates with `fo doctor`) |
| eli5 | utility | fast | none | `eli5` |
| fundamentals-analyst, competitive-analyst, valuation-analyst, risk-analyst, sentiment-analyst | sub-agent | balanced | inherits | `lead-edge-researcher` generalised |
| (none) | | | | `sync` becomes `fo sync`; `medical` becomes a folder; v1 memory files become `corrections.md` and the notebook |

Codex cloud availability (an `AGENTS.md`-only host with the tracked store, no secrets, and no market cache): runnable from the store: `briefing`, `review`, `cfo`, `plan`, `tax`, `risk`, `estate`, `ventures`, `realestate`, `eli5`, `journal` (list and close only), `cio` without `--deep`; run with data gaps for anything market-dependent, because the cloud environment has no keys and no cache: `research`, `diligence`, `scout`, `macro`, the nine playbooks, `options`, `technicals`; not available: `onboard`, interactive journal intake, and every `--deep` run. Reports and journal events written there return through `fo commit` (KTD2).

### Appendix C. Cross-host facts the design relies on

Verified against official documentation and local Codex references on 2026-09-12.

- Claude Code reads `CLAUDE.md`, not `AGENTS.md`; its docs recommend `@AGENTS.md` inside `CLAUDE.md` or a symlink. It scans `.claude/skills/`, `~/.claude/skills/`, and plugin `skills/`, not `.agents/skills/`. Skill frontmatter supports `model`, `effort`, `argument-hint`, `allowed-tools`, `disallowed-tools`, `disable-model-invocation`, `context`, `agent`, `metadata`, `compatibility`; `@` imports are documented for `CLAUDE.md` only. Sub-agent files support `model` (aliases or full ids), `tools`, `permissionMode`, `skills`. A Bash deny rule is not a security boundary; `Write(path)` rules are never consulted, `Edit(path)` rules are.
- Naming: OpenAI's agent documentation now lives at learn.chatgpt.com and the desktop app is the ChatGPT desktop app, while the CLI, the IDE extension, the cloud runner, the config directory (`~/.codex`), and the agent files keep the Codex name. This plan says Codex for the host family and names the surface where it matters.
- Codex reads `AGENTS.md` (and `AGENTS.override.md`) from the repo root down to the working directory, capped at 32 KiB combined; it never reads `CLAUDE.md`. Skills live in `.agents/skills/` at repo, ancestor, and home scope; only `name`, `description`, and `metadata.short-description` are parsed and unknown keys are ignored; `agents/openai.yaml` carries display metadata and `policy.allow_implicit_invocation`; there is no per-skill model pin. Custom agents are `.codex/agents/*.toml` with `name`, `description`, `developer_instructions`, optional `model`, `model_reasoning_effort`, `sandbox_mode`, `mcp_servers`. Project-scoped `.codex/` layers apply only to trusted projects. Codex cloud loads `AGENTS.md` only and does not offer `gpt-6-astra`.
- Elliott's machine already shares skills across hosts with per-entry symlinks (`~/.agents/skills/<name>` and `~/.claude/skills/<name>` both point into one source directory), which is the mechanism U3 reuses.
- The Agent Skills specification allows `name`, `description`, `license`, `compatibility`, `metadata` (string map), and `allowed-tools`; body under 500 lines.
- Sources: Claude Code docs for skills, sub-agents, permissions, memory, plugins, and model config; OpenAI's Codex docs at learn.chatgpt.com for AGENTS.md, skills, sub-agents, config reference, models, cloud environments, and import; the Codex `migrate-to-codex` skill's `references/differences.md` (docs checked 2026-04-20); agentskills.io specification; the draft v2 plan at `docs/plans/references/family-office-v2-draft.md`.
