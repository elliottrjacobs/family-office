# family-office

A private family office built around the `fo` command. Python computes the facts;
28 advisor skills interpret evidence and record decisions. Accounts are read-only.
`fo` (short for “family office”) is the command-line tool installed by this
package. For example, `fo positions` shows holdings and `fo networth` calculates
net worth. Your coding agent uses these same commands to retrieve facts.

This is an alpha prerelease (`2.0.0a1`). Automated tests use synthetic accounts;
end-to-end live account reconciliation and scheduled operation have not yet been
validated. Check imported balances and holdings against your institution before
relying on the results.

## Setup

Ask your coding agent to install the package and set up a separate private office.
It handles configuration, account discovery, synchronization, and diagnostics.
You enter credentials locally and approve the provider's authorization screen.
Never paste passwords, API secrets, or tokens into an agent chat or this public
repository. A private Git remote is optional; setup does not create one.

### Connections and credentials

- **Schwab:** the current direct brokerage integration requires your developer
  application's app key, app secret, and registered callback URL. Setup prompts
  for the key and secret with hidden terminal input. It opens the browser so you
  can sign in directly to Schwab and authorize account access. The local callback
  receives the authorization result and saves tokens; you do not give your
  brokerage password to the agent. An approved developer application is a
  prerequisite that setup cannot create for you.
- **SimpleFIN:** connect your institutions through SimpleFIN, then enter its setup
  token at the hidden local prompt. The CLI exchanges it for an access credential.
  Institution coverage and available data depend on the connection.
- **Other brokerages:** the calculations and advisor skills use normalized account
  data, but direct authentication and synchronization currently support Schwab
  only. Fidelity or another brokerage requires a new read-only adapter if it
  offers an accessible developer API; changing a broker name or API key is not
  enough. Supported CSV imports are another path; other export formats need mapping.

Choose `--provider schwab` or `--provider simplefin` to connect only that provider;
without this option, setup attempts both. Use `--offline` to prepare an office
without either connection. Optional market-data API keys are separate from
brokerage credentials.

After authorization, supported providers return account identifiers automatically.
The CLI creates the local registry and keeps Schwab account hashes in local
credentials, so you normally do not need to look up IDs. Ambiguous matches stop for resolution;
you may still need to identify account owners or clarify account labels.
If a sync returns no registered account, `fo doctor` and onboarding show the repair
before retrying. Institution errors require repairing the connection at the provider.
Without institution errors, register the returned accounts with `fo auth <provider>`.
For SimpleFIN, get a new setup token first, then run `fo auth simplefin`.
The office may live in iCloud Drive or another synced folder. Credentials stay in
an outside, per-machine folder keyed by `[office].id` in `office.toml`: on macOS,
`~/Library/Application Support/FamilyOffice/credentials/<office-id>/`; elsewhere,
`${XDG_DATA_HOME:-~/.local/share}/family-office/credentials/<office-id>/`.
`FO_CREDENTIALS_HOME` overrides the base directory. Directories are 0700 and files
0600. Each machine connects separately. Legacy `secrets/` files migrate once when
`fo doctor --fix`, `fo serve`, or a credential command runs; reads never migrate.
Differing local copies are retained and flagged by `fo doctor`; iCloud `.icloud`
placeholders are skipped until downloaded.
macOS Keychain storage is possible future hardening; it is not used here.

### No trade execution

The CLI and provider adapters expose account and market-data reads only: no
placing, changing, or canceling orders, and no transfers or money movement.
Recommendations remain decisions for you to execute separately. This is an
application boundary, not a guarantee that the broker-issued token cannot trade.
Use provider-enforced read-only access where available. If you require a strict
no-trading credential boundary and the provider cannot supply one, use offline
imports without connecting brokerage credentials. See [SECURITY.md](SECURITY.md).

The development checkout runs with Python 3.12 and [uv](https://docs.astral.sh/uv/):

```sh
uv sync --locked
uv run fo setup ~/office
```

`setup` creates a separate private repository, reuses valid credentials, connects
Schwab and SimpleFIN, discovers accounts, syncs them, and runs diagnostics. To
prepare an unconnected office, the agent uses `fo setup ~/office --offline`.
Provider availability and consent determine connection time; no live timing claim
has been verified. Market keys are optional. SEC requests require a configured
identifying User-Agent in `office.toml`; the agent configures it from the user's
contact information. The agent must not invent a contact address.

The packaged prerelease is installed with
`uv tool install "family-office @ git+https://github.com/elliottrjacobs/family-office.git@v2.0.0a1"`.
New offices pin that same package version. Version numbers identify releases;
the installed command and product name remain `fo` and family-office.

An installed package can be run as `fo`; from this checkout use `uv run fo`.
Use `--office PATH` from anywhere. `--json` is the machine interface, `--full`
expands compute results, and `--read-only` prevents writes and market requests.

## Use

Claude Code invokes `/research ACME`; Codex invokes `$research ACME`.
Both start from the private office. Where skill discovery is unavailable,
`fo skill research` prints the instructions. Codex main-session skills inherit
the session model; worker models and Claude skill tiers come from `office.toml`.

| Area | Skills |
|---|---|
| Research | `research` — business and valuation; `diligence` — management; `scout` — candidates; `macro` — economic conditions |
| Household | `cio` — investment policy; `cfo` — cash flow; `plan` — goals; `tax` — tax scenarios |
| Routine | `journal` — decision record; `briefing` — cached briefing; `review` — thesis review; `onboard` — guided setup; `eli5` — plain-language explanation |
| Specialists | `options`, `technicals`, `risk`, `realestate`, `ventures`, `estate` |
| Playbooks | `lead-edge-eight`, `piotroski`, `greenblatt`, `compounder`, `lynch`, `fisher`, `powers`, `marks`, `all-weather` |

Each skill declares its area as `metadata.group`; `fo skills list --json` prints the
registry with tiers, context levels, and commands.

Research, diligence, and CIO support explicit `--deep` evidence work. The parent
prefetches inputs, five workers return bounded blocks, and the parent writes the
report. `fo report parts` identifies missing blocks for resumption. Workers have
no provider write operations; their instructions prohibit shell and file writes.
On a host without workers, the parent performs these steps sequentially.

Useful commands include `networth`, `positions`, `allocation`, `spend`, `cashflow`,
`goals`, `lots`, `performance`, `quote`, `fundamentals`, `filings`, `macro`, and `screen`.
`fo --help` and each command's `--help` document arguments.

### Research providers

`fo research search`, `fo research fetch`, and `fo research deep` reach Exa,
Firecrawl (or a direct fetch), and Gemini Deep Research. Store a key with
`fo connect exa` (the key is read from standard input), remove it with
`fo connect exa --remove`, and set the SEC contact with
`fo connect edgar --user-agent "Name email@example.com"`. Results are marked
untrusted, scrubbed, cached under `cache/research/`, and limited per day:

```toml
[providers.exa]
daily_limit = 25

[providers.firecrawl]
daily_limit = 25

[providers.gemini]
max_tasks_per_day = 3
```

Fetches refuse local, private, and tailnet addresses. See
[research providers](docs/development/research-providers.md).

Reports have dated paths, frontmatter, prior-report links, decision IDs, and a
correction invitation. `fo start` supplies context and a path; `fo skill verify`
checks the result. `fo journal add` records a thesis and invalidation. `fo review`
evaluates supported conditions using local facts and cached market observations;
missing evidence requests judgment. It does not fetch quotes or make trades.

Playbooks distinguish mechanical facts from judgment and never generate a
mechanical investment verdict. Library thresholds are editable through private
`playbooks/overrides/` files. Greenblatt's capital-return measure uses operating
income divided by net working capital plus net fixed assets; it is not a generic
company-reported ROIC or a complete ranked Magic Formula portfolio.

## Mac app

The Family Office Mac app wraps everything below in one window: the dashboard, the
advisors, and a terminal for `fo`, with no Python or Node to install. Download the
latest `.dmg` from the GitHub Releases page, drag the app to Applications, and open
it. A setup dialog walks you through choosing or creating your office folder, picking
an engine, and connecting accounts; credentials and provider consent stay in the
terminal pane. New versions arrive as new signed releases.

It needs macOS 14 or later, and Claude Code or Codex installed and signed in
(Codex ships disabled until you turn it on in Settings). Advisor runs go through
your own account with that tool and are billed there; the app has no account or
subscription of its own.

Your office stays on the Mac, and nothing phones home: no telemetry and no analytics.
The iPhone app reaches the Mac only over your own tailnet, after a one-time pairing
with a code shown in the Mac app's Settings > Devices; see
[Reach it from your phone](#reach-it-from-your-phone). To build the apps from
source, see [docs/development/apple.md](docs/development/apple.md).

## Companion app (optional)

`fo serve` opens a dashboard for your office in a browser on the same machine:
Home, Finances, Reports, Decisions, Profile, and the advisor directory. It needs
no extra install, no Node, and nothing running in the background.

```sh
fo serve --office ~/family-office --open
```

The server listens on 127.0.0.1:4790 (`--port`, or `port` under `[serve]` in
`office.toml`) and prints a link carrying a one-time token. Opening the link signs
that browser in until the server stops; press Enter to print it again and Ctrl-C
to stop. Every start issues a new link. Run it before an office exists and the
page walks you through `fo setup`, connecting accounts, and the first sync, one
exact command at a time. Credentials and provider consent stay in the terminal.

The dashboard reads the office in read-only mode: no provider calls, no cache or
index writes, and no lock. It reads only `profile/`, `reports/`, `notebook/`, and
the canonical data files, never `secrets/`, `imports/`, `cache/`, or `medical/`.
Verdicts, new decisions, and corrections can be recorded from the Decisions page;
each asks first, names its undo, and runs the matching `fo journal` or
`fo corrections` command. `fo serve --read-only` leaves out chat and every write.

### Chat with an advisor

Each advisor page can start that skill on a subject and stream its work: commands
it ran, its answer, decisions it recorded, and the verified report. Chat runs
Claude Code on this machine, so install it and sign in once in a terminal. A run
reads at the context level you pick (the page shows what that includes first),
loads only the office's settings, and may run only `fo` commands, read inside the
office, and write under `reports/`; a refused call is listed in the run, never
asked about. Runs are capped in `office.toml`:

```toml
[serve]
max_budget_usd = 2.0       # per run, in Claude usage
run_timeout_minutes = 30
keep_runs = 50             # run logs kept under cache/serve/runs/
web_fetch_cap = 20         # web fetches per run at level none
```

Web search and fetch follow the context level. At level `none`, where a run reads
no household data, the advisor may search the web and fetch pages; at `household`
and `full` both are off, and the launch panel says which applies before you start.
Every fetch is checked against the same deny list as `fo research fetch` (nothing
on this machine, the local network, or the tailnet, and no URL carrying a password),
fetches stop at `web_fetch_cap`, and the run view lists the sites visited, searches
by query and fetches by host with the full URL on hover. See
[SECURITY.md](SECURITY.md) for what this exposes.

Each run goes to an engine: Claude Code (the default and the recommended one) or
Codex. The
launch panel lists the engines `fo serve` can run, with one that is missing,
outdated, or turned off shown disabled and the reason beside it. Model and effort are
chosen per run: the panel offers a curated list of model ids for the engine
(shipped in the package, so it can change in a patch release), an Other field
for any id the engine accepts, and an effort of low, medium, or high. A model
fo does not list is passed through as is; an id the engine rejects fails the
run with the engine's message. The panel starts from the office's defaults and
remembers your last choice per advisor for the browser session, and the run
view names the engine and model it used. The defaults live in `office.toml`,
set through `fo config set` (below), and a change shows on the next request
without restarting `fo serve`:

```toml
[serve.engines]
default = "claude"         # the engine a run uses when the launch names none

[serve.engines.claude]
model = "claude-fable-5-1"  # the curated recommendation when unset
effort = "high"            # low, medium, or high
max_budget_usd = 2.0       # per run on this engine; [serve] max_budget_usd when unset
enabled = true             # false turns the engine off for chat
```

Codex needs the Codex CLI installed and signed in once in a terminal (`codex login`;
the server links each run to that sign-in and never copies it). If `fo serve` cannot
find `codex` on its `PATH`, set `FO_CODEX_EXECUTABLE` to its full path. It is off by
default: Codex confines reads by refusing a list of commands rather than by path, so a
command the list misses could print a file such as one in the credentials folder (see
[SECURITY.md](SECURITY.md)). Turn it on with `fo config set serve.engines.codex.enabled
true` if you accept that. What differs from Claude Code: each run has its own scratch
workspace in its run folder, where the advisor drafts the report before writing it
with `fo report write --body-file`; web search at level `none` comes from Codex's own
search (page fetches go through `fo research fetch`); there is no budget cap, only
`run_timeout_minutes`; there is no deep mode; and runs show no streamed text, only each
finished message.

A run that recorded decisions but stopped before its report verified shows as
partial; Resume continues the same report. Stopping `fo serve` stops a run in
progress and keeps what it recorded. Onboarding stays an interview in the
terminal, and the journal skill is replaced by the record-decision form.

### Reach it from your phone

Run it on a machine in your tailnet and let Tailscale proxy it. In `office.toml`:

```toml
[serve]
tailnet_name = "machine.your-tailnet.ts.net"
allowed_logins = ["you@example.com"]
```

```sh
fo serve --remote
tailscale serve --bg 4790
```

Open the Tailnet link `fo serve` prints. With `allowed_logins`, a request over the
tailnet without one of those Tailscale identities is refused; on loopback the
launch cookie alone still works, because any local process could forge the header
there. Tailscale Funnel is
not supported, because it sends no identity. `--host` binds another address for a
proxy of your own and prints a warning; do not expose the server to a network you
do not control.

The Family Office iPhone app pairs once by scanning the code in the Mac app's
Settings > Devices, keeps a revocable device token in the Keychain, and shows this
same web app over the tailnet. Building and trying it on a simulator is covered in
[docs/development/apple.md](docs/development/apple.md#iphone-app).

### For the Mac app

`fo serve --app` prints one JSON line on stdout before the usual lines, then runs
exactly like `fo serve` without the press-Enter reprint:

```json
{"port": 4790, "token": "…", "office": "/path/to/office", "state": "ready", "version": "…"}
```

`office` is null and `state` names the onboarding step when no office exists yet.
The app reads that line, ignores the rest of stdout, and opens the landing link so
the cookie is set the normal way. With `--remote`, a phone pairs once over the
tailnet with a five-minute code from the Mac and then holds a revocable device
token; see [SECURITY.md](SECURITY.md).

### Writing reports and settings through `fo`

`fo report write` reads a report body on stdin and writes it at the path `fo start`
returned (`--report PATH`), or allocates one from `--kind` and `--subject` the way
`fo report path` does; `--part NAME` writes `NAME.md` in the report's part
directory instead. It writes only under `reports/`, never into a dotted directory
or file there, caps the body at 2 MB (`max_body_bytes` under `[reports]`), writes
through a temp file and rename, and prints the path and byte count. Skills and
advisor runs use it in place of a file-writing tool. `--body-file PATH` reads the
body from a file instead of stdin, under the same cap, for headless runs that cannot
pipe: the file must resolve under `reports/` or a run's scratch workspace,
`cache/serve/runs/<id>/workspace/`, or the command refuses it (`unsafe_path`).

`fo config set KEY VALUE` changes one setting in `office.toml` under the office
lock, keeps every other line and comment as it was, and refuses anything outside
this list with `invalid_key`, or a value of the wrong type with `invalid_value`:
`hosts.writer` (the writer hostname), `office.timezone` (an IANA timezone key),
`serve.port` (1 to 65535, not 8182), `serve.tailnet_name`, `serve.allowed_logins`
(a JSON array or comma-separated), `serve.web_fetch_cap`, `serve.max_budget_usd`,
`serve.run_timeout_minutes`, `serve.keep_runs`, `serve.engines.default`
(`claude` or `codex`), and for each engine `serve.engines.<claude|codex>.model`,
`.effort` (`low`, `medium`, `high`), `.max_budget_usd`, and `.enabled`; then
`providers.<name>.daily_limit` for `alphavantage`, `fred`, `edgar`, `exa`,
`firecrawl`, and `gemini`, `providers.gemini.max_tasks_per_day`, and
`providers.edgar.user_agent`. `fo config get KEY` prints one of them as JSON.
Advisor runs cannot change settings.
Changed settings are committed locally in `office.toml`. Unrelated dirty or staged
files stay outside that commit. Credential repairs also record their settings changes.

After changing `hosts.writer`, run `fo schedule install` on the new writer if it
has not been scheduled there. Scheduled syncs on the old host skip once their
job uses `--if-writer`; manual `fo sync` still requires the writer host.

## Storage and migration

The public repository contains code and skills. The private office contains
profiles, append-only JSONL data, reports, and notebook events. SQLite indexes
can be rebuilt. Secrets, raw imports, caches, and medical documents are ignored
by Git. Missing lot dates or basis remain unknown.

New users start with an empty private office; no migration is needed. Setup does
not run `fo migrate-v1`. Keep your office folder outside this public checkout.

`fo migrate-v1` is an optional compatibility utility only for someone who already
has data in the supported legacy layout. It is not part of normal onboarding.

`fo schedule install` prepares four launchd definitions on every host without
activating them, including a 02:00 `fo sync --commit --if-writer` job. That sync
skips cleanly on hosts other than `hosts.writer`, without writing a sync log.
The machine-specific files in `launchd/` are ignored by Git. For an older office,
`fo doctor --fix` adds and commits the ignore rule.
Regenerate and reload existing definitions to pick up `--if-writer`. The agent
loads the jobs after runtime verification and cutover approval. See
[office layout and operations](docs/office-layout.md) and the
[system explainer](docs/explainers/family-office-system.html).

## Privacy and development

Office content read by an advisor may go to its model provider. A configured
private Git remote receives tracked office data. A cloud agent receives the
entire checkout. Market providers receive requested tickers or series.
See [SECURITY.md](SECURITY.md) for the actual trust boundaries.

```sh
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run python scripts/lint_skills.py
uv run python scripts/lint_office_paths.py
uv build
```

The companion app's frontend lives in `app/`; [its README](app/README.md) covers
rebuilding the committed bundle with Node. CI fails if the bundle and source differ.

The [implementation plan](docs/plans/2026-09-12-001-feat-family-office-plan.md)
records the contract. Real accounts are never test fixtures.
