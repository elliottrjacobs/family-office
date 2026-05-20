#!/usr/bin/env python3.10
"""
Schwab live sync — fetches positions from all configured accounts and rebuilds
profile/portfolio/holdings.json in the existing schema.

Usage:
  python3.10 scripts/schwab/sync.py            # dry-run: writes holdings.live.json + prints diff
  python3.10 scripts/schwab/sync.py --apply    # writes to holdings.json (overwrites)

Always writes:
  profile/portfolio/_probe/accounts_with_positions.json  (raw snapshot for audit)

Updates on --apply (all derived/live data — never hand-edit these):
  profile/portfolio/holdings.json   (canonical)
  profile/portfolio/holdings.csv
  profile/accounts/brokerage.json, retirement.json, accounts.json
  profile/accounts/crypto.json      (TICKER2 exposure)
  memory/data-freshness.json        (api_sources.schwab + key_metrics)
"""
import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from client import get_read_only_client

ROOT = Path(__file__).resolve().parents[2]
HOLDINGS_PATH = ROOT / "profile" / "portfolio" / "holdings.json"
HOLDINGS_CSV_PATH = ROOT / "profile" / "portfolio" / "holdings.csv"
HOLDINGS_LIVE_PATH = ROOT / "profile" / "portfolio" / "holdings.live.json"
PROBE_DIR = ROOT / "profile" / "portfolio" / "_probe"
FRESHNESS_PATH = ROOT / "memory" / "data-freshness.json"
KEYS_PATH = ROOT / "profile" / "api-keys.json"
BROKERAGE_PATH = ROOT / "profile" / "accounts" / "brokerage.json"
RETIREMENT_PATH = ROOT / "profile" / "accounts" / "retirement.json"
ACCOUNTS_PATH = ROOT / "profile" / "accounts" / "accounts.json"
CRYPTO_PATH = ROOT / "profile" / "accounts" / "crypto.json"
MEMORY_INDEX_PATH = ROOT / "memory" / "MEMORY.md"

CRYPTO_ACCT_LABELS = {
    "individual_brokerage_bbb": "Individual (...bbb)",
    "roth_ira_ccc": "Roth IRA (...ccc)",
    "custodial_ddd": "Custodial (...ddd)",
    "joint_brokerage_aaa": "Joint (...aaa)",
}

SCHWAB_LAST4 = {"aaa", "bbb", "ccc", "ddd"}
TAXABLE_SLOTS = {"joint_brokerage_aaa", "individual_brokerage_bbb"}
RETIREMENT_SLOTS = {"roth_ira_ccc"}
SLOT_LAST4 = {
    "joint_brokerage_aaa": "aaa",
    "individual_brokerage_bbb": "bbb",
    "roth_ira_ccc": "ccc",
    "custodial_ddd": "ddd",
}


SUFFIX_TO_SLOT = {
    "aaa": ("joint_brokerage_aaa", "Joint Tenant Brokerage ...aaa"),
    "bbb": ("individual_brokerage_bbb", "Individual Brokerage ...bbb"),
    "ccc": ("roth_ira_ccc", "Roth IRA ...ccc"),
    "ddd": ("custodial_ddd", "Custodial UTMA ...ddd"),
}

MONEY_MARKET_SYMBOLS = {"SWVXX", "SNAXX", "SNVXX", "SNSXX"}


def classify_type(symbol, asset_type, description):
    if symbol in MONEY_MARKET_SYMBOLS:
        return "money_market"
    if asset_type == "EQUITY":
        return "equity"
    if asset_type in ("ETF", "COLLECTIVE_INVESTMENT"):
        return "etf"
    if asset_type == "MUTUAL_FUND":
        if "MONEY" in (description or "").upper():
            return "money_market"
        return "mutual_fund"
    if asset_type == "OPTION":
        return "option"
    if asset_type in ("CASH_EQUIVALENT", "CASH"):
        return "cash"
    return (asset_type or "unknown").lower()


def match_slot(account_number):
    for suffix, (slot, name) in SUFFIX_TO_SLOT.items():
        if account_number.endswith(suffix):
            return slot, name
    return None, None


def transform_position(pos, account_market_value):
    inst = pos.get("instrument") or {}
    sym = inst.get("symbol", "")
    shares = pos.get("longQuantity", 0) or 0
    mv = pos.get("marketValue", 0) or 0
    avg_price = pos.get("averageLongPrice") or pos.get("averagePrice") or 0
    cost_basis_total = round(avg_price * shares, 2) if shares else 0
    open_pnl = pos.get("longOpenProfitLoss")
    gain_pct = None
    if cost_basis_total and shares:
        gain_pct = round((mv - cost_basis_total) / cost_basis_total * 100, 2) if cost_basis_total else None
    price = round(mv / shares, 4) if shares else None
    pct = round(mv / account_market_value * 100, 2) if account_market_value else 0
    return {
        "symbol": sym,
        "name": inst.get("description") or sym,
        "shares": shares,
        "price": price,
        "market_value": round(mv, 2),
        "cost_basis": round(avg_price, 4) if avg_price else None,
        "cost_basis_total": cost_basis_total,
        "open_pnl": round(open_pnl, 2) if open_pnl is not None else None,
        "gain_pct": gain_pct,
        "pct_of_account": pct,
        "type": classify_type(sym, inst.get("assetType"), inst.get("description")),
        "cusip": inst.get("cusip"),
        "asset_type_raw": inst.get("assetType"),
    }


def build_holdings(accounts_resp, now_iso):
    accounts_out = {}
    total = 0
    all_positions = []

    for entry in accounts_resp:
        sa = entry.get("securitiesAccount", {})
        acct_num = sa.get("accountNumber", "")
        slot, name = match_slot(acct_num)
        if not slot:
            continue
        bal = sa.get("currentBalances", {}) or {}
        mv = bal.get("liquidationValue") or 0
        cash = bal.get("cashBalance") or 0

        positions = []
        for pos in sa.get("positions", []):
            positions.append(transform_position(pos, mv))

        if cash > 0:
            positions.append({
                "symbol": "CASH",
                "name": "Cash & Cash Investments",
                "shares": None,
                "price": None,
                "market_value": round(cash, 2),
                "cost_basis": None,
                "cost_basis_total": None,
                "open_pnl": None,
                "gain_pct": None,
                "pct_of_account": round(cash / mv * 100, 2) if mv else 0,
                "type": "cash",
                "cusip": None,
                "asset_type_raw": "CASH",
            })

        positions.sort(key=lambda p: p["market_value"], reverse=True)
        accounts_out[slot] = {
            "name": name,
            "account_number_last4": acct_num[-4:],
            "account_type": sa.get("type"),
            "market_value": round(mv, 2),
            "cash_balance": round(cash, 2),
            "holdings": positions,
        }
        total += mv
        for p in positions:
            all_positions.append({**p, "_slot": slot})

    # portfolio_summary
    summary = {
        "total_equities": round(sum(p["market_value"] for p in all_positions if p["type"] == "equity"), 2),
        "total_etfs_funds": round(sum(p["market_value"] for p in all_positions if p["type"] in ("etf", "mutual_fund")), 2),
        "total_cash_money_market": round(sum(p["market_value"] for p in all_positions if p["type"] in ("cash", "money_market")), 2),
        "total_bitcoin_exposure_ibit": round(sum(p["market_value"] for p in all_positions if p["symbol"] == "TICKER2"), 2),
    }
    summary["bitcoin_pct_of_portfolio"] = round(summary["total_bitcoin_exposure_ibit"] / total * 100, 2) if total else 0

    # aggregate same-symbol across accounts for top5
    by_sym = {}
    for p in all_positions:
        s = p["symbol"]
        by_sym[s] = by_sym.get(s, 0) + p["market_value"]
    top5 = sorted(by_sym.items(), key=lambda x: x[1], reverse=True)[:5]
    summary["top_5_positions"] = [
        {"symbol": s, "value": round(v, 2), "pct": round(v / total * 100, 2)}
        for s, v in top5
    ]

    return {
        "last_updated": now_iso[:10],
        "data_as_of": now_iso,
        "source": "Schwab Trader API (live)",
        "total_portfolio_value": round(total, 2),
        "accounts": accounts_out,
        "portfolio_summary": summary,
    }


def print_diff(old, new):
    print(f"\n=== Portfolio Diff ===")
    old_total = old.get("total_portfolio_value", 0)
    new_total = new["total_portfolio_value"]
    delta = new_total - old_total
    print(f"Total portfolio: ${old_total:,.2f} → ${new_total:,.2f}  (Δ ${delta:+,.2f})")
    print(f"Source: {old.get('source','?')} → {new['source']}")
    print(f"As of:  {old.get('data_as_of','?')} → {new['data_as_of']}")

    print(f"\nPer-account:")
    for slot in new["accounts"]:
        old_acct = old.get("accounts", {}).get(slot, {})
        old_mv = old_acct.get("market_value", 0)
        new_mv = new["accounts"][slot]["market_value"]
        print(f"  {slot}: ${old_mv:>12,.2f} → ${new_mv:>12,.2f}  (Δ ${new_mv-old_mv:+,.2f})")

    print(f"\nPosition changes (top 10 by abs delta):")
    old_by_key = {}
    for slot, acct in old.get("accounts", {}).items():
        for h in acct.get("holdings", []):
            old_by_key[(slot, h["symbol"])] = h["market_value"]
    new_by_key = {}
    for slot, acct in new["accounts"].items():
        for h in acct["holdings"]:
            new_by_key[(slot, h["symbol"])] = h["market_value"]

    keys = set(old_by_key) | set(new_by_key)
    changes = [(k, new_by_key.get(k, 0) - old_by_key.get(k, 0)) for k in keys]
    changes.sort(key=lambda x: abs(x[1]), reverse=True)
    for (slot, sym), d in changes[:10]:
        old_v = old_by_key.get((slot, sym), 0)
        new_v = new_by_key.get((slot, sym), 0)
        tag = "ADDED" if not old_v else ("REMOVED" if not new_v else "UPDATED")
        print(f"  [{tag:8}] {slot:24} {sym:8} ${old_v:>10,.2f} → ${new_v:>10,.2f}  (Δ ${d:+,.2f})")


SLOT_TO_CSV_LABEL = {
    "joint_brokerage_aaa": "Joint (...aaa)",
    "individual_brokerage_bbb": "Individual (...bbb)",
    "roth_ira_ccc": "Roth IRA (...ccc)",
    "custodial_ddd": "Custodial UTMA (...ddd)",
}

TYPE_TO_CSV_LABEL = {
    "equity": "Equity",
    "etf": "ETF",
    "mutual_fund": "Mutual Fund",
    "money_market": "Money Market",
    "cash": "Cash",
    "option": "Option",
}


def write_holdings_csv(new_holdings):
    """Regenerate holdings.csv from live data to match the legacy CSV schema."""
    rows = []
    for slot, acct in new_holdings["accounts"].items():
        label = SLOT_TO_CSV_LABEL.get(slot, slot)
        for h in acct["holdings"]:
            shares = h["shares"] if h["shares"] is not None else "--"
            price = f"{h['price']:.2f}" if h["price"] is not None else "--"
            cb = f"{h['cost_basis_total']:.2f}" if h["cost_basis_total"] else "--"
            gl = (f"{(h['market_value'] - h['cost_basis_total']):.2f}"
                  if h["cost_basis_total"] else "--")
            gl_pct = f"{h['gain_pct']:.2f}%" if h["gain_pct"] is not None else "--"
            pct = f"{h['pct_of_account']:.2f}%" if h["pct_of_account"] is not None else "--"
            sym = h["symbol"] if h["symbol"] != "CASH" else "Cash"
            rows.append({
                "Account": label,
                "Symbol": sym,
                "Description": h["name"],
                "Shares": shares,
                "Price": price,
                "Market Value": f"{h['market_value']:.2f}",
                "Cost Basis": cb,
                "Gain/Loss $": gl,
                "Gain/Loss %": gl_pct,
                "% of Account": pct,
                "Type": TYPE_TO_CSV_LABEL.get(h["type"], h["type"].title()),
            })

    with open(HOLDINGS_CSV_PATH, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"  updated {HOLDINGS_CSV_PATH.name} ({len(rows)} rows)")


def _slim_holding(h):
    """Reduce a holdings.json holding to the slimmer schema used by brokerage/retirement.json."""
    sym = h["symbol"]
    if sym == "CASH":
        sym = "Cash"
    return {
        "symbol": sym,
        "shares": h["shares"],
        "market_value": h["market_value"],
        "cost_basis": h["cost_basis_total"],
        "gain_pct": h["gain_pct"],
        "pct_of_account": h["pct_of_account"],
    }


def _summary_for_account(acct):
    """Compute totals for one account from its holdings (excl. cash for cost basis)."""
    mv = acct["market_value"]
    cb = round(sum((h.get("cost_basis_total") or 0) for h in acct["holdings"]), 2)
    gain = round(mv - cb, 2) if cb else None
    gain_pct = round(gain / cb * 100, 2) if cb else None
    return mv, cb, gain, gain_pct


def update_brokerage_file(new_holdings):
    if not BROKERAGE_PATH.exists():
        print(f"  skip {BROKERAGE_PATH.name} (file not present)")
        return
    with open(BROKERAGE_PATH) as f:
        bro = json.load(f)

    new_accts = new_holdings["accounts"]
    out_accounts = []
    for entry in bro.get("accounts", []):
        last4 = entry.get("last_four")
        slot = next((s for s, l in SLOT_LAST4.items() if l == last4 and s in TAXABLE_SLOTS), None)
        if slot and slot in new_accts:
            live = new_accts[slot]
            mv, cb, gain, gain_pct = _summary_for_account(live)
            entry = {**entry,
                     "market_value": mv,
                     "cost_basis": cb,
                     "unrealized_gain": gain,
                     "gain_pct": gain_pct,
                     "as_of": new_holdings["data_as_of"],
                     "api_synced_at": new_holdings["data_as_of"],
                     "source": "Schwab Trader API (live)",
                     "holdings": [_slim_holding(h) for h in live["holdings"]]}
        out_accounts.append(entry)
    bro["accounts"] = out_accounts
    bro["total_taxable_value"] = round(sum(a.get("market_value", 0) for a in out_accounts), 2)

    with open(BROKERAGE_PATH, "w") as f:
        json.dump(bro, f, indent=2)
        f.write("\n")
    print(f"  updated {BROKERAGE_PATH.name} ({len([a for a in out_accounts if a.get('source','').startswith('Schwab')])} Schwab accounts refreshed)")


def update_retirement_file(new_holdings):
    if not RETIREMENT_PATH.exists():
        print(f"  skip {RETIREMENT_PATH.name} (file not present)")
        return
    with open(RETIREMENT_PATH) as f:
        ret = json.load(f)

    new_accts = new_holdings["accounts"]
    out_accounts = []
    refreshed = 0
    for entry in ret.get("accounts", []):
        last4 = entry.get("last_four")
        slot = next((s for s, l in SLOT_LAST4.items() if l == last4 and s in RETIREMENT_SLOTS), None)
        if slot and slot in new_accts:
            live = new_accts[slot]
            mv, cb, gain, gain_pct = _summary_for_account(live)
            entry = {**entry,
                     "market_value": mv,
                     "cost_basis": cb,
                     "unrealized_gain": gain,
                     "gain_pct": gain_pct,
                     "as_of": new_holdings["data_as_of"],
                     "api_synced_at": new_holdings["data_as_of"],
                     "source": "Schwab Trader API (live)",
                     "holdings": [_slim_holding(h) for h in live["holdings"]]}
            refreshed += 1
        out_accounts.append(entry)
    ret["accounts"] = out_accounts

    with open(RETIREMENT_PATH, "w") as f:
        json.dump(ret, f, indent=2)
        f.write("\n")
    print(f"  updated {RETIREMENT_PATH.name} ({refreshed} Schwab Roth account refreshed; non-Schwab retirement entries preserved)")


def update_accounts_file(new_holdings):
    if not ACCOUNTS_PATH.exists():
        print(f"  skip {ACCOUNTS_PATH.name} (file not present)")
        return
    with open(ACCOUNTS_PATH) as f:
        acc = json.load(f)

    new_accts = new_holdings["accounts"]
    out_brokerage = []
    refreshed = 0
    for entry in acc.get("brokerage_accounts", []):
        last4 = entry.get("account_last4")
        slot = next((s for s, l in SLOT_LAST4.items() if l == last4), None)
        if slot and slot in new_accts:
            live = new_accts[slot]
            mv, cb, gain, gain_pct = _summary_for_account(live)
            entry = {**entry,
                     "market_value": mv,
                     "cost_basis": cb,
                     "unrealized_gain": gain,
                     "unrealized_gain_pct": gain_pct,
                     "api_synced_at": new_holdings["data_as_of"]}
            refreshed += 1
        out_brokerage.append(entry)
    acc["brokerage_accounts"] = out_brokerage
    acc["last_updated"] = new_holdings["last_updated"]
    acc["data_as_of"] = new_holdings["data_as_of"]
    acc["source"] = "Schwab Trader API (live) + manual entries"
    acc["total_investment_value"] = round(sum(a.get("market_value", 0) for a in out_brokerage), 2)
    acc["total_cost_basis"] = round(sum(a.get("cost_basis", 0) or 0 for a in out_brokerage), 2)
    acc["total_unrealized_gain"] = round(
        acc["total_investment_value"] - acc["total_cost_basis"], 2
    )

    with open(ACCOUNTS_PATH, "w") as f:
        json.dump(acc, f, indent=2)
        f.write("\n")
    print(f"  updated {ACCOUNTS_PATH.name} ({refreshed} Schwab accounts refreshed)")


def update_crypto_file(new_holdings):
    """Refresh TICKER2 exposure in crypto.json from live holdings (pure derived data)."""
    if not CRYPTO_PATH.exists():
        print(f"  skip {CRYPTO_PATH.name} (file not present)")
        return
    with open(CRYPTO_PATH) as f:
        cr = json.load(f)

    total = new_holdings["total_portfolio_value"]
    accts = []
    total_shares = 0
    total_mv = 0.0
    for slot, acct in new_holdings["accounts"].items():
        for h in acct["holdings"]:
            if h["symbol"] == "TICKER2":
                accts.append({
                    "account": CRYPTO_ACCT_LABELS.get(slot, slot),
                    "shares": h["shares"],
                    "market_value": h["market_value"],
                    "cost_basis": h["cost_basis_total"],
                })
                total_shares += h["shares"] or 0
                total_mv += h["market_value"] or 0
    cr["as_of"] = new_holdings["last_updated"]
    cr["source"] = "Schwab Trader API (live) — see profile/portfolio/holdings.json (canonical)"
    cr["total_ibit_exposure"] = {
        "total_shares": total_shares,
        "total_market_value": round(total_mv, 2),
        "pct_of_total_portfolio": round(total_mv / total * 100, 2) if total else 0,
        "accounts": accts,
    }
    with open(CRYPTO_PATH, "w") as f:
        json.dump(cr, f, indent=2)
        f.write("\n")
    print(f"  updated {CRYPTO_PATH.name} (TICKER2 exposure refreshed: ${total_mv:,.2f})")


def update_memory_status(new_holdings):
    """Regenerate the auto-managed Status block in memory/MEMORY.md (between markers)."""
    if not MEMORY_INDEX_PATH.exists():
        print(f"  skip {MEMORY_INDEX_PATH.name} (file not present)")
        return
    text = MEMORY_INDEX_PATH.read_text()
    begin = "<!-- STATUS:BEGIN"
    end = "<!-- STATUS:END -->"
    if begin not in text or end not in text:
        print(f"  skip {MEMORY_INDEX_PATH.name} (STATUS markers not found)")
        return
    block = (
        "<!-- STATUS:BEGIN (auto-generated by scripts/schwab/sync.py — do not hand-edit) -->\n"
        "- **Onboarding:** COMPLETE — profile fully populated under `profile/`.\n"
        f"- **Last holdings/profile sync:** {new_holdings['last_updated']} "
        "(Schwab Trader API live). Run `/sync` after dropping new statements.\n"
        f"- **Portfolio value (as of last sync):** ${new_holdings['total_portfolio_value']:,.2f} "
        "(Schwab). Recompute from `profile/portfolio/holdings.json`.\n"
        "- **Canonical financial source of truth:** `profile/portfolio/holdings.json` "
        "(positions/balances), `profile/accounts/*` (account-level), filed returns in "
        "`profile/tax/` (income). Do NOT trust hardcoded dollar figures in narrative files "
        "— recompute from these.\n"
        "<!-- STATUS:END -->"
    )
    pre = text[: text.index(begin)]
    post = text[text.index(end) + len(end):]
    MEMORY_INDEX_PATH.write_text(pre + block + post)
    print(f"  updated {MEMORY_INDEX_PATH.name} (Status block regenerated)")


def update_freshness(new_holdings, accounts_synced):
    if FRESHNESS_PATH.exists():
        with open(FRESHNESS_PATH) as f:
            fresh = json.load(f)
    else:
        fresh = {}

    with open(KEYS_PATH) as f:
        keys = json.load(f)
    refresh_expires = keys["schwab"]["tokens"].get("refresh_token_expires_at")

    fresh.setdefault("api_sources", {})
    fresh["api_sources"]["schwab"] = {
        "last_sync": new_holdings["data_as_of"],
        "refresh_token_expires": refresh_expires,
        "status": "active",
        "accounts_synced": accounts_synced,
        "portfolio_value": new_holdings["total_portfolio_value"],
    }
    fresh["last_sync_date"] = new_holdings["last_updated"]

    km = fresh.setdefault("key_metrics", {})
    km["portfolio_value_schwab"] = new_holdings["total_portfolio_value"]

    with open(FRESHNESS_PATH, "w") as f:
        json.dump(fresh, f, indent=2)
        f.write("\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="Write to holdings.json (default: dry-run to holdings.live.json)")
    args = ap.parse_args()

    print("Fetching live positions from Schwab...")
    c = get_read_only_client()
    resp = c.get_accounts(fields=["positions"])
    if resp.status_code != 200:
        print(f"FAIL: {resp.status_code}: {resp.text}")
        sys.exit(1)
    accounts_resp = resp.json()

    PROBE_DIR.mkdir(parents=True, exist_ok=True)
    with open(PROBE_DIR / "accounts_with_positions.json", "w") as f:
        json.dump(accounts_resp, f, indent=2, default=str)
        f.write("\n")

    now_iso = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    new_holdings = build_holdings(accounts_resp, now_iso)
    print(f"Built holdings: {len(new_holdings['accounts'])} accounts, "
          f"${new_holdings['total_portfolio_value']:,.2f} total")

    if HOLDINGS_PATH.exists():
        with open(HOLDINGS_PATH) as f:
            old = json.load(f)
        print_diff(old, new_holdings)
    else:
        print("(no existing holdings.json to diff against)")

    if args.apply:
        with open(HOLDINGS_PATH, "w") as f:
            json.dump(new_holdings, f, indent=2)
            f.write("\n")
        print(f"\nWrote {HOLDINGS_PATH.name}")
        print("Updating account summary files (preserving non-Schwab entries):")
        write_holdings_csv(new_holdings)
        update_brokerage_file(new_holdings)
        update_retirement_file(new_holdings)
        update_accounts_file(new_holdings)
        update_crypto_file(new_holdings)
        update_memory_status(new_holdings)
        update_freshness(new_holdings, list(new_holdings["accounts"].keys()))
        print(f"Updated {FRESHNESS_PATH.relative_to(ROOT)}")
        print("\nRun the drift-lint to confirm consistency:")
        print("  python3.10 scripts/consistency_check.py")
    else:
        with open(HOLDINGS_LIVE_PATH, "w") as f:
            json.dump(new_holdings, f, indent=2)
            f.write("\n")
        print(f"\nDry-run: wrote {HOLDINGS_LIVE_PATH.name} (existing holdings.json untouched)")
        print("Re-run with --apply to commit.")


if __name__ == "__main__":
    main()
