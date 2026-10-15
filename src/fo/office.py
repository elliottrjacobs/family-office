import json
import os
import subprocess
import tempfile
from pathlib import Path

from fo.errors import OfficeError

# Set by fo serve for a headless advisor run: the value is the office the run belongs to.
RUN_MARKER = "FO_SERVE_RUN"
# Commands an advisor run may never invoke: setup, credentials, account sync, publishing,
# scheduling, notifications, and rewriting derived or rendered files.
RUN_RESTRICTED = (
    "setup",
    "auth",
    "sync",
    "commit",
    "schedule",
    "notify",
    "init",
    "migrate-v1",
    "reindex",
    "skills sync",
)


def run_office(explicit: Path | None, args: list[str]) -> Path | None:
    """Pin a marked advisor run to its office and refuse restricted commands.

    args are the command words and options left after the global flags, read before
    dispatch so that flag order cannot move a command past this check. Only `sync status`
    survives the sync restriction, because it reads the sync log.
    """
    marked = os.environ.get(RUN_MARKER)
    if not marked:
        return explicit
    office = Path(marked).resolve()
    for value in (explicit, os.environ.get("FO_OFFICE")):
        if value and Path(value).expanduser().resolve() != office:
            raise OfficeError(
                "serve_run_restricted", "An advisor run may use only the office it started in."
            )
    for command in RUN_RESTRICTED:
        first, *second = command.split()
        if args[:1] == [first] and all(word in args[1:] for word in second):
            if args != ["sync", "status"]:
                raise OfficeError(
                    "serve_run_restricted",
                    "Advisor runs cannot set up, authenticate, sync, commit, schedule, "
                    "notify, migrate, or reindex.",
                )
    return office


def discover(explicit: Path | None = None) -> Path:
    value = explicit or os.environ.get("FO_OFFICE")
    candidates = (
        [Path(value).expanduser().resolve()] if value else [Path.cwd(), *Path.cwd().parents]
    )
    for root in candidates:
        if (root / "office.toml").is_file() and (root / "profile").is_dir():
            return root
    raise OfficeError("office_not_found", "Use --office PATH or run inside an initialized office.")


def contained(root: Path, relative: str) -> Path:
    target = root / relative
    if not target.resolve().is_relative_to(root.resolve()) or target.is_symlink():
        raise OfficeError("unsafe_path", "A managed path escapes the office or is a symlink.")
    return target


def atomic_write(path: Path, text: str, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".fo-", dir=path.parent)
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, "w") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def write_json(path: Path, value: object, mode: int = 0o644) -> None:
    atomic_write(path, json.dumps(value, indent=2, ensure_ascii=False) + "\n", mode)


def git(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    result = subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True, timeout=60
    )
    if check and result.returncode:
        raise OfficeError(
            "git_failed", "Git operation failed; inspect the office repository locally."
        )
    return result
