# Family Office — development

This repository contains the public `family-office` Python package and `fo` CLI.
The private office lives outside this repository. Never read the real office or
copy its financial data into this checkout; development uses synthetic fixtures.

## Development

- Python 3.12 through uv. Run `uv sync` and `uv run pytest`.
- Run `uv run ruff check .` and `uv run ruff format --check .` before committing.
- Account providers are read-only; no order, trade, or money-movement operations.
- Secrets belong only in a private office's ignored secrets/ directory, at 0600
  inside a 0700 directory. Never print provider exceptions or raw credentials.
- Canonical derived files are append-only JSONL; SQLite is a disposable index.
- Test financial arithmetic, complete snapshots, identity changes, offline reads,
  interrupted writes, and privacy failures with synthetic data.
- Canonical skill bodies live in skills/. Both development discovery trees use
  relative symlinks. Package office rules live in src/fo/data/AGENTS.rules.md.
- Keep the product name family-office. Version numbers are release metadata.
- Use separate verified commits for implementation units. Preserve docs/plans/
  and historical references. Do not update the plan as a progress tracker.

## Tools

Run review and implementation work sequentially in the main task. Batch
independent tool reads where useful. Use fixtures, not real financial accounts,
for automated tests. The user owns credentials, live validation, and cutover.
