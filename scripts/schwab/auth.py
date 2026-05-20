#!/usr/bin/env python3.10
"""
Schwab API OAuth bootstrap / refresh.

Run this:
  - Once for initial OAuth dance (mints first refresh token).
  - Every <7 days to keep the refresh token alive (schwab-py auto-handles
    refresh as long as the token file is fresh).

Reads:   profile/api-keys.json  (schwab.app_key, app_secret, callback_url)
Writes:  profile/.schwab-token.json  (managed by schwab-py)
         profile/api-keys.json  (account_hashes, last_auth, refresh_token_expires_at)
"""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from schwab.auth import client_from_manual_flow, client_from_token_file

ROOT = Path(__file__).resolve().parents[2]
KEYS_PATH = ROOT / "profile" / "api-keys.json"
TOKEN_PATH = ROOT / "profile" / ".schwab-token.json"

# Map the last 3 digits of each of your Schwab account numbers to a slot label.
# Replace these placeholders with your own account suffixes + labels.
ACCOUNT_SUFFIX_MAP = {
    "aaa": "joint_aaa",
    "bbb": "individual_bbb",
    "ccc": "roth_ccc",
    "ddd": "utma_ddd",
}


def load_keys():
    with open(KEYS_PATH) as f:
        return json.load(f)


def save_keys(keys):
    with open(KEYS_PATH, "w") as f:
        json.dump(keys, f, indent=2)
        f.write("\n")


def get_client(app_key, app_secret, callback_url):
    if TOKEN_PATH.exists():
        print(f"Loading existing token from {TOKEN_PATH}")
        return client_from_token_file(str(TOKEN_PATH), app_key, app_secret)

    print("No token file found. Starting manual OAuth flow.")
    print("schwab-py will print an auth URL. Open it in a browser,")
    print("log into Schwab, consent, then paste the redirect URL back here.")
    print()
    return client_from_manual_flow(
        api_key=app_key,
        app_secret=app_secret,
        callback_url=callback_url,
        token_path=str(TOKEN_PATH),
    )


def map_account_hashes(accounts):
    hashes = {slot: None for slot in ACCOUNT_SUFFIX_MAP.values()}
    unmapped = []
    for a in accounts:
        num = a["accountNumber"]
        matched = False
        for suffix, slot in ACCOUNT_SUFFIX_MAP.items():
            if num.endswith(suffix):
                hashes[slot] = a["hashValue"]
                matched = True
                break
        if not matched:
            unmapped.append(num)
    return hashes, unmapped


def main():
    keys = load_keys()
    schwab = keys.get("schwab")
    if not schwab:
        print("ERROR: no 'schwab' block in api-keys.json", file=sys.stderr)
        sys.exit(1)

    app_key = schwab["app_key"]
    app_secret = schwab["app_secret"]
    callback = schwab["callback_url"]

    if app_key.startswith("PASTE") or app_secret.startswith("PASTE"):
        print("ERROR: app_key/app_secret still have placeholder values.", file=sys.stderr)
        sys.exit(1)

    client = get_client(app_key, app_secret, callback)

    print("\nFetching account numbers + hashes...")
    resp = client.get_account_numbers()
    if resp.status_code != 200:
        print(f"ERROR: get_account_numbers returned {resp.status_code}", file=sys.stderr)
        print(resp.text, file=sys.stderr)
        sys.exit(1)

    accounts = resp.json()
    print(f"\nReturned {len(accounts)} accounts:")
    for a in accounts:
        masked = "*" * (len(a["accountNumber"]) - 4) + a["accountNumber"][-4:]
        print(f"  {masked}  hash={a['hashValue'][:12]}...")

    hashes, unmapped = map_account_hashes(accounts)
    if unmapped:
        print(f"\nWARNING: {len(unmapped)} account(s) did not match known suffixes "
              f"({'/'.join(ACCOUNT_SUFFIX_MAP)}): {unmapped}")

    now = datetime.now(timezone.utc)
    schwab["account_hashes"] = hashes
    schwab["tokens"]["last_auth"] = now.isoformat()
    schwab["tokens"]["refresh_token_expires_at"] = (now + timedelta(days=7)).isoformat()
    schwab["app_status"] = "ready_for_use"
    if not schwab.get("app_approved_date"):
        schwab["app_approved_date"] = now.date().isoformat()
    keys["schwab"] = schwab
    save_keys(keys)

    print(f"\nUpdated {KEYS_PATH.name}")
    print(f"  account_hashes: {sum(1 for v in hashes.values() if v)} / 4 mapped")
    print(f"  refresh_token_expires_at: {schwab['tokens']['refresh_token_expires_at']}")
    print("\nRe-run this script before that expiry to refresh.")
    print("\nWhile you're here (weekly cadence), refresh holdings + check consistency:")
    print("  python3.10 scripts/schwab/sync.py --apply")
    print("  python3.10 scripts/consistency_check.py")


if __name__ == "__main__":
    main()
