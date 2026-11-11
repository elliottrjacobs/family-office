import json
import os
import subprocess
import tempfile
from pathlib import Path

from fo.errors import OfficeError

# Set by fo serve for a headless advisor run: the value is the office the run belongs to.
RUN_MARKER = "FO_SERVE_RUN"
# Commands an advisor run may never invoke: setup, credentials, account sync, publishing,
# scheduling, notifications, rewriting derived or rendered files, changing office.toml,
# and starting a server.
RUN_RESTRICTED = (
    "setup",
    "config set",
    "auth",
    "connect",
    "sync",
    "commit",
    "schedule",
    "notify",
    "init",
    "migrate-v1",
    "reindex",
    "skills sync",
    "serve",
    # Retiring a correction or settling a decision overrides the owner's own record, and
    # neither event says who wrote it, so a run may add notes but never change these.
    "corrections retire",
    "journal close",
    "journal reopen",
    "journal judge",
)


def run_office(explicit: Path | None, args: list[str]) -> Path | None:
    """Pin a marked advisor run to its office and refuse restricted commands.

    args are the command words and options left after the global flags, read before
    dispatch so that flag order cannot move a command past this check. Only `sync status`
    survives the sync restriction, because it reads the sync log. The hook's command
    policy also applies here; without that hook the CLI caps and logs research itself.
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
    # Click drops a "--" separator before dispatch, so the check drops it too; otherwise
    # `fo -- sync` would hide the command word from the comparison below.
    words = [arg for arg in args if arg != "--"]
    # The groups with restricted subcommands take no options of their own, so the
    # subcommand is the first word after the group that is not an option. Matching only
    # that word lets `fo journal add ... --action close` through.
    subcommand = [word for word in words[1:] if not word.startswith("-")][:1]
    for command in RUN_RESTRICTED:
        first, *second = command.split()
        if words[:1] == [first] and (not second or subcommand == second):
            if words != ["sync", "status"]:
                raise OfficeError(
                    "serve_run_restricted",
                    "Advisor runs cannot set up, change settings, authenticate, connect "
                    "providers, sync, commit, schedule, notify, migrate, reindex, retire "
                    "corrections, or settle decisions.",
                )
    # Import here: the guard's logging helpers also depend on office path validation.
    from fo.serve.guard import words_denial
    from fo.serve.runner import HOOK_FLAG

    try:
        reason = words_denial(args, record=os.environ.get(HOOK_FLAG) != "1")
    except (OSError, ValueError) as exc:
        raise OfficeError(
            "serve_run_restricted", "The run guard could not check this command."
        ) from exc
    if reason:
        raise OfficeError("serve_run_restricted", reason)
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


def atomic_write(path: Path, text: str | bytes, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".fo-", dir=path.parent)
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, "wb" if isinstance(text, bytes) else "w") as stream:
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
