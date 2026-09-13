import sqlite3

import pytest

from fo.errors import OfficeError
from fo.init import initialize
from fo.providers.cache import Cache
from fo.store.index import reindex


def test_rate_limit_response_not_cached_and_budget_enforced(tmp_path):
    root = tmp_path / "office"
    initialize(root)
    cache = Cache(root)
    with pytest.raises(OfficeError) as first:
        cache.get("x", 10, lambda: {"Information": "limit"}, "alpha", 1)
    assert first.value.reason == "rate_limited"
    with sqlite3.connect(cache.path) as db:
        assert db.execute("select count(*) from cache").fetchone()[0] == 0
    with pytest.raises(OfficeError) as second:
        cache.get("x", 10, lambda: {"price": 1}, "alpha", 1)
    assert second.value.reason == "rate_limited"


def test_offline_stale_cache_and_reindex_preservation(tmp_path):
    root = tmp_path / "office"
    initialize(root)
    cache = Cache(root)
    assert cache.get("x", 10, lambda: {"price": 95})["data"] == {"price": 95}
    before = cache.path.read_bytes()
    assert Cache(root, read_only=True).get("x", -1)["stale"]
    reindex(root)
    assert cache.path.read_bytes() == before
    assert cache.get("x", 10, lambda: pytest.fail("cache miss"))["data"]["price"] == 95
