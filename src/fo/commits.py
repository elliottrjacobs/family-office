import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from fo.config import read_config
from fo.errors import OfficeError
from fo.office import git

HIDDEN = "Hidden files or folders under reports/ cannot be committed."


def check_commit_state(root):
    for marker in (
        "MERGE_HEAD",
        "REBASE_HEAD",
        "CHERRY_PICK_HEAD",
        "rebase-merge",
        "rebase-apply",
    ):
        path = Path(git(root, "rev-parse", "--git-path", marker).stdout.strip())
        if (root / path).exists():
            raise OfficeError(
                "merge_in_progress",
                "Finish or abort the Git merge or rebase in the office before fo commits.",
            )
    status = git(
        root, "status", "--porcelain", "-z", "--no-renames", "--untracked-files=all"
    ).stdout
    if any("U" in row[:2] or row[:2] in {"AA", "DD"} for row in status.split("\0") if row):
        raise OfficeError(
            "merge_in_progress",
            "Finish or abort the Git merge or rebase in the office before fo commits.",
        )
    return status


def record(root, paths, message):
    if not paths or not (root / ".git").exists():
        return
    check_commit_state(root)
    changed = any(
        git(root, "diff", *cached, "--quiet", "HEAD", "--", *paths, check=False).returncode
        for cached in ([], ["--cached"])
    )
    untracked = git(root, "ls-files", "--others", "--exclude-standard", "--", *paths).stdout
    if not changed and not untracked:
        return
    stage = [
        path
        for path in paths
        if git(root, "check-ignore", "--quiet", "--", path, check=False).returncode != 0
    ]
    if stage:
        git(root, "add", "--", *stage)
    staged = git(root, "diff", "--cached", "--no-renames", "--name-only", "-z").stdout.split("\0")
    unrelated = [
        path
        for path in staged
        if path and not any(path == p or path.startswith(p + "/") for p in paths)
    ]
    index = root / git(root, "rev-parse", "--git-path", "index").stdout.strip()
    with tempfile.TemporaryDirectory(prefix="fo-record-", dir=index.parent) as directory:
        isolated = Path(directory) / "index"
        shutil.copyfile(index, isolated)
        env = {**os.environ, "GIT_INDEX_FILE": str(isolated)}
        if unrelated:
            git(root, "reset", "-q", "HEAD", "--", *unrelated, env=env)
        git(
            root,
            "-c",
            "user.name=Family Office",
            "-c",
            "user.email=office@localhost",
            "commit",
            "-qm",
            message,
            env=env,
        )


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
    # Every untracked file is listed, so a hidden file inside a new folder is seen too.
    status = check_commit_state(root)
    for row in status.split("\0"):
        if not row:
            continue
        path = row[3:]
        if not any(path == p or path.startswith(p + "/") for p in allowed):
            raise OfficeError(
                "dirty_office",
                "Unrelated office changes must be committed or resolved before publication.",
            )
        # Hidden entries under reports/ (.claude/, .git/, ...) would reach later sessions.
        if path.startswith("reports/") and any(
            part.startswith(".") for part in path.split("/")[1:]
        ):
            raise OfficeError("unsafe_path", HIDDEN)
    # Git never lists a .git entry, but one under reports/ can turn a folder into a nested
    # repository that `git add` records as a gitlink.
    for _, directories, files in os.walk(root / "reports"):
        if ".git" in directories or ".git" in files:
            raise OfficeError("unsafe_path", HIDDEN)
    paths = [p for p in allowed if (root / p).exists()]
    git(root, "add", "--", *paths)
    changed = git(root, "diff", "--cached", "--quiet", check=False).returncode != 0
    if changed:
        # The status check above admits only allowed paths, so the index holds nothing else.
        # A pathspec would fail on an allowed folder that exists but is empty.
        git(
            root,
            "-c",
            "user.name=Family Office",
            "-c",
            "user.email=office@localhost",
            "commit",
            "-qm",
            "Record office updates",
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
