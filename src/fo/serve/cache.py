"""Response cache keyed by the office fingerprint.

The fingerprint reads every source file, so it is recomputed only when a cheap stat
signature (path, size, mtime) changes, and that signature is taken at most once per poll
cycle. An unchanged office therefore costs one directory walk per cycle, not a full read
per route. The store file is outside the fingerprint, so a scheduled reindex is invisible.
"""

import hashlib
import threading
import time

from fo.office import contained
from fo.store.index import fingerprint

SOURCES = ("data", "notebook", "profile", "reports")


def signature(root):
    digest = hashlib.sha256()
    for directory in SOURCES:
        for path in sorted(contained(root, directory).rglob("*")):
            stat = path.lstat()
            digest.update(
                f"{path.relative_to(root)}\0{stat.st_size}\0{stat.st_mtime_ns}\n".encode()
            )
    return digest.hexdigest()


class ResponseCache:
    def __init__(self, cycle=2.0, clock=time.monotonic):
        self.cycle = cycle
        self.clock = clock
        self.lock = threading.Lock()
        self.entries = {}
        self.root = self.stamp = self.current = None
        self.checked = float("-inf")

    def fingerprint(self, root):
        with self.lock:
            now = self.clock()
            if root != self.root:
                self.root, self.stamp, self.entries = root, None, {}
                self.checked = float("-inf")
            if now - self.checked >= self.cycle:
                stamp = signature(root)
                if stamp != self.stamp:
                    self.stamp, self.current = stamp, fingerprint(root)
                self.checked = now
            return self.current

    def get(self, root, key, compute, ttl=None):
        """A cached value for this office state; ttl also expires inputs outside it."""
        current = self.fingerprint(root)
        with self.lock:
            entry = self.entries.get(key)
        now = self.clock()
        if entry and entry[0] == current and (ttl is None or now - entry[1] < ttl):
            return entry[2]
        value = compute()
        with self.lock:
            if self.root == root:
                self.entries[key] = (current, now, value)
        return value
