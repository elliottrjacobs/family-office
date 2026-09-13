"""Reject private office layouts in the public Git tree; permit synthetic fixtures."""

import subprocess
from pathlib import PurePosixPath


def violations(paths):
    errors = []
    offices = {
        str(PurePosixPath(p).parent)
        for p in paths
        if p.endswith("office.toml") and not p.startswith(("tests/fixtures/", "src/fo/templates/"))
    }
    for p in paths:
        if p.startswith(("tests/fixtures/", "src/fo/templates/")):
            continue
        parts = PurePosixPath(p).parts
        if not parts:
            continue
        if (
            parts[0] in {"office", "profile", "data", "notebook", "secrets", "imports", "medical"}
            or p == "office.toml"
        ):
            errors.append(p)
        elif any(p.startswith(prefix + "/") for prefix in offices if prefix != "."):
            errors.append(p)
    return sorted(set(errors))


if __name__ == "__main__":
    paths = subprocess.check_output(["git", "ls-files", "-z"]).decode().split("\0")
    errors = violations(paths)
    for error in errors:
        print("Office path must not be tracked:", error)
    raise SystemExit(bool(errors))
