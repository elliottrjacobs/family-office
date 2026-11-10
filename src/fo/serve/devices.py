"""Paired devices: revocable bearer tokens for the iOS app, and the codes that issue them.

A device token is 32 random bytes shown once in the pairing response and stored only as
its SHA-256 in devices.json in the per-machine credentials folder outside the office
(0600 inside a 0700 directory), so the file never holds a usable credential. Pairing
codes and login sessions live only in memory: a restart forgets them but keeps every
paired device.
"""

import hashlib
import hmac
import json
import re
import secrets
import threading
import time
from datetime import UTC, datetime

from fo.config import credentials_dir, ensure_credentials
from fo.errors import OfficeError
from fo.office import atomic_write

# No 0, O, 1, I, or L, so a code read off a screen cannot be mistyped into another one.
ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"
CODE_LENGTH = 8
CODE_TTL = 300.0
# Failed redemptions before the outstanding code is discarded.
CODE_ATTEMPTS = 10
SEEN_INTERVAL = 60.0
NAME_LIMIT = 64
DEVICE_ID = re.compile(r"dev_[0-9a-f]{12}")
FILE = "devices.json"


def digest(token):
    return hashlib.sha256(token.encode()).hexdigest()


def stamp(seconds):
    return datetime.fromtimestamp(seconds, UTC).isoformat(timespec="seconds")


def seconds(value):
    try:
        return datetime.fromisoformat(value).timestamp()
    except (TypeError, ValueError):
        return float("-inf")


def public(record):
    return {key: record.get(key) for key in ("id", "name", "created", "last_seen")}


def clean_name(value):
    if not isinstance(value, str):
        raise OfficeError("invalid_request", "name must be text.")
    value = value.strip()
    if not value or len(value) > NAME_LIMIT or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise OfficeError(
            "invalid_request", f"name must be 1 to {NAME_LIMIT} printable characters."
        )
    return value


def normalize(code):
    if not isinstance(code, str):
        return ""
    return code.replace("-", "").replace(" ", "").upper()


class Devices:
    """The paired-device registry of the office that root() returns."""

    def __init__(self, root, clock=time.time):
        self.root = root
        self.clock = clock
        self.lock = threading.Lock()
        # One outstanding code at a time: (code, expires_at, failed attempts).
        self.code = None
        # Login session cookie value -> device id.
        self.sessions = {}

    def path(self):
        return credentials_dir(self.root()) / FILE

    def load(self):
        try:
            path = self.path()
        except OfficeError as exc:
            if exc.reason == "credentials_not_migrated":
                return []
            raise
        if not path.is_file():
            return []
        try:
            value = json.loads(path.read_text())
        except ValueError as exc:
            raise OfficeError("invalid_devices", "The local devices.json is unreadable.") from exc
        records = value.get("devices") if isinstance(value, dict) else None
        if not isinstance(records, list):
            raise OfficeError("invalid_devices", "The local devices.json is unreadable.")
        return [r for r in records if isinstance(r, dict) and isinstance(r.get("id"), str)]

    def save(self, records):
        path = ensure_credentials(self.root()) / FILE
        directory = path.parent
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        directory.chmod(0o700)
        atomic_write(path, json.dumps({"devices": records}, indent=2) + "\n", 0o600)

    def issue_code(self):
        """A new pairing code; it replaces any code still outstanding."""
        code = "".join(secrets.choice(ALPHABET) for _ in range(CODE_LENGTH))
        expires = self.clock() + CODE_TTL
        with self.lock:
            self.code = (code, expires, 0)
        return {"code": code, "expires_at": stamp(expires)}

    def consume(self, code):
        """True once for the outstanding, unexpired code; every other answer is False."""
        with self.lock:
            if self.code is None:
                return False
            current, expires, failures = self.code
            if self.clock() >= expires:
                self.code = None
                return False
            if hmac.compare_digest(normalize(code).encode(), current.encode()):
                self.code = None
                return True
            failures += 1
            self.code = None if failures >= CODE_ATTEMPTS else (current, expires, failures)
            return False

    def pair(self, code, name):
        name = clean_name(name)
        # A refusal that is no fault of the code must not spend it.
        ensure_credentials(self.root())
        if not self.consume(code):
            raise OfficeError("invalid_pairing_code", "The pairing code is invalid or expired.")
        token = secrets.token_urlsafe(32)
        now = stamp(self.clock())
        record = {
            "id": "dev_" + secrets.token_hex(6),
            "name": name,
            "token_sha256": digest(token),
            "created": now,
            "last_seen": now,
        }
        with self.lock:
            self.save([*self.load(), record])
        return {"id": record["id"], "token": token, "name": name}

    def match(self, token):
        """The device record for a bearer token, or None; last_seen moves once a minute."""
        if not token:
            return None
        wanted = digest(token)
        with self.lock:
            records = self.load()
            found = next(
                (r for r in records if hmac.compare_digest(str(r.get("token_sha256", "")), wanted)),
                None,
            )
            if found is None:
                return None
            now = self.clock()
            if now - seconds(found.get("last_seen")) >= SEEN_INTERVAL:
                found["last_seen"] = stamp(now)
                self.save(records)
            return found

    def list(self):
        with self.lock:
            return [public(r) for r in self.load()]

    def revoke(self, device_id):
        if not isinstance(device_id, str) or not DEVICE_ID.fullmatch(device_id):
            raise OfficeError("device_not_found", "No such paired device.")
        with self.lock:
            records = self.load()
            kept = [r for r in records if r["id"] != device_id]
            if len(kept) == len(records):
                raise OfficeError("device_not_found", "No such paired device.")
            self.save(kept)
            self.sessions = {k: v for k, v in self.sessions.items() if v != device_id}
        return {"id": device_id, "revoked": True}

    def start_session(self, device_id):
        value = secrets.token_urlsafe(32)
        with self.lock:
            self.sessions[value] = device_id
        return value

    def session(self, value):
        """The device behind a login session cookie while it is still paired, or None."""
        if not value:
            return None
        with self.lock:
            device_id = self.sessions.get(value)
            if device_id is None:
                return None
            try:
                records = self.load()
            except OfficeError:
                return None
            found = next((r for r in records if r["id"] == device_id), None)
            if found is None:
                self.sessions.pop(value, None)
            return found
