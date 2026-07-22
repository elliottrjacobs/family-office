# Security & Privacy

## Data layout

All personal financial data lives in **gitignored** directories (`profile/`, `imports/`, `reports/`, `briefings/`, `journal/`, `memory/`, `medical/`) — only `.gitkeep` placeholders and the two generic templates (`profile/SOURCES.md`, `profile/api-guide.md`) are tracked. Secrets (`profile/api-keys.json`, `profile/.schwab-token.json`, `.env*`, `.mcp.json`) are gitignored as well. Before publishing a fork, run `git status` and `python3 scripts/consistency_check.py`.

## The genericity scrub-lint

`scripts/consistency_check.py` includes `check_genericity()`: a lint over **tracked files only** that fails if personal residue (account-number fragments, household facts, personal vendors) reappears. Generic patterns ship in the script; add your own household-specific patterns to the gitignored `profile/scrub-patterns.local.json` (a `{label: regex}` map) so the public lint never discloses anything about your household. Run it before every push.

## Trading safety

`scripts/schwab/client.py` is a whitelist proxy: order-placing methods raise `ReadOnlyClientError` before any HTTP call (see `scripts/schwab/test_read_only.py`). Understand its limits honestly: this is a **footgun-guard against accidental agent misuse, not a security boundary** — code that deliberately reaches the underlying client or imports `schwab` directly can bypass it. The real boundaries are your Schwab application's own scope and your Claude Code permission settings.

## History rewrite (2026-07-21)

The repository's git history was rewritten with `git filter-repo` on 2026-07-21 to remove personal residue that shipped in the original public release (holding tickers, partial account-number fragments, household details in prompt examples). All commit ids changed.

- **If you cloned or forked before 2026-07-21, delete and re-clone.** Old clones contain the pre-rewrite history and will conflict with the rewritten remote.
- Commit ids referenced in older discussions/issues refer to the pre-rewrite history and no longer resolve.
- Known residual: GitHub retains read-only `refs/pull/*` refs and cached commit views from before the rewrite until GitHub removes them (requested via GitHub Support's sensitive-data process).

## Reporting

If you find personal data, a secret, or a security issue in this repository, please open a GitHub issue with **no sensitive details** (or contact the maintainer via the email on the GitHub profile) and it will be addressed promptly.
