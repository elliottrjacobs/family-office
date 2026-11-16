"""Account sync from the server: when asked, and on its own when the data has gone stale.

A sync is the fo sync command, run as a subprocess of this server's interpreter, so the
writer-host rule, the office lock, and the providers' read-only adapters apply exactly
as in a terminal. One sync runs at a time. It never starts while an advisor is
answering, and an advisor message sent while it runs is queued until it ends
(RunManager.pause and resume). What a sync wrote under data/ is then recorded in the
office's history, as the scheduled job's --commit does; unrelated uncommitted changes
leave the data as it is for fo doctor to report.

Automatic sync is on unless [serve] auto_sync = false. A background thread looks once a
minute and syncs when any connected provider's last complete sync is older than
[serve] auto_sync_hours (six unless office.toml says otherwise), on the writer host
only. A sync that fails or ends incomplete is tried again after half an hour, then one
hour, doubling up to the interval, so a broken connection is not hammered and the sync
log is not flooded with failures. The answer carries each provider's status and reason,
never a provider's own error text.
"""

import platform
import subprocess
import threading
import time
from datetime import UTC, datetime

from fo.config import read_config
from fo.errors import OfficeError
from fo.lock import office_lock
from fo.serve.routes_write import command

TIMEOUT = 600
TICK = 60.0
# The first look comes soon after the server starts, once the page has loaded.
FIRST_TICK = 5.0
DEFAULT_HOURS = 6.0
RETRY_HOURS = 0.5
COMMIT_WAIT = 20.0
PROVIDERS = {"schwab", "simplefin", "plaid", "csv"}
KEYS = ("provider", "status", "reason", "message", "as_of")
# Refusals that mean "not now", not that a sync was tried and failed.
BUSY = {"run_active", "sync_active"}


def settings(root):
    """[serve] auto_sync and auto_sync_hours from office.toml."""
    serve = read_config(root).get("serve", {})
    serve = serve if isinstance(serve, dict) else {}
    auto = serve.get("auto_sync", True)
    if not isinstance(auto, bool):
        raise OfficeError("invalid_config", "[serve] auto_sync must be true or false.")
    hours = serve.get("auto_sync_hours", DEFAULT_HOURS)
    if isinstance(hours, bool) or not isinstance(hours, int | float) or hours <= 0:
        raise OfficeError("invalid_config", "[serve] auto_sync_hours must be a positive number.")
    return {"auto": auto, "hours": float(hours)}


def stamp(text):
    """Seconds since the epoch for a stored timestamp, or None when it is unreadable."""
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
    except (AttributeError, ValueError):
        return None


def iso(seconds):
    return datetime.fromtimestamp(seconds, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class Syncer:
    def __init__(self, locator, runs=None, cache=None, clock=time.time, run=command):
        self.locator = locator
        self.runs = runs
        self.cache = cache
        self.clock = clock
        self.run = run
        self.lock = threading.Lock()
        # "manual" or "auto" while a sync runs.
        self.running = None
        # The automatic attempts since the last complete sync, and when the latest began.
        self.failures = 0
        self.attempted = None
        self.stopping = threading.Event()
        self.thread = None

    # Syncing -----------------------------------------------------------------------

    def sync(self, root, automatic=False):
        """Refresh every connected account now; one row per provider, failures included."""
        if not self.lock.acquire(blocking=False):
            raise OfficeError("sync_active", "A sync is already running.")
        try:
            if self.runs is not None:
                self.runs.pause()
            self.running = "auto" if automatic else "manual"
            if automatic:
                self.attempted = self.clock()
            try:
                rows = self.pull(root, automatic)
            except OfficeError:
                self.failures += 1
                raise
            complete = all(row["status"] in ("complete", "skipped") for row in rows)
            self.failures = 0 if complete else self.failures + 1
            if any(row["status"] == "complete" for row in rows):
                self.keep(root)
            return {"complete": complete, "providers": rows}
        finally:
            self.running = None
            if self.runs is not None:
                self.runs.resume()
            if self.cache is not None:
                self.cache.forget(("/api/onboarding", ()))
            self.lock.release()

    def pull(self, root, automatic):
        args = ["sync", "--if-writer"] if automatic else ["sync"]
        try:
            _, payload = self.run(root, *args, timeout=TIMEOUT)
        except subprocess.TimeoutExpired as exc:
            raise OfficeError("sync_timeout", "The sync took too long; try again.") from exc
        if not isinstance(payload, list):
            # An error before any provider ran: not the writer host, no accounts, a held lock.
            payload = payload if isinstance(payload, dict) else {}
            raise OfficeError(payload.get("reason", "operation_failed"), payload.get("message", ""))
        return [{key: row.get(key) for key in KEYS} for row in payload if isinstance(row, dict)]

    def keep(self, root):
        """Record the synced data in the office's history; never fails the sync."""
        from fo.commits import commit_office

        try:
            with office_lock(root, wait=COMMIT_WAIT):
                commit_office(root, include_data=True)
        except (OfficeError, OSError, subprocess.SubprocessError):
            pass

    # Automatic sync ----------------------------------------------------------------

    def providers(self, root):
        """The connected providers a sync would pull, or why this host does not sync."""
        from fo.store.authored import load

        if platform.node() != read_config(root).get("hosts", {}).get("writer"):
            return set(), "not_writer"
        names = {a.get("provider") for a in load(root, "accounts")["accounts"]} & PROVIDERS
        return names, None if names else "no_accounts"

    def stale_at(self, root, names):
        """When the oldest provider's last complete sync passes the interval; 0 if never."""
        from fo.store.jsonl import read_rows

        latest = {}
        for row in read_rows(root, "data/sync_log.jsonl"):
            when = stamp(row.get("as_of"))
            if row.get("status") == "complete" and when is not None:
                latest[row.get("provider")] = max(when, latest.get(row.get("provider"), 0))
        if any(name not in latest for name in names):
            return 0.0
        return min(latest[name] for name in names) + settings(root)["hours"] * 3600

    def next_at(self, root):
        """When the next automatic sync is due, and why none is when that is None."""
        config = settings(root)
        if not config["auto"]:
            return None, "off"
        names, reason = self.providers(root)
        if reason:
            return None, reason
        due = self.stale_at(root, names)
        if self.failures and self.attempted is not None:
            wait = min(config["hours"], RETRY_HOURS * 2 ** (self.failures - 1))
            due = max(due, self.attempted + wait * 3600)
        return due, None

    def state(self, root):
        """What the page shows: a sync in progress, and when the next automatic one is."""
        try:
            config = settings(root)
            due, reason = self.next_at(root)
        except (OfficeError, OSError, ValueError, KeyError, TypeError):
            return {"running": self.running, "auto": False, "hours": None, "next": None}
        return {
            "running": self.running,
            "auto": config["auto"],
            "hours": config["hours"],
            "reason": reason,
            "next": iso(max(due, self.clock())) if due is not None else None,
        }

    def tick(self):
        """Sync when it is due; a busy office is asked again on the next tick."""
        try:
            root = self.locator.root()
            due, _ = self.next_at(root)
            if due is None or self.clock() < due:
                return False
            self.sync(root, automatic=True)
            return True
        except OfficeError as exc:
            if exc.reason in BUSY:
                # pause() and the lock refuse before anything is tried.
                return False
            return True
        except Exception:  # noqa: BLE001 - the background loop outlives any one failure
            return False

    def start(self):
        if self.thread is not None:
            return
        self.thread = threading.Thread(target=self.loop, daemon=True, name="auto-sync")
        self.thread.start()

    def loop(self):
        wait = FIRST_TICK
        while not self.stopping.wait(wait):
            self.tick()
            wait = TICK

    def stop(self):
        self.stopping.set()
