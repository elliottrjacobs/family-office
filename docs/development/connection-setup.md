# Connection setup

The implementing agent owns setup, account discovery, configuration, sync, and
diagnostics. Elliott supplies only credentials and browser consent when needed.
Do not ask him to edit JSON, find provider account IDs, or run a test checklist.

Run from the development checkout, using a separate office outside this public
repository and outside iCloud:

```sh
uv run fo setup ~/family-office-smoke
```

The command initializes the office, reuses configured connections, authenticates
missing or expired connections, discovers accounts, saves safe registry entries,
syncs each connected provider, and runs diagnostics. Existing account names and
household metadata are preserved. Schwab account hashes remain in secrets only.
SimpleFIN account IDs are discovered directly; no manual mapping is required.

Use `--provider schwab` or `--provider simplefin` to connect one provider. If a
connection fails, inspect the safe reason code and rerun after resolving it;
successful connections are retained. Never request credentials in chat. Arrange
local credential entry or browser consent when the command requires it.

Development can continue without live credentials:

```sh
uv run fo setup /tmp/family-office-example --offline
```

Offline setup reports live validation as pending. A successful connected setup
reports `connection_checked`; it does not claim financial reconciliation or
release readiness. The agent still owns end-to-end validation before cutover.
The existing office remains operational until migration and reconciliation are
complete and Elliott elects to switch. No remote is configured by setup.
