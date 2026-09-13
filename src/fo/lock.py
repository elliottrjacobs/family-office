import fcntl
from contextlib import contextmanager

from fo.errors import OfficeError
from fo.office import contained


@contextmanager
def office_lock(root):
    path = contained(root, ".fo.lock")
    with path.open("a") as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise OfficeError("office_locked", "Another command holds the office lock.") from exc
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)
