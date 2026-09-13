import shutil
import subprocess

from fo.config import read_config
from fo.errors import OfficeError
from fo.office import git


def scan_history(root):
    scanner = shutil.which("gitleaks")
    if scanner is None:
        raise OfficeError(
            "scanner_missing", "Install gitleaks before publishing the private office."
        )
    try:
        result = subprocess.run(
            [scanner, "git", "--redact", "--no-banner", str(root)], capture_output=True, timeout=120
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise OfficeError(
            "scanner_failed", "Office history scan could not complete; nothing was pushed."
        ) from exc
    if result.returncode:
        raise OfficeError(
            "history_scan_failed",
            "Office history scan failed; inspect gitleaks locally. Nothing was pushed.",
        )


def commit_office(root, include_data=False):
    allowed = ["notebook", "reports"] + (["data"] if include_data else [])
    status = git(root, "status", "--porcelain", "-z").stdout.split("\0")
    for row in status:
        if not row:
            continue
        path = row[3:]
        if not any(path == p or path.startswith(p + "/") for p in allowed):
            raise OfficeError(
                "dirty_office",
                "Unrelated office changes must be committed or resolved before publication.",
            )
    paths = [p for p in allowed if (root / p).exists()]
    git(root, "add", "--", *paths)
    changed = git(root, "diff", "--cached", "--quiet", check=False).returncode != 0
    if changed:
        git(
            root,
            "-c",
            "user.name=Family Office",
            "-c",
            "user.email=office@localhost",
            "commit",
            "-qm",
            "Record office updates",
            "--",
            *paths,
        )
    remote = read_config(root).get("hosts", {}).get("remote")
    if remote:
        if remote not in git(root, "remote").stdout.splitlines():
            raise OfficeError("unknown_remote", "Configured office remote does not exist.")
        scan_history(root)
        branch = git(root, "symbolic-ref", "--short", "HEAD").stdout.strip()
        heads = git(root, "ls-remote", "--heads", remote, "refs/heads/" + branch).stdout
        if heads:
            result = git(root, "pull", "--rebase", remote, branch, check=False)
            if result.returncode:
                raise OfficeError(
                    "rebase_failed",
                    "Rebase failed; local commits are preserved and nothing was pushed.",
                )
        from fo.store.index import reindex

        reindex(root, locked=True)
        # The remote can introduce history not present in the first scan.
        scan_history(root)
        git(root, "push", remote, "HEAD")
    return {"committed": changed, "pushed": bool(remote)}
