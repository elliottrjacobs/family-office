# Office layout and operations

An office is a separate private Git repository. Its `profile/` files contain
household identity, policies, categories, goals, account registry, and tax notes.
Only `fo sync` writes financial JSONL in `data/`. Notebook events record decisions
and reviews; correction retirement appends an event instead of deleting history.
Reports retain their original text. `store.sqlite` is a disposable projection;
`cache/cache.sqlite` holds expendable market responses and daily request budgets.

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

`fo schedule install` prepares launchd definitions in `launchd/`. It returns
argument arrays for loading them. Only the configured writer gets the 02:00 sync
job. Doctor runs at 07:30, review Sunday at 08:00, and report indexing at 03:00.
Sync also rebuilds the index before it completes. All four jobs invoke `fo`,
never a model host. Notifications contain generic status text rather than
financial values. Logs remain in ignored `cache/logs/`.

The agent validates each plist with `plutil -lint`, verifies the pinned office
runtime, loads the jobs only after cutover approval, and checks `launchctl list`
and the next scheduled sync log. These live checks have not been performed in
the development test suite. Two offices should not load identically named jobs
at once; archive the prior definitions during the approved cutover.

## A second machine or cloud task

The default office has no remote. If the user chooses a private GitHub remote,
the agent configures a repository-scoped deploy key under ignored `secrets/`
and a local `core.sshCommand`. Run a full Git history scan before the first push;
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
