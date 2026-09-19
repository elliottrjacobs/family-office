import json
import os
import re
import secrets
import time
from datetime import UTC, datetime

from fo.errors import OfficeError
from fo.office import contained
from fo.store.records import validate

TABLES = {
    f"data/{name}.jsonl"
    for name in ("accounts", "positions", "balances", "transactions", "sync_log", "voids")
} | {"notebook/decisions.jsonl", "notebook/reviews.jsonl"}
FORBIDDEN = {
    "accountnumber",
    "accounthash",
    "hashvalue",
    "accesstoken",
    "refreshtoken",
    "appsecret",
    "apikey",
    "accessurl",
    "authorization",
}


def now():
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def identifier():
    number = (time.time_ns() // 1_000_000 << 80) | secrets.randbits(80)
    alphabet = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
    return "".join(alphabet[(number >> shift) & 31] for shift in range(125, -1, -5))


def check_safe(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).replace("_", "").replace("-", "").lower() in FORBIDDEN:
                raise OfficeError(
                    "unsafe_payload", "Credential or full account identifier field rejected."
                )
            check_safe(item)
    elif isinstance(value, list):
        for item in value:
            check_safe(item)
    elif isinstance(value, str) and re.search(r"https?://\S+@\S+", value):
        raise OfficeError("unsafe_payload", "Credential URL rejected from canonical data.")


def read_rows(root, table):
    if table not in TABLES:
        raise OfficeError("unknown_table", "Unknown canonical table.")
    path = contained(root, table)
    if not path.exists():
        return []
    rows = []
    try:
        # An unterminated tail is an interrupted append, never a committed record.
        raw = path.read_bytes()
        for line in raw[: raw.rfind(b"\n") + 1].decode().splitlines():
            if line.strip():
                item = json.loads(line)
                if not isinstance(item, dict):
                    raise ValueError("record must be object")
                check_safe(item)
                validate(table, item)
                rows.append(item)
    except (OSError, ValueError) as exc:
        raise OfficeError(
            "store_corrupt",
            "Canonical JSONL contains an unreadable record; repair from its Git history.",
        ) from exc
    return rows


def torn(root):
    """Tables whose last append was interrupted before its newline."""
    result = []
    for table in sorted(TABLES):
        path = contained(root, table)
        if path.exists() and path.stat().st_size:
            with path.open("rb") as stream:
                stream.seek(-1, os.SEEK_END)
                if stream.read(1) != b"\n":
                    result.append(table)
    return result


def append(root, table, row):
    append_many(root, table, [row])


def append_many(root, table, rows):
    """Validate every row, then write them with one durable append."""
    if table not in TABLES:
        raise OfficeError("unknown_table", "Unknown canonical table.")
    content = b""
    for row in rows:
        check_safe(row)
        validate(table, row)
        try:
            timestamp = datetime.fromisoformat(row["as_of"].replace("Z", "+00:00"))
            if timestamp.tzinfo is None:
                raise ValueError("timezone required")
        except (KeyError, ValueError, TypeError, AttributeError) as exc:
            raise OfficeError(
                "invalid_record",
                "Every canonical row requires an RFC3339 timestamp with a timezone.",
            ) from exc
        content += (
            json.dumps(row, ensure_ascii=False, allow_nan=False, separators=(",", ":")) + "\n"
        ).encode()
    if not content:
        return
    path = contained(root, table)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_RDWR | os.O_APPEND | os.O_CREAT, 0o600)
    try:
        size = os.fstat(fd).st_size
        if size and os.pread(fd, 1, size - 1) != b"\n":
            # Drop the fragment so the new record cannot fuse with it.
            os.ftruncate(fd, os.pread(fd, size, 0).rfind(b"\n") + 1)
        view = memoryview(content)
        while view:
            written = os.write(fd, view)
            view = view[written:]
        os.fsync(fd)
    finally:
        os.close(fd)
