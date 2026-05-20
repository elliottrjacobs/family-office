#!/usr/bin/env python3.10
"""
Fetches one full snapshot from the Schwab API and dumps it to disk so we can
inspect the real response shape before writing the sync transformer.

Outputs (in profile/portfolio/_probe/):
  accounts_with_positions.json   — all configured accounts + positions
  quotes_sample.json             — quotes for top symbols across accounts
  transactions_sample.json       — 30 days of transactions from joint account

Writes NOTHING to existing profile files. Pure read.
"""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from client import get_read_only_client

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "profile" / "portfolio" / "_probe"
OUT_DIR.mkdir(parents=True, exist_ok=True)


def dump(name, obj):
    path = OUT_DIR / name
    with open(path, "w") as f:
        json.dump(obj, f, indent=2, default=str)
    print(f"  wrote {path.relative_to(ROOT)}  ({path.stat().st_size} bytes)")


def main():
    c = get_read_only_client()

    print("1. Fetching all accounts with positions...")
    resp = c.get_accounts(fields=["positions"])
    if resp.status_code != 200:
        print(f"  FAIL: {resp.status_code}: {resp.text}")
        sys.exit(1)
    accounts = resp.json()
    dump("accounts_with_positions.json", accounts)

    symbols_seen = set()
    for entry in accounts:
        sa = entry.get("securitiesAccount") or entry.get("aggregatedBalance") or entry
        for pos in sa.get("positions", []):
            sym = (pos.get("instrument") or {}).get("symbol")
            if sym:
                symbols_seen.add(sym)
    print(f"  collected {len(symbols_seen)} unique symbols across accounts")

    print("\n2. Fetching live quotes for those symbols...")
    if symbols_seen:
        resp = c.get_quotes(list(symbols_seen))
        if resp.status_code != 200:
            print(f"  WARN: quotes returned {resp.status_code}: {resp.text[:200]}")
        else:
            dump("quotes_sample.json", resp.json())
    else:
        print("  no symbols found, skipping quotes")

    print("\n3. Fetching last 30 days of transactions from one account...")
    with open(ROOT / "profile" / "api-keys.json") as f:
        keys = json.load(f)
    joint_hash = keys["schwab"]["account_hashes"]["joint_aaa"]
    if joint_hash:
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=30)
        try:
            resp = c.get_transactions(joint_hash, start_date=start, end_date=end)
            if resp.status_code == 200:
                dump("transactions_sample.json", resp.json())
            else:
                print(f"  WARN: transactions returned {resp.status_code}: {resp.text[:200]}")
        except Exception as e:
            print(f"  WARN: transactions call raised: {e}")
    else:
        print("  no joint_aaa hash available")

    print("\nDone. Inspect files in profile/portfolio/_probe/ to see real schema.")


if __name__ == "__main__":
    main()
