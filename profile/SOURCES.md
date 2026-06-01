# Source of Truth Registry

This file records **which file is canonical for each fact** in the profile. Every agent must consult it before writing data, and re-read the canonical file before quoting a number in a report.

> Generic template. The files below are created/updated by `/onboard` and `/sync`; this registry tells agents which ones to trust and which ones are derived.

## The two tiers

- **Tier 1 — Authored.** Identity, policy, intent. The listed file *is* the truth. Edit it by hand (or via `/onboard`) when the underlying fact changes. Examples: who's in the household, the IPS, goals, risk tolerance.
- **Tier 2 — Derived / live.** Computed from your brokerage or filed returns. **Written only by automated writers** (`/sync` for holdings/balances; the filed return for income/tax actuals). Never hand-edit these.

## Non-negotiable rules

1. **Reference, don't copy.** Never embed a live dollar figure or weight (portfolio value, position $/%, balances) into a Tier-1 / narrative file as a permanent literal. If you must mention one, tag it `as_of: YYYY-MM-DD` and say "recompute from `profile/portfolio/holdings.json`." Stale copies are the #1 source of bad advice.
2. **One writer per fact.** Each Tier-2 fact has exactly one writer. Live financials → `/sync` (`scripts/schwab/sync.py --apply`). Income/tax actuals → the filed return. Never hand-edit `holdings.json`, `holdings.csv`, `accounts/*.json`, or `crypto.json`.
3. **Re-read at report time.** Before writing any report, re-read `profile/portfolio/holdings.json` for live numbers rather than trusting figures from earlier in the conversation — they may be stale mid-session.
4. **Never read the dry-run preview as canonical.** `holdings.live.json` is sync's preview; `holdings.csv` is a convenience export. Only `holdings.json` is canonical.

## Registry

| Fact | Canonical file | Tier | Writer |
|------|----------------|------|--------|
| Household members, dependents, employment | `profile/family.json` | 1 (authored) | hand / `/onboard` |
| Goals | `profile/goals.json` | 1 (authored) | hand / `/onboard` |
| Risk tolerance | `profile/risk-tolerance.json` | 1 (authored) | hand / `/onboard` |
| Investment Policy Statement (IPS) | `profile/investment-policy.json` | 1 (authored) | hand / `/onboard` |
| Business entities / overview / tax setup | `profile/business/*.json` | 1 (authored) | hand / `/onboard` |
| Insurance policies | `profile/insurance/*.json` | 1 (authored) | hand / `/onboard` |
| Real estate (residence, investment properties) | `profile/real-estate/*.json` | 1 (authored) | hand / `/onboard` |
| Tax elections / strategies in place | `profile/tax/*.json` | 1 (authored) | hand / `/onboard` |
| Watchlist | `profile/portfolio/watchlist.json` | 1 (authored) | hand |
| **Holdings, position $/%, portfolio value** | `profile/portfolio/holdings.json` | **2 (live)** | **`/sync` only** |
| Holdings convenience export | `profile/portfolio/holdings.csv` | 2 (derived) | `/sync` only |
| Account balances (brokerage, retirement, cash, crypto) | `profile/accounts/*.json` | 2 (live) | `/sync` only |
| Crypto balances | `profile/accounts/crypto.json` | 2 (live) | `/sync` only |
| Data freshness timestamps | `memory/data-freshness.json` | 2 (derived) | `/sync` only |
| Income actuals (W-2, 1099, other) | `profile/income/*.json` | 2 (derived) | filed return / `/onboard` |
| Debt balances | `profile/debts/*.json` | 2 (live) | statements via `/sync` / hand |
| **Bank/card transactions** | `profile/transactions/<slug>/<year>.json` (accumulating); derived: `<slug>/rollups.json` + `index.json` | 2 (live) | `scripts/simplefin/sync.py` (sync-owned) |
| Bank/card balances | `profile/accounts/*` + `profile/debts/credit-cards.json` | 2 (live) | `scripts/simplefin/sync.py` |
| **Expense categories / budget rules** | `profile/expenses/categories.json` | **1 (authored)** | hand |
| Budget rollup (categorized) | `profile/expenses/budget-data.json` + `summary.json` | 2 (derived) | `scripts/expenses/categorize.py` |
| Budget dashboard | `reports/budget-dashboard.html` | 2 (derived) | `scripts/expenses/build_dashboard.py` |

## Drift lint

`scripts/consistency_check.py` enforces this registry. It treats `profile/portfolio/holdings.json` as canonical, verifies the derived files agree with it, and fails if any retired stale value reappears. Run it after every `/sync` and weekly alongside the Schwab re-auth:

```bash
python3.10 scripts/consistency_check.py
```

When you retire a stale value, add it to the `STALE_BLOCKLIST` in that script as a regex so a future `/sync` or hand-edit can't silently reintroduce it. Never resolve drift by editing the lint to ignore it — fix the offending file instead (live financials → re-run `sync.py --apply`; authored files → correct by hand per this registry).
