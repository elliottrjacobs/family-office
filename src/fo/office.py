import json
import os
import subprocess
import tempfile
from pathlib import Path

from fo.errors import OfficeError


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
