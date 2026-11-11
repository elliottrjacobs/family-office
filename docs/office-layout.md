# Office layout and operations

An office is a separate private Git repository. Its `profile/` files contain
household identity, policies, categories, goals, account registry, and tax notes.
Only `fo sync` writes financial JSONL in `data/`. Notebook events record decisions
and reviews; correction retirement appends an event instead of deleting history.
Reports retain their original text. `store.sqlite` is a disposable projection;
`cache/cache.sqlite` holds expendable market responses and daily request budgets.

## Local credentials

The office may live in iCloud Drive or another synced folder. `office.toml`
contains a random `[office].id`, created by init or on first credential access
for older offices. It is shared across machines; credentials are not.

Credentials live outside the office in
`~/Library/Application Support/FamilyOffice/credentials/<office-id>/` on macOS,
or `${XDG_DATA_HOME:-~/.local/share}/family-office/credentials/<office-id>/` on
other systems. `FO_CREDENTIALS_HOME` overrides the base directory. The base and
office credential directories are 0700; `keys.toml`, `<provider>.json`,
`schwab-token.json`, and `devices.json` are 0600. Connect each machine separately.
This change uses files; macOS Keychain is possible future hardening.

Legacy `secrets/` files migrate on `fo doctor --fix`, `fo serve`, or a credential
command; read-only commands never migrate or write `office.toml`. Identical destination copies
allow removal of the office copy; differing copies remain for manual resolution
and `fo doctor` flags them. The empty legacy directory is removed. The office
still ignores and blocks `secrets/` in Git for defense in depth.
Credential repairs commit changes to `office.toml` and `.claude/settings.json`
locally. Only files changed by the repair are included.

## Account roles

Each entry in `profile/accounts.json` may carry a `role`: `investment`, `cash`,
`credit`, `loan`, `property`, or `other`. Without one, the role is inferred from
the free-text `type` (Schwab accounts default to `investment`). Allocation weights
divide by investable assets (investment and cash accounts), the cash band counts
bank balances plus brokerage cash, and `fo doctor` warns about accounts whose role
is unknown. `fo spend` ignores trades, dividends, and funding transfers, and a
refund lowers its category. Mark an income rule with `income: true` in
`profile/categories.yaml`.
Monthly cashflow includes `partial` for the current month and `uncategorized_inflow`
for excluded positive needs-review amounts, with `net` null while those amounts remain.

## Currency

Family Office assumes every account is in USD and does no currency conversion.
A balance's `currency` is recorded, and a net worth, allocation, cash, or goal
total shows unknown when an account it includes is not in USD. `fo spend` and monthly
cashflow do not check currency: transactions from a non-USD account are still
counted as USD. This is a known limitation, kept on purpose.

## Companion app settings

`fo serve` reads an optional `[serve]` table in `office.toml`: `port` (default
4790), `tailnet_name` (the name `tailscale serve` answers on, required for
`--remote`), `allowed_logins` (Tailscale logins allowed with `--remote`), and for
chat `max_budget_usd`, `run_timeout_minutes`, and `keep_runs`. The dashboard reads
profiles, reports, notebook events, and canonical data in read-only mode. Writes
from the page go through `fo journal` and `fo corrections`. Advisor runs write
reports under `reports/` and notebook events through `fo`, and keep their records
and event logs in the ignored `cache/serve/runs/`, which is disposable; durable
results stay in `reports/` and `notebook/`.

## Agent-owned setup and cutover

The agent runs setup and diagnostics, handles account discovery, and reconciles
the migration preview against the live provider snapshots. Credential entry and
browser consent remain with the user. Neither a successful synthetic migration
nor a healthy empty scaffold proves live reconciliation.

The source office stays operational until the agent has reconciled balances,
account coverage, transaction identities, report counts, and notebook status,
and the user approves switching. Legacy policy wording that lacks an exact new
schema mapping is preserved in the migration's historical context notes. The
agent resolves those mappings before calling the new IPS operational.

The rollback is to keep operating the unchanged source. If new work exists in
the destination, preserve it before retiring that destination. Never delete the
source, rotate its credentials, or unload its jobs as a side effect of migration.

## Scheduled operations

`fo schedule install` prepares launchd definitions in `launchd/` and returns
argument arrays for loading them. The files contain machine-specific absolute
paths and are ignored by Git. `fo doctor` warns if the ignore rule is missing.
`fo doctor --fix` adds and commits it locally. Every host gets the 02:00
`sync --commit --if-writer` job. It checks `hosts.writer` each time and exits
successfully on other hosts without syncing, writing a sync log, or notifying.
Manual `fo sync` without `--if-writer` still refuses a non-writer host.
Doctor runs at 07:30, review Sunday at 08:00, and report indexing at 03:00.
Sync also rebuilds the index before it completes. All four jobs invoke `fo`,
never a model host. Notifications contain generic status text rather than
financial values. Logs remain in ignored `cache/logs/`.

When moving the writer with `fo config set hosts.writer example-mac.local`, run
`fo schedule install` on that machine if it has not been scheduled there, then
load the returned jobs as described below. The old host's sync job now skips.
`fo config set` commits its `office.toml` change locally without committing other
dirty or staged files. These managed writes keep `fo commit` and nightly syncs
from being blocked by their own settings changes.
For existing installations, regenerate and reload the definitions to pick up
`--if-writer` before moving the writer.

The agent validates each plist with `plutil -lint`, verifies the pinned office
runtime, loads the jobs only after cutover approval, and checks `launchctl list`
and the next scheduled sync log. These live checks have not been performed in
the development test suite. Two offices should not load identically named jobs
at once; archive the prior definitions during the approved cutover.

## A second machine or cloud task

The default office has no remote. If the user chooses a private GitHub remote,
the agent configures a repository-scoped deploy key in the per-machine credentials
folder outside the office and a local `core.sshCommand`. Run a full Git history scan before the first push;
`fo commit` requires gitleaks for publication and scans again after rebasing.
Do not disable the scanner when it blocks a push. No force-push is automated.

Clone only the private office into the second machine or cloud environment.
Its setup command is `uv sync`; the office dependency must identify an available,
verified package revision. Local hosts run `fo skills sync`. In cloud tasks,
`fo skill NAME` works without generated discovery files. Cloud environments hold
the entire tracked checkout, including household notes and financial records.
They receive no secrets. Market commands return cached values if a cache has
been separately provisioned, otherwise a data gap; caches are not Git-tracked.

A read-only task runs `fo --read-only …`. Account computations never contact a
provider. Only the writer can sync. An authorized report-producing task writes
reports and notebook events and runs `fo commit` to rebase and publish them.
A rebase conflict stops publication and preserves local commits for resolution.
Changes to authored profiles must be committed separately before `fo commit`.
