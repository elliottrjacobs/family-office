# Changelog

## 2.0.0b5 — 2026-11-17

- On macOS, provider credentials now live in the login Keychain instead of 0600
  files: `keys.toml` (Plaid client ID and secret, SimpleFIN access link, market keys),
  each `<provider>.json` research key, and `plaid-items.json` (Plaid access tokens).
  Items stay on this Mac and never enter iCloud Keychain. Existing files move the
  first time `fo serve`, `fo doctor --fix`, or a credential command runs: each is
  copied, read back, and only then removed, so nothing has to be entered or linked
  again. `fo doctor` reports where credentials are kept and lists any that did not
  move. `fo config set credentials.store file` goes back to files and moves them
  back; other systems keep using files. Paired-device records (`devices.json`, token
  hashes only) stay a file. If macOS asks whether family-office may use the item,
  that is a different copy of `fo` than the one that stored it; allow it once.

## 2.0.0b4 — 2026-11-15

- Plaid is an optional account connector you use with your own Plaid developer
  account: `fo auth plaid` (or Settings > Connectors > Plaid in the Mac app) asks for
  your client ID and secret, keeps them in the per-machine credentials folder, and
  opens Plaid Link on a one-time local page. Sync brings Plaid accounts, balances,
  holdings and transactions into the same records as the other providers. Run it
  again to add an institution or reconnect one that needs attention.
- No account provider is a default any more. `fo setup` asks which to connect
  (Plaid, SimpleFIN, both, or none) instead of trying Schwab and SimpleFIN;
  `--provider` still chooses up front, and without a terminal setup connects
  nothing. Plaid is listed first in the app and onboarding for its breadth of
  coverage; SimpleFIN works as before.
- The direct Schwab connector is gone: link Schwab through Plaid instead. Schwab's
  developer API issues keys that can also place trades, and Plaid reads the same
  accounts, holdings and transactions. Accounts registered through the old connector
  keep their history but no longer sync; `fo auth schwab` and `fo sync --provider
  schwab` say how to switch, and `fo doctor` warns until the old accounts are removed
  from `profile/accounts.json`. Quotes now come from AlphaVantage alone, and the
  schwab-py dependency, with the 21 packages only it needed, is gone.
- Claude's model list offers Fable 5.2 in place of Fable 5.1 and recommends Opus 5.5,
  which is also the default when `office.toml` names no Claude model. An office that
  set a model keeps it; one set to Fable 5.1 shows it under Other.
- Effort goes past High: Extra high (`xhigh`) and Max, for Claude and Codex, in the
  chat options, Settings > Engines and `fo config set serve.engines.<engine>.effort`.
- Engine, Model and Effort are dropdowns of one height, side by side in the chat
  options; Settings > Engines uses dropdowns for the default engine and effort too.
- The sidebar shows the app icon beside "Family Office", without the folder name.

## 2.0.0b3 — 2026-11-14

- The skills are written for conversation, so an advisor behaves the same in Claude
  Code or Codex opened on the office folder as in the app: it answers first from `fo`
  figures, asks back, and writes a report only when asked, when the analysis is worth
  keeping, or when invoked with a subject and no question. The shared rules in
  `AGENTS.md` gain "How an advisor works", "Web evidence" and "Reports"; the app's own
  prompt now carries only what is particular to its run. Run `fo skills sync` in an
  existing office (the Mac app does it itself).
- `fo skill verify` takes the report path as an argument, as the rules have always
  written it; `--path` still works.
- The app's build tooling pins minimatch to 11.x (GHSA-g3hv-75wg-m249). It is not in
  the shipped app.

## 2.0.0b2 — 2026-11-14

- Advisors are conversations. Each advisor page is a chat: type a message, press
  Enter, follow up as often as you like. The subject field is gone. Earlier chats are
  listed beside each advisor and on a new Chats page, and can be deleted. A chat
  writes a report only when asked or when the answer is worth keeping.
- Web search and fetch are on by default in every chat, including ones that read
  household data, with a switch beside the message box. `[serve] web` sets the
  policy: `on`, `isolated` (the previous rule: only where no household data is read),
  or `off`. The fetch cap now counts one reply. SECURITY.md describes the trade-off
  and the limits that apply.
- Onboarding happens in the app. The Onboard advisor interviews you in a chat and
  writes `profile/`, committing each change; Home lists it under Getting started.
  Setup steps offer buttons that open the Mac app's Connectors settings or setup
  dialog instead of terminal commands.
- Sync now, in the header and in setup steps, runs `fo sync` from the page.
- Several advisors can answer at once, each in its own conversation, up to
  `[serve] parallel_runs` (three by default). The sidebar shows which are answering
  and marks one that finished while you were reading another. Their `fo` commands
  wait for the office lock instead of failing.
- Accounts sync automatically while the app is open, when the data is more than
  `[serve] auto_sync_hours` old (six by default), on the writer host and never while
  an advisor is answering; `[serve] auto_sync = false` turns it off. A message sent
  during a sync is queued until it ends, and a sync from the app is recorded in the
  office's history.
- Settings > Advanced in the Mac app has the web access policy, automatic sync and
  its interval, and how many advisors answer at once.
- The app renders the office's skills itself when a new version changes them, so an
  update no longer leaves "Run fo skills sync" for a terminal.
- Pages remember their last figures, so switching Finances tabs, or returning to a
  page, no longer flashes a loading skeleton.
- `keep_runs` defaults to 300 for new offices.

## 2.0.0b1 — 2026-11-13

- The Mac app is Apple Silicon only. cryptography, a locked dependency of the bundled
  runtime, publishes no Intel macOS wheels, so the release builds one arm64 DMG and one
  appcast. `bundle-python.sh` refuses `FO_BUNDLE_ARCH=x86_64`.
- Release workflows pin every action by commit SHA, read signing secrets from the
  protected `release` environment only in the steps that use them, validate the tag before
  it reaches a build, and sign the Sparkle appcast in the build job so the job that writes
  the release holds no secret.
- Dependency updates for the bundled runtime: certifi 2026.10.23 (drops the distrusted
  emSign ECC Root CA - G3), joserfc 1.8.0 (CVE-2026-119284), authlib 1.9.5, urllib3 2.8.0
  and werkzeug 3.1.9. `pip-audit` reports no known vulnerabilities in the shipped set.
- `fo auth`, `fo setup`, `fo connect edgar` and `fo skills sync` commit the tracked
  files they write (`profile/accounts.json`, `office.toml`, `AGENTS.md`, `CLAUDE.md`),
  so they no longer block `fo commit` or the nightly sync. `fo doctor` warns with
  `office.uncommitted` when changes outside notebook/, reports/ and data/ would block it.
- Failed syncs retain institution error and unmapped account counts without error
  text. Institution failures point to provider repairs. SimpleFIN registration
  requires a new setup token. First-sync onboarding shows the repair before retrying.
- Offices ignore machine-specific `launchd/` files. `fo doctor --fix` adds the rule
  for existing offices and untracks old plists without deleting local files.
  Settings changes and credential repairs create local commits of managed files.
  Repeating `fo config set` or running `fo doctor --fix` recovers failed commits.
  Doctor warns about unrecorded ignore changes and tracked plists. Office commits
  handle an empty reports folder and refuse unfinished merges, rebases, and cherry-picks.
- A provider sync that returns accounts but matches none in the registry and has
  no institution errors now fails with `no_mapped_accounts`.
  It does not count as a completed sync for freshness or
  onboarding, and `fo doctor` shows `sync.unmapped.<provider>` with the fix:
  `fo auth <provider>`, then `fo sync`.
- Scheduling always includes `sync --commit --if-writer`; non-writer hosts skip
  cleanly. Changing `hosts.writer` reminds users to schedule the new host.
- Sync skips unmapped provider accounts and reports how many were skipped;
  `fo doctor` directs users to `fo auth <provider>` to register them.
  `fo config set` now accepts `hosts.writer` and `office.timezone`.
- `fo config set office.timezone` on an office with transactions now returns a note.
  Stored dates keep the old zone until a sync re-dates the last 30 days (90 with `--full`).
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
