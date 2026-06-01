#!/usr/bin/env python3.10
"""
SimpleFIN setup — claim a setup token into a durable Access URL.

SimpleFIN flow:
  1. You generate a one-time, base64-encoded *Setup Token* at your bridge
     (e.g. bridge.simplefin.org). This is what most apps call the "app token".
  2. base64-decode it -> a one-time *Claim URL*.
  3. POST (empty body) to the Claim URL -> the bridge returns a durable
     *Access URL* with embedded credentials. THE SETUP TOKEN IS CONSUMED here
     and can never be claimed again.
  4. We persist the Access URL to profile/api-keys.json -> simplefin.access_url
     (gitignored via **/api-keys*). It does not expire — no weekly re-auth
     (unlike the Schwab refresh token).

Usage:
  python3.10 scripts/simplefin/auth.py --token <SETUP_TOKEN_OR_ACCESS_URL>
  SIMPLEFIN_SETUP_TOKEN=<...> python3.10 scripts/simplefin/auth.py
  python3.10 scripts/simplefin/auth.py            # prompts on stdin

If the value you pass is already an Access URL (https://user:pass@host/...),
the claim step is skipped and it's stored directly.

Reads/Writes: profile/api-keys.json  (simplefin block)
"""
import argparse
import base64
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[2]
KEYS_PATH = ROOT / "profile" / "api-keys.json"


def load_keys():
    if not KEYS_PATH.exists():
        print(f"ERROR: no api-keys.json at {KEYS_PATH}", file=sys.stderr)
        sys.exit(1)
    with open(KEYS_PATH) as f:
        return json.load(f)


def save_keys(keys):
    with open(KEYS_PATH, "w") as f:
        json.dump(keys, f, indent=2)
        f.write("\n")


def looks_like_access_url(value):
    v = value.strip()
    return v.startswith("http://") or v.startswith("https://")


def claim_setup_token(setup_token):
    """Decode a base64 setup token, POST to the claim URL, return the Access URL."""
    token = setup_token.strip()
    try:
        claim_url = base64.b64decode(token).decode("utf-8").strip()
    except Exception as e:  # noqa: BLE001
        print(f"ERROR: could not base64-decode the setup token ({e}).", file=sys.stderr)
        print("If you pasted an Access URL instead, that's fine — it starts with https://", file=sys.stderr)
        sys.exit(1)

    if not claim_url.startswith("http"):
        print(f"ERROR: decoded value is not a URL: {claim_url[:80]!r}", file=sys.stderr)
        sys.exit(1)

    print(f"Claiming setup token at: {claim_url.split('/claim/')[0]}/claim/****")
    resp = requests.post(claim_url, timeout=60)
    if resp.status_code == 403:
        print("ERROR 403: this setup token was already claimed (they are one-time).", file=sys.stderr)
        print("Generate a fresh setup token at your bridge, or pass the existing Access URL.", file=sys.stderr)
        sys.exit(1)
    if resp.status_code != 200:
        print(f"ERROR: claim returned HTTP {resp.status_code}: {resp.text[:300]}", file=sys.stderr)
        sys.exit(1)

    access_url = resp.text.strip()
    if "@" not in access_url or not access_url.startswith("http"):
        print(f"ERROR: claim response is not a valid Access URL: {access_url[:80]!r}", file=sys.stderr)
        sys.exit(1)
    return access_url


def verify(access_url):
    """Hit /accounts?balances-only=1 to confirm the URL works; return account summaries."""
    sys.path.insert(0, str(Path(__file__).parent))
    from client import SimpleFINClient  # local import after path insert

    client = SimpleFINClient(access_url)
    data = client.get_accounts(balances_only=True)
    errors = data.get("errors") or []
    if errors:
        print(f"  NOTE: bridge returned errors: {errors}")
    return data.get("accounts", [])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--token", help="Setup token (base64) OR an existing Access URL")
    ap.add_argument("--force", action="store_true",
                    help="Overwrite an existing simplefin.access_url")
    args = ap.parse_args()

    keys = load_keys()
    existing = (keys.get("simplefin") or {}).get("access_url")
    if existing and not existing.startswith("PASTE") and not args.force:
        print("An Access URL is already stored in api-keys.json (simplefin.access_url).")
        print("Setup tokens are one-time, so re-claiming a consumed token will fail.")
        print("If you intend to replace it with a NEW token/URL, re-run with --force.")
        sys.exit(0)

    value = (
        args.token
        or os.environ.get("SIMPLEFIN_SETUP_TOKEN")
        or (sys.stdin.readline().strip() if not sys.stdin.isatty() else
            input("Paste your SimpleFIN setup token (or Access URL): ").strip())
    )
    if not value:
        print("ERROR: no setup token provided.", file=sys.stderr)
        sys.exit(1)

    if looks_like_access_url(value):
        print("Input looks like an Access URL — storing directly (skipping claim).")
        access_url = value.strip()
    else:
        access_url = claim_setup_token(value)

    now = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    sf = keys.get("simplefin") or {}
    sf.update({
        "access_url": access_url,
        "claimed_at": now,
        "bridge": access_url.split("@")[-1].split("/")[0],
        "account_map": sf.get("account_map", {}),
        "notes": [
            "Access URL is a durable bearer-equivalent secret — gitignored via **/api-keys*.",
            "SimpleFIN is read-only by protocol; no weekly re-auth needed.",
            "account_map pins SimpleFIN account id -> {last4,type,label} for stable profile matching.",
        ],
    })
    keys["simplefin"] = sf
    save_keys(keys)
    print(f"\nStored Access URL in {KEYS_PATH.name} (simplefin.access_url).")

    print("\nVerifying connection (balances-only)...")
    accounts = verify(access_url)
    print(f"  Bridge reachable. {len(accounts)} account(s) visible:")
    for a in accounts:
        org = (a.get("org") or {}).get("name") or (a.get("org") or {}).get("domain") or "?"
        print(f"    [{a.get('id','?')[:18]:18}] {org:22} {a.get('name','?'):28} "
              f"{a.get('currency','')} {a.get('balance','?')}")

    print("\nNext steps:")
    print("  1. Map any unmatched accounts (auth.py prints ids above).")
    print("  2. Pull full history + write profile:")
    print("       python3.10 scripts/simplefin/sync.py --full          # dry-run preview")
    print("       python3.10 scripts/simplefin/sync.py --full --apply   # commit")
    print("  3. Routine/daily refresh later:  python3.10 scripts/simplefin/sync.py --apply")


if __name__ == "__main__":
    main()
