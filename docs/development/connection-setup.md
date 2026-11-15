# Connection setup

The implementing agent owns setup, account discovery, configuration, sync, and
diagnostics. The user supplies only credentials and browser consent when needed.
Do not ask the user to edit JSON, find provider account IDs, or run a test checklist.

Run from the development checkout, using a separate office outside this public
repository and outside iCloud:

```sh
uv run fo setup ~/family-office-smoke
```

The command initializes the office, reuses configured connections, authenticates
missing or expired connections, discovers accounts, saves safe registry entries,
syncs each connected provider, and runs diagnostics. Existing account names and
household metadata are preserved. Schwab account hashes remain only in the per-machine credentials folder outside the office.
SimpleFIN and Plaid account IDs are discovered directly; no manual mapping is required.
Plaid Item access tokens and transactions cursors remain only in `plaid-items.json` in
the per-machine credentials folder.

No provider is connected by default. In a terminal, setup asks which to connect
(`plaid`, `simplefin`, `schwab`, several, or `none`); ask the user, never pick for
them. Pass `--provider plaid`, `--provider simplefin` or `--provider schwab` to skip
the question; without a terminal and without `--provider`, setup connects nothing. If a
connection fails, inspect the safe reason code and rerun after resolving it;
successful connections are retained. Never request credentials in chat. Arrange
local credential entry or browser consent when the command requires it.

Development can continue without live credentials:

```sh
uv run fo setup /tmp/family-office-example --offline
```

Plaid can be exercised end to end in its Sandbox with your own Sandbox keys: answer
`sandbox` at the environment prompt, pick any institution in Plaid Link, and sign in
with Plaid's test user `user_good` / `pass_good`. Automated tests use a fake Plaid
API (`tests/test_plaid.py`) and never reach Plaid.

Offline setup reports live validation as pending. A successful connected setup
reports `connection_checked`; it does not claim financial reconciliation or
release readiness. The agent still owns end-to-end validation before cutover.
The existing office remains operational until migration and reconciliation are
complete and the user elects to switch. No remote is configured by setup.
