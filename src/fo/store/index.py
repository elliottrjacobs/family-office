import hashlib
import json
import os
import sqlite3
import tempfile
from contextlib import closing

from fo.errors import OfficeError
from fo.lock import office_lock
from fo.office import contained
from fo.store.jsonl import TABLES, read_rows

SCHEMA_VERSION = 3


def project(root, as_of=None):
    """Project canonical records without writes, even when an old index exists."""
    voids = read_rows(root, "data/voids.jsonl")
    void_runs = {r["run_id"] for r in voids if "run_id" in r}
    void_rows = {r["row_id"] for r in voids if "row_id" in r}
    logs = [
        r
        for r in read_rows(root, "data/sync_log.jsonl")
        if r.get("status") == "complete"
        and r["run_id"] not in void_runs
        and (as_of is None or r["as_of"][:10] <= as_of)
    ]
    # Log append order breaks ties for provider timestamps, including same-millisecond runs.
    logs.sort(key=lambda r: (r["as_of"], r.get("sequence", 0)))
    complete = {r["run_id"] for r in logs}
    current, latest_provider, providers = {}, {}, {}
    for log in logs:
        provider = log["provider"]
        latest_provider[provider] = log
        for account in log.get("snapshot_account_ids", log["account_ids"]):
            source = log.get("unchanged_since", {}).get(account, log["run_id"])
            if source not in complete:
                continue
            current[account] = source
            providers[account] = provider
    result = {}
    for name in ("positions", "balances"):
        result[name] = [
            r
            for r in read_rows(root, f"data/{name}.jsonl")
            if current.get(r.get("account_id")) == r.get("run_id")
            and r.get("row_id") not in void_rows
        ]
    transactions = {}
    for row in read_rows(root, "data/transactions.jsonl"):
        if row.get("run_id") in complete and row.get("row_id") not in void_rows:
            key = row["account_id"], row["transaction_id"]
            if row.get("revision", 0) >= transactions.get(key, {}).get("revision", -1):
                transactions[key] = row
    result["transactions"] = list(transactions.values())
    result["stale_accounts"] = sorted(
        a for a, provider in providers.items() if a not in latest_provider[provider]["account_ids"]
    )
    result["providers"] = latest_provider
    result["snapshots"] = current
    result["as_of"] = min(
        (r["as_of"] for k in ("positions", "balances") for r in result[k]), default=None
    )
    return result


def fingerprint(root):
    digest = hashlib.sha256()
    for directory in ("data", "notebook", "profile", "reports"):
        for path in sorted(contained(root, directory).rglob("*")):
            if path.is_symlink():
                raise OfficeError("unsafe_path", "A source file is a symlink.")
            if path.is_file():
                digest.update(str(path.relative_to(root)).encode())
                digest.update(path.read_bytes())
    return digest.hexdigest()


def reindex(root, locked=False):
    if not locked:
        with office_lock(root):
            return reindex(root, locked=True)
    state = project(root)
    target = contained(root, "store.sqlite")
    fd, name = tempfile.mkstemp(prefix=".fo-index-", dir=root)
    os.close(fd)
    try:
        with closing(sqlite3.connect(name)) as db:
            db.execute("pragma journal_mode=wal")
            db.execute("create table metadata (schema_version integer, source_hash text)")
            db.execute("insert into metadata values (?, ?)", (SCHEMA_VERSION, fingerprint(root)))
            db.execute("create table state (name text primary key, payload text not null)")
            db.executemany(
                "insert into state values (?, ?)",
                [(key, json.dumps(value)) for key, value in state.items()],
            )
            from fo.compute import categorized
            from fo.reports import scan

            db.execute(
                "create table categories (transaction_id text, category text, transfer integer, rules_hash text)"
            )
            rules_hash = hashlib.sha256(
                contained(root, "profile/categories.yaml").read_bytes()
            ).hexdigest()
            db.executemany(
                "insert into categories values (?, ?, ?, ?)",
                [
                    (r["transaction_id"], r["category"], r["transfer"], rules_hash)
                    for r in categorized(root, state)
                ],
            )
            db.execute(
                "create table reports_index (path text primary key, kind text, subject text, date text, payload text)"
            )
            db.executemany(
                "insert into reports_index values (?, ?, ?, ?, ?)",
                [
                    (
                        r["path"],
                        r["frontmatter"]["kind"],
                        r["frontmatter"]["subject"],
                        r["frontmatter"]["date"],
                        json.dumps(r),
                    )
                    for r in scan(root)["reports"]
                ],
            )
            for path in sorted(TABLES):
                table = path.rsplit("/", 1)[1].removesuffix(".jsonl")
                db.execute(
                    f"create table {table} (as_of text not null, run_id text, account_id text, payload text not null)"
                )
                db.executemany(
                    f"insert into {table} values (?, ?, ?, ?)",
                    [
                        (r["as_of"], r.get("run_id"), r.get("account_id"), json.dumps(r))
                        for r in read_rows(root, path)
                    ],
                )
            for table, key in (
                ("current_positions", "positions"),
                ("current_balances", "balances"),
                ("current_transactions", "transactions"),
            ):
                db.execute(
                    f"create view {table} as select value as payload from state, json_each(state.payload) where state.name='{key}'"
                )
            db.commit()
            db.execute("pragma wal_checkpoint(truncate)")
        os.replace(name, target)
    finally:
        if os.path.exists(name):
            os.unlink(name)
    return {
        "schema_version": SCHEMA_VERSION,
        "positions": len(state["positions"]),
        "transactions": len(state["transactions"]),
    }


def read_state(root, read_only=False):
    target = contained(root, "store.sqlite")
    try:
        with closing(sqlite3.connect(target.as_uri() + "?mode=ro&immutable=1", uri=True)) as db:
            meta = db.execute("select schema_version, source_hash from metadata").fetchone()
            if meta == (SCHEMA_VERSION, fingerprint(root)):
                return {
                    key: json.loads(value)
                    for key, value in db.execute("select name,payload from state")
                }
    except (sqlite3.Error, OSError, ValueError):
        pass
    if not read_only:
        try:
            reindex(root)
        except (OSError, sqlite3.Error):
            pass
        except OfficeError as exc:
            if exc.reason != "office_locked":
                raise
    return project(root)
