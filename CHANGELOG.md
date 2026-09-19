# Changelog

## Unreleased

- Account `role` in the registry: allocation weights use investable assets, the
  cash band and `cash_months` count bank balances, and `fo doctor` flags accounts
  without a role.
- `fo spend` ignores trades, dividends, and funding transfers; refunds lower their
  category; income rules use `income: true`.
- `fo performance`: modified Dietz returns per investment account with dividends,
  fees, and an optional weekly benchmark. Realized gains stay unknown without lots.
- Schwab transactions keep symbol, quantity, price, fees, and kind; option prices
  are per share; transaction dates use the office timezone.
- An interrupted append is ignored on read and removed by the next write. One
  failing SimpleFIN institution no longer blocks the others.
- Long-term lots use the one-year anniversary. Skills have distinct descriptions.
- Faster large imports; CI enforces test coverage.

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
