import fcntl
import os
import time
from contextlib import contextmanager

from fo.errors import OfficeError
from fo.office import contained


@contextmanager
def office_lock(root, wait=0.0):
    """The exclusive office lock; with wait, retry for up to that many seconds first."""
    path = contained(root, ".fo.lock")
    with path.open("a") as stream:
        deadline = time.monotonic() + wait
        while True:
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError as exc:
                if time.monotonic() >= deadline:
                    raise OfficeError(
                        "office_locked", "Another command holds the office lock."
                    ) from exc
                time.sleep(0.05)
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


def probe(root):
    """Whether another command holds the office lock.

    The lock cannot be observed without a momentary acquire and release, so a writer that
    starts during the probe fails with office_locked. Call this only when about to act on
    the answer, never on a polling path. A missing lock file means nobody holds it and is
    not created.
    """
    path = contained(root, ".fo.lock")
    try:
        fd = os.open(path, os.O_RDONLY)
    except FileNotFoundError:
        return False
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return True
    else:
        fcntl.flock(fd, fcntl.LOCK_UN)
        return False
    finally:
        os.close(fd)
