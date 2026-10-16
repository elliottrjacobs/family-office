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
The CLI creates the local registry and keeps Schwab account hashes in secrets,
so you normally do not need to look up IDs. Ambiguous matches stop for resolution;
you may still need to identify account owners or clarify account labels.
Credentials are stored only in the private office's Git-ignored `secrets/`
directory, with restrictive file permissions.

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
```

A run that recorded decisions but stopped before its report verified shows as
partial; Resume continues the same report. Onboarding stays an interview in the
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

Open the Tailnet link `fo serve` prints. With `allowed_logins`, a request without
one of those Tailscale identities is refused, on loopback too. Tailscale Funnel is
not supported, because it sends no identity. `--host` binds another address for a
proxy of your own and prints a warning; do not expose the server to a network you
do not control.

## Storage and migration

The public repository contains code and skills. The private office contains
profiles, append-only JSONL data, reports, and notebook events. SQLite indexes
can be rebuilt. Secrets, raw imports, caches, and medical documents are ignored
by Git. Missing lot dates or basis remain unknown.

New users start with an empty private office; no migration is needed. Setup does
not run `fo migrate-v1`. Keep your office folder outside this public checkout.

`fo migrate-v1` is an optional compatibility utility only for someone who already
has data in the supported legacy layout. It is not part of normal onboarding.

Scheduling prepares four launchd definitions without activating them. The agent
loads them after runtime verification and cutover approval. See
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
