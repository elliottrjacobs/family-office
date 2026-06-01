#!/usr/bin/env python3.10
"""
SimpleFIN read-only client wrapper.

SimpleFIN is a read-only data protocol — there are NO write/mutating
endpoints in the spec. This wrapper exists for architectural parity with
scripts/schwab/client.py: it centralizes loading of the durable Access URL
and exposes only the single GET /accounts endpoint.

The Access URL embeds HTTP Basic credentials
(https://USER:PASS@bridge.simplefin.org/simplefin). We split the userinfo
out of the netloc and pass it via requests' auth= so credentials never leak
into logs, query strings, or redirects.

ALL skills / sub-agents that need bank or credit-card data MUST import here:

    from scripts.simplefin.client import get_simplefin_client
    c = get_simplefin_client()
    data = c.get_accounts()                       # balances + recent txns
    data = c.get_accounts(balances_only=True)     # fast balance-only poll
    data = c.get_accounts(start_date=epoch_secs)  # history from a point in time

Credentials live in profile/api-keys.json -> simplefin.access_url
(gitignored via **/api-keys*). Run scripts/simplefin/auth.py to claim a
setup token into that slot.
"""
import json
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import requests

ROOT = Path(__file__).resolve().parents[2]
KEYS_PATH = ROOT / "profile" / "api-keys.json"

# SimpleFIN access URLs are durable bearer-equivalent secrets. A reasonable
# network timeout keeps a stalled bridge from hanging /sync indefinitely.
HTTP_TIMEOUT = 60


class SimpleFINError(Exception):
    """Raised on missing credentials or a non-2xx SimpleFIN response."""


class SimpleFINClient:
    """Thin read-only client over a SimpleFIN bridge Access URL."""

    def __init__(self, access_url):
        parts = urlsplit(access_url)
        if not parts.username or not parts.password:
            raise SimpleFINError(
                "Access URL has no embedded credentials. Expected "
                "https://USER:PASS@host/path — re-run scripts/simplefin/auth.py."
            )
        self._auth = (parts.username, parts.password)
        netloc = parts.hostname + (f":{parts.port}" if parts.port else "")
        # Base URL with credentials stripped from the netloc (auth goes via auth=).
        self._base = urlunsplit((parts.scheme, netloc, parts.path.rstrip("/"), "", ""))

    def get_accounts(self, start_date=None, end_date=None, pending=True,
                     balances_only=False, account_ids=None):
        """GET {access_url}/accounts.

        start_date / end_date: epoch SECONDS (int) bounding transactions.
        pending:        include not-yet-posted transactions (default True).
        balances_only:  skip transactions entirely (fast balance poll).
        account_ids:    optional list of SimpleFIN account ids to filter to.

        Returns the parsed JSON dict: {"errors": [...], "accounts": [...]}.
        """
        params = []
        if start_date is not None:
            params.append(("start-date", int(start_date)))
        if end_date is not None:
            params.append(("end-date", int(end_date)))
        if pending:
            params.append(("pending", 1))
        if balances_only:
            params.append(("balances-only", 1))
        for aid in (account_ids or []):
            params.append(("account", aid))

        resp = requests.get(
            self._base + "/accounts",
            auth=self._auth,
            params=params,
            timeout=HTTP_TIMEOUT,
        )
        if resp.status_code != 200:
            raise SimpleFINError(
                f"SimpleFIN /accounts returned {resp.status_code}: {resp.text[:300]}"
            )
        return resp.json()


def load_access_url():
    """Read the durable Access URL from profile/api-keys.json."""
    if not KEYS_PATH.exists():
        raise SimpleFINError(f"No api-keys.json at {KEYS_PATH}.")
    with open(KEYS_PATH) as f:
        keys = json.load(f)
    sf = keys.get("simplefin") or {}
    access_url = sf.get("access_url")
    if not access_url or access_url.startswith("PASTE"):
        raise SimpleFINError(
            "No simplefin.access_url in api-keys.json. "
            "Run `python3.10 scripts/simplefin/auth.py` to claim your setup token first."
        )
    return access_url


def get_simplefin_client():
    """Load the Access URL and return a ready-to-use read-only client."""
    return SimpleFINClient(load_access_url())
