# family-office

A private family office built around the `fo` command. Python computes the facts;
28 advisor skills interpret evidence and record decisions. Accounts are read-only.
This repository starts with fresh Git history. The original implementation and
its history are preserved in [family-office-v1-archive](https://github.com/elliottrjacobs/family-office-v1-archive),
at the `v1-archive` tag. The product remains **family-office**.

This is a prerelease. Automated checks use synthetic accounts. Live provider
reconciliation, native host acceptance, and the final cutover remain separate
acceptance gates; the existing office continues operating until they pass.

## Setup

Ask your agent to set up the office. It owns installation, account discovery,
configuration, synchronization, diagnostics, and reconciliation. You provide
credentials and browser consent, choose whether to use a private remote, and
approve the eventual cutover. You do not need to look up account IDs or edit JSON.

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

Research, diligence, and CIO support explicit `--deep` evidence work. The parent
prefetches inputs, five workers return bounded blocks, and the parent writes the
report. `fo report parts` identifies missing blocks for resumption. Workers have
no provider write operations; their instructions prohibit shell and file writes.
On a host without workers, the parent performs these steps sequentially.

Useful commands include `networth`, `positions`, `allocation`, `spend`, `cashflow`,
`goals`, `lots`, `quote`, `fundamentals`, `filings`, `macro`, and `screen`.
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

## Storage and migration

The public repository contains code and skills. The private office contains
profiles, append-only JSONL data, reports, and notebook events. SQLite indexes
can be rebuilt. Secrets, raw imports, caches, and medical documents are ignored
by Git. Missing lot dates or basis remain unknown.

The agent runs `fo migrate-v1 SOURCE --dry-run`, resolves mapping issues, compares
balances and counts, then applies migration to a fresh office. It never reads
legacy credential files or changes the source. `notebook/migration-report.md`
records ambiguities, and `notebook/legacy-context.md` preserves historical policy
context that needs reconciliation. An identical `--force` rerun is a no-op;
changed sources and populated destinations are refused to preserve new work.

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

The [implementation plan](docs/plans/2026-09-12-001-feat-family-office-plan.md)
records the contract. Real accounts are never test fixtures.
