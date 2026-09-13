import json
import sqlite3
import time
from contextlib import closing

from fo.errors import OfficeError
from fo.office import contained


class Cache:
    def __init__(self, root, read_only=False):
        self.path = contained(root, "cache/cache.sqlite")
        self.read_only = read_only

    def get(self, key, ttl, fetch=None, provider=None, daily_limit=None):
        cached = None
        if self.path.exists():
            try:
                with closing(
                    sqlite3.connect(self.path.as_uri() + "?mode=ro&immutable=1", uri=True)
                ) as db:
                    cached = db.execute(
                        "select fetched_at,payload from cache where key=?", (key,)
                    ).fetchone()
                if cached:
                    json.loads(cached[1])
            except (sqlite3.Error, ValueError) as exc:
                raise OfficeError(
                    "cache_corrupt",
                    "Market cache is invalid; remove cache/cache.sqlite locally to rebuild it. Canonical records are unaffected.",
                ) from exc
        if cached and (time.time() - cached[0] < ttl or self.read_only or fetch is None):
            return {
                "data": json.loads(cached[1]),
                "fetched_at": cached[0],
                "stale": time.time() - cached[0] >= ttl,
            }
        if self.read_only or fetch is None:
            raise OfficeError("missing_cached_data", "No cached data is available in offline mode.")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute(
                "create table if not exists cache(key text primary key, fetched_at real, payload text)"
            )
            db.execute(
                "create table if not exists budgets(provider text, day integer, used integer, primary key(provider,day))"
            )
            day = int(time.time() // 86400)
            if provider and daily_limit is not None:
                db.execute("begin immediate")
                row = db.execute(
                    "select used from budgets where provider=? and day=?", (provider, day)
                ).fetchone()
                used = row[0] if row else 0
                if used >= daily_limit:
                    if cached:
                        return {
                            "data": json.loads(cached[1]),
                            "fetched_at": cached[0],
                            "stale": True,
                            "warning": "rate_limited",
                        }
                    raise OfficeError("rate_limited", "Provider daily request budget exhausted.")
                db.execute(
                    "insert into budgets values(?,?,?) on conflict(provider,day) do update set used=excluded.used",
                    (provider, day, used + 1),
                )
                db.commit()
            try:
                payload = fetch()
                if isinstance(payload, dict) and ("Information" in payload or "Note" in payload):
                    raise OfficeError("rate_limited", "Provider returned a request-limit notice.")
            except OfficeError as exc:
                if cached:
                    return {
                        "data": json.loads(cached[1]),
                        "fetched_at": cached[0],
                        "stale": True,
                        "warning": exc.reason,
                    }
                raise
            stamp = time.time()
            db.execute(
                "insert into cache values(?,?,?) on conflict(key) do update set fetched_at=excluded.fetched_at,payload=excluded.payload",
                (key, stamp, json.dumps(payload, allow_nan=False)),
            )
        return {"data": payload, "fetched_at": stamp, "stale": False}
