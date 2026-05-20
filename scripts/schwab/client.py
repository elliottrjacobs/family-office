#!/usr/bin/env python3.10
"""
Schwab read-only client wrapper.

Wraps schwab-py to expose ONLY whitelisted read methods. Any attempt to
call mutating methods (place_order / replace_order / cancel_order) or
access the raw HTTP session raises ReadOnlyClientError BEFORE any HTTP
request is made.

ALL skills and sub-agents MUST import from here:

    from scripts.schwab.client import get_read_only_client
    c = get_read_only_client()
    quotes = c.get_quotes(["AAPL", "NVDA"]).json()

Direct `from schwab.auth import ...` is forbidden outside auth.py.

To enable trading (deliberate change required):
  1. Add the method name to ALLOWED_METHODS below.
  2. Remove it from BLOCKED_METHODS.
  3. Re-test with test_read_only.py.
  4. Commit the change with explicit rationale.
"""
import json
from pathlib import Path

from schwab.auth import client_from_token_file

ROOT = Path(__file__).resolve().parents[2]
KEYS_PATH = ROOT / "profile" / "api-keys.json"
TOKEN_PATH = ROOT / "profile" / ".schwab-token.json"


ALLOWED_METHODS = frozenset({
    "get_account_numbers", "get_account", "get_accounts",
    "get_transactions", "get_transaction",
    "get_orders_for_account", "get_orders_for_all_linked_accounts", "get_order",
    "get_user_preferences",
    "get_quote", "get_quotes",
    "get_option_chain", "get_option_expiration_chain",
    "get_price_history",
    "get_price_history_every_minute",
    "get_price_history_every_five_minutes",
    "get_price_history_every_ten_minutes",
    "get_price_history_every_fifteen_minutes",
    "get_price_history_every_thirty_minutes",
    "get_price_history_every_day",
    "get_price_history_every_week",
    "get_movers",
    "get_market_hours", "get_market_hours_for_single_market",
    "get_instruments", "get_instrument",
})


BLOCKED_METHODS = frozenset({
    "place_order",
    "replace_order",
    "cancel_order",
})


class ReadOnlyClientError(Exception):
    """Raised when a blocked or unknown method is called on the wrapper."""


class ReadOnlySchwabClient:
    """Whitelist proxy around schwab-py's client. Only ALLOWED_METHODS pass through."""

    def __init__(self, raw_client):
        self._client = raw_client

    def __getattr__(self, name):
        if name in BLOCKED_METHODS:
            raise ReadOnlyClientError(
                f"BLOCKED: '{name}' is a mutating endpoint. This wrapper is read-only. "
                f"See scripts/schwab/client.py to enable (deliberate change required)."
            )
        if name in ALLOWED_METHODS:
            return getattr(self._client, name)
        if name.startswith("_"):
            raise AttributeError(name)
        raise ReadOnlyClientError(
            f"DENIED: '{name}' is not in the read-only allowlist. "
            f"If this is a read method, add it to ALLOWED_METHODS in scripts/schwab/client.py."
        )

    @property
    def session(self):
        raise ReadOnlyClientError(
            "BLOCKED: direct session access bypasses the read-only wrapper. "
            "Use a whitelisted method instead."
        )

    @property
    def session_manager(self):
        raise ReadOnlyClientError(
            "BLOCKED: direct session_manager access bypasses the read-only wrapper."
        )


def get_read_only_client():
    """Load credentials, refresh token if needed, return a read-only client."""
    with open(KEYS_PATH) as f:
        keys = json.load(f)
    s = keys["schwab"]
    if not TOKEN_PATH.exists():
        raise FileNotFoundError(
            f"No token file at {TOKEN_PATH}. Run `python3.10 scripts/schwab/auth.py` first."
        )
    raw = client_from_token_file(
        str(TOKEN_PATH), s["app_key"], s["app_secret"],
        enforce_enums=False,
    )
    return ReadOnlySchwabClient(raw)
