#!/usr/bin/env python3.10
"""
SimpleFIN connection probe — read-only, writes nothing.

Prints every account the bridge exposes with its SimpleFIN id, org, balance,
and a sample of recent transactions. Use it to (a) confirm the Access URL
works and (b) collect the account ids needed to fill simplefin.account_map
in api-keys.json.

Usage:
  python3.10 scripts/simplefin/probe.py            # balances + 5 recent txns each
  python3.10 scripts/simplefin/probe.py --balances # balances only (fast)
"""
import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from client import get_simplefin_client, SimpleFINError


def fmt_epoch(secs):
    if not secs:
        return "?"
    return datetime.fromtimestamp(int(secs), tz=timezone.utc).astimezone().strftime("%Y-%m-%d")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--balances", action="store_true", help="Balances only, no transactions")
    args = ap.parse_args()

    try:
        client = get_simplefin_client()
    except SimpleFINError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    data = client.get_accounts(balances_only=args.balances)
    errors = data.get("errors") or []
    if errors:
        print(f"Bridge errors: {errors}\n")

    accounts = data.get("accounts", [])
    print(f"{len(accounts)} account(s) visible:\n")
    for a in accounts:
        org = (a.get("org") or {}).get("name") or (a.get("org") or {}).get("domain") or "?"
        print(f"id={a.get('id')}")
        print(f"  org:       {org}")
        print(f"  name:      {a.get('name')}")
        print(f"  balance:   {a.get('currency','')} {a.get('balance')}  "
              f"(available {a.get('available-balance','?')}, as of {fmt_epoch(a.get('balance-date'))})")
        txns = a.get("transactions") or []
        if not args.balances:
            print(f"  txns:      {len(txns)} returned")
            for t in txns[:5]:
                pend = " [PENDING]" if t.get("pending") else ""
                print(f"     {fmt_epoch(t.get('posted'))}  {t.get('amount','?'):>12}  "
                      f"{(t.get('description') or t.get('payee') or '')[:48]}{pend}")
        print()


if __name__ == "__main__":
    main()
