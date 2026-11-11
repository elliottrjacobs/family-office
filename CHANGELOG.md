# Changelog

## Unreleased

- A provider sync with returned accounts but no registered matches now fails with
  `no_mapped_accounts`, directs users to authenticate and sync again, and does not
  advance sync freshness, finish onboarding's first sync, or commit.
- Scheduling always includes `sync --commit --if-writer`; non-writer hosts skip
  cleanly. Changing `hosts.writer` reminds users to schedule the new host.
- Sync skips unmapped provider accounts and reports how many were skipped;
  `fo doctor` directs users to `fo auth <provider>` to register them.
  `fo config set` now accepts `hosts.writer` and `office.timezone`.
- `fo serve`: an optional local web app with a read-only dashboard (home, finances
  against policy bands, reports, decisions, profile, advisor directory) and guided
  onboarding from an empty folder to a synced office. Loopback by default, a
  per-launch token cookie on every route, Host and Origin checks, and optional
  `tailscale serve` access with an allowed-login list. The built app ships in the
  package; Node is needed only to change it.
- Companion app chat: each advisor page runs its skill headlessly in Claude Code,
  isolated to the office by a run profile and a guard hook, with streaming,
  follow-ups, cancel, resume, and verification by the report verifier. Verdicts,
  reopen, deferral, new decisions, and corrections can be recorded from the
  Decisions page through `fo journal` and `fo corrections`.
- New read-only commands: `fo skills list`, `fo reports list`, `fo report show`,
  `fo status [--lock]`, and `fo review --dry-run`. `fo start`, `fo report path`,
  and `fo report parts` accept `--report PATH` to resume a run on its original
  report. Skills declare `metadata.group`. Under `FO_SERVE_RUN`, `fo` refuses other
  offices and setup, credential, sync, commit, and similar commands.
- Account `role` in the registry: allocation weights use investable assets, the
  cash band and `cash_months` count bank balances, and `fo doctor` flags accounts
  without a role.
- `fo spend` ignores trades, dividends, and funding transfers; refunds lower their
  category; income rules use `income: true`.
- Uncategorized inflows no longer count as income or offset spending; `uncategorized_inflow`
  reports their total in spending and monthly cashflow results, and monthly `net` is null
  until those inflows are categorized. Cashflow marks the current month as `partial`;
  runway requires three complete months covered by every account with counted transactions
  and a positive total outflow.
- `fo performance`: modified Dietz returns per investment account with dividends,
  fees, and an optional weekly benchmark. Realized gains stay unknown without lots.
- Schwab transactions keep symbol, quantity, price, fees, and kind; option prices
  are per share; transaction dates use the office timezone.
- An interrupted append is ignored on read and removed by the next write. One
  failing SimpleFIN institution no longer blocks the others.
- Long-term lots use the one-year anniversary. Skills have distinct descriptions.
- Faster large imports; CI enforces test coverage.

### Added

- Family Office Mac app (`apple/`): a SwiftUI shell with the dashboard in a web view, a
  bundled Python and the `fo` CLI, menu bar status, launch at login, keep awake, Settings
  (General, Engines, Connectors, Devices, Advanced), an embedded terminal, a setup dialog
  and a Home checklist. Signed, notarized builds ship as a DMG with Sparkle updates, built
  by the release workflow. `fo serve --app` prints a one-line JSON handshake and
  `--parent-pid` stops the server when the app dies.
- Family Office iPhone app: pairs once with a five-minute code from the Mac over the
  tailnet, keeps a revocable device token in the Keychain, and shows the dashboard. A
  release workflow archives it for TestFlight when the signing secrets exist.
- Device tokens and pairing routes in `fo serve --remote`, with `/api/devices` to list and
  revoke, and an optional Tailscale login allowlist.
- `fo connect` stores research provider keys in `secrets/`. `fo research search` (Exa),
  `fo research fetch` (Firecrawl, or a direct fetch behind a network guard) and
  `fo research deep` (Gemini Deep Research) return text marked `untrusted`; research
  skills list their sources and the verifier checks them.
- Advisor runs can use web search and fetch at context level `none`, with a deny list,
  a per-run fetch cap and every URL logged as "sites visited".
- A second engine: Codex runs beside Claude Code, with engine, model and effort chosen
  per run and recorded. Codex ships disabled (`[serve.engines.codex] enabled = false`)
  because its read confinement is command-based; see SECURITY.md.
- `fo report write` and `fo config set` give runs and the app a route for the writes they
  lacked.
- `scripts/lint_identifiers.py`, run in CI, fails on tailnet hostnames, CGNAT addresses,
  UDID-shaped strings and absolute home paths outside documented placeholders.

### Changed

- Exa results are not cached on disk by default (`cache_hours = 0`), because Exa's terms
  restrict storing results; set hours per provider to opt in. Firecrawl keeps a 24-hour
  cache.
- `fo serve` applies the tailnet login allowlist only to requests that arrive through the
  tailnet name; on loopback the launch cookie is the gate, so the Mac app keeps working
  with `--remote` and `allowed_logins` both on.
- The launch cookie is `Secure` only on a landing reached through the tailnet name.
- The Mac app names the Claude CLI with `FO_CLAUDE_EXECUTABLE`, and the config route lists
  which provider keys exist (masked) so Connectors shows what is connected.
- `fo config set` accepts `serve.max_budget_usd`, `serve.run_timeout_minutes` and
  `serve.keep_runs`.

### Fixed

- The Mac app's own web view no longer loses its session when phone access is on, and a
  server whose app crashed stops within seconds.

### Security

- Closed SEC-26 and SEC-27 in the advisor-run guard: restricted `fo` commands are
  refused after a `--` separator and with `--install-completion`, hidden folders under
  `reports/` cannot be written, and a run cannot record a correction with another
  run's source.
- New exposures, described in SECURITY.md: web access at level `none`, research provider
  keys in `secrets/`, device tokens over the tailnet, and the Codex command-based read
  barrier (the reason Codex ships disabled).

## 2.0.0a1 — 2026-09-13

Clean rebuild of family-office with fresh repository history.

- Separate public package and private office repositories; automated setup,
  credential protection, diagnostics, and cross-host skill rendering.
- Read-only account adapters, append-only snapshots and transaction revisions,
  historical imports, offline projections, and budgeted market caches.
- Household calculations, source-aware market facts, nine scoring playbooks,
  dated reports, decision invalidation, corrections, and review calibration.
- 28 advisor skills, five evidence workers, resumable report parts, migration,
  notification support, and prepared launchd schedules.
- Synthetic reconciliation, JSON output contracts, and workflow tests.

Live provider reconciliation, native host acceptance, scheduled-run verification,
and the user-approved cutover are pending. No stable 2.0.0 release is claimed.
