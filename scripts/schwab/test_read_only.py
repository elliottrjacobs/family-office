#!/usr/bin/env python3.10
"""
Proves the read-only wrapper blocks mutating methods BEFORE any HTTP call.

Runs end-to-end against the live API for the read path, and unit-tests the
block path without making any HTTP calls.
"""
import sys

from client import (
    ReadOnlyClientError,
    ReadOnlySchwabClient,
    get_read_only_client,
    ALLOWED_METHODS,
    BLOCKED_METHODS,
)


def test_blocks_without_api_calls():
    """No real client needed — test the wrapper logic directly."""
    class FakeRaw:
        def place_order(self, *a, **kw):
            raise AssertionError("place_order should never be reached")
        def cancel_order(self, *a, **kw):
            raise AssertionError("cancel_order should never be reached")
        def replace_order(self, *a, **kw):
            raise AssertionError("replace_order should never be reached")
        def get_quote(self, *a, **kw):
            return "quote-result"
        def some_random_method(self, *a, **kw):
            return "should-not-be-reachable"

    c = ReadOnlySchwabClient(FakeRaw())

    blocks_tested = 0
    for method in BLOCKED_METHODS:
        try:
            getattr(c, method)
            print(f"  FAIL: {method} did not raise")
            sys.exit(1)
        except ReadOnlyClientError as e:
            assert "BLOCKED" in str(e), f"wrong error for {method}: {e}"
            blocks_tested += 1
    print(f"  OK: all {blocks_tested} BLOCKED_METHODS raise before HTTP")

    try:
        getattr(c, "some_random_method")
        print("  FAIL: unknown method did not raise")
        sys.exit(1)
    except ReadOnlyClientError as e:
        assert "DENIED" in str(e), f"wrong error: {e}"
    print("  OK: unknown methods raise DENIED")

    try:
        _ = c.session
        print("  FAIL: session access did not raise")
        sys.exit(1)
    except ReadOnlyClientError:
        pass
    print("  OK: raw session access is blocked")

    assert c.get_quote() == "quote-result", "allowed method should pass through"
    print("  OK: allowed methods (get_quote) pass through")


def test_live_read():
    """Hit the real API on the read path to confirm credentials work."""
    c = get_read_only_client()
    resp = c.get_account_numbers()
    if resp.status_code != 200:
        print(f"  FAIL: get_account_numbers returned {resp.status_code}: {resp.text}")
        sys.exit(1)
    n = len(resp.json())
    print(f"  OK: get_account_numbers returned {n} accounts")


if __name__ == "__main__":
    print("Test 1: wrapper blocks mutating methods (no HTTP calls)")
    test_blocks_without_api_calls()
    print("\nTest 2: live read against Schwab API")
    test_live_read()
    print("\nAll tests passed. Trading endpoints are blocked.")
