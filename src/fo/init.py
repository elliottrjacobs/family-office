import json
import platform
from pathlib import Path

from fo import __version__
from fo.errors import OfficeError
from fo.office import atomic_write, git, write_json

OFFICE_IGNORE = """secrets/
cache/
imports/
medical/
store.sqlite*
.fo.lock
.venv/
.agents/skills/
.claude/skills/
.claude/agents/
.codex/agents/
__pycache__/
"""
HOOK = """#!/usr/bin/env python3
import subprocess
import sys
blocked = ("secrets/", "cache/", "imports/", "medical/", ".agents/skills/", ".claude/skills/", ".claude/agents/", ".codex/agents/")
paths = subprocess.check_output(["git", "diff", "--cached", "--name-only", "-z"]).decode().split("\\0")
if any(p.startswith(blocked) for p in paths if p):
    print("Blocked staged private path.", file=sys.stderr)
    sys.exit(1)
import shutil
if shutil.which("gitleaks"):
    sys.exit(subprocess.call(["gitleaks", "protect", "--staged", "--redact", "--no-banner"]))
"""


def initialize(path: Path):
    original = path.expanduser().absolute()
    if original.is_symlink():
        raise OfficeError("unsafe_path", "Choose a local directory without symlink components.")
    root = original.resolve()
    if (root / "office.toml").is_file():
        return {"office": str(root), "created": False, "reason": "already_initialized"}
    for parent in [root, *root.parents]:
        if (parent / ".git").exists():
            raise OfficeError(
                "nested_repository",
                "An office must be a separate repository outside the code checkout.",
            )
    if root.exists() and any(root.iterdir()):
        raise OfficeError("target_not_empty", "Initialize an empty directory.")
    root.mkdir(parents=True, exist_ok=True)
    for directory in (
        "profile",
        "data",
        "notebook/reviews",
        "reports",
        "imports",
        "medical",
        "cache",
        "playbooks/overrides",
        "hooks",
        ".claude",
        ".codex",
        "secrets",
    ):
        (root / directory).mkdir(parents=True, exist_ok=True)
    (root / "secrets").chmod(0o700)
    atomic_write(
        root / "office.toml",
        f"""[office]
timezone = "America/New_York"

[hosts]
writer = {json.dumps(platform.node())}
remote = ""

[schedule]
sync_hours = 24

[notebook]
verdict_days = 180

[models.claude]
fast = {{model = "haiku", effort = "low"}}
balanced = {{model = "sonnet", effort = "high"}}
strong = {{model = "opus", effort = "high"}}

[models.codex]
fast = {{model = "gpt-5.6-luna", effort = "low"}}
balanced = {{model = "gpt-5.6-sol", effort = "high"}}
strong = {{model = "gpt-6-astra", effort = "high"}}

[providers.alphavantage]
daily_limit = 25
""",
    )
    examples = {
        "ips": {"bands": [], "prohibitions": []},
        "goals": {"goals": []},
        "tax": {"notes": []},
        "accounts": {"accounts": []},
    }
    for name, value in examples.items():
        write_json(root / f"profile/{name}.json", value)
    atomic_write(
        root / "profile/household.md",
        '# Household\n\nComplete with the onboard skill.\n\n```json\n{"members": [], "businesses": []}\n```\n',
    )
    atomic_write(root / "profile/categories.yaml", "rules: []\n")
    atomic_write(root / "profile/universes.yaml", "universes: {}\n")
    for table in ("accounts", "positions", "balances", "transactions", "sync_log", "voids"):
        atomic_write(root / f"data/{table}.jsonl", "")
    for table in ("decisions", "reviews"):
        atomic_write(root / f"notebook/{table}.jsonl", "")
    atomic_write(root / "notebook/corrections.md", "# Standing corrections\n")
    atomic_write(root / ".gitignore", OFFICE_IGNORE)
    atomic_write(
        root / ".gitattributes", "*.jsonl merge=union\nnotebook/corrections.md merge=union\n"
    )
    atomic_write(root / "hooks/pre-commit", HOOK, 0o755)
    atomic_write(
        root / "pyproject.toml",
        """[project]
name = "private-office"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = ["family-office"]

[tool.uv.sources]
family-office = {git = "https://github.com/elliottrjacobs/family-office.git", tag = "PACKAGE_TAG"}
""".replace("PACKAGE_TAG", "v" + __version__),
    )
    write_json(
        root / ".claude/settings.json",
        {
            "permissions": {
                "allow": ["Bash(uv run fo *)", "Bash(fo *)", "Read", "Edit(reports/**)"],
                "deny": [
                    "Read(secrets/**)",
                    "Edit(data/**)",
                    "Edit(notebook/**)",
                    "Bash(python *)",
                    "Bash(python3 *)",
                    "Bash(uv run python *)",
                    "Bash(curl *)",
                    "Bash(pip *)",
                    "Bash(git push *)",
                ],
            }
        },
    )
    atomic_write(
        root / ".codex/config.toml",
        'sandbox_mode = "workspace-write"\napproval_policy = "on-request"\nmodel = "gpt-5.6-sol"\nmodel_reasoning_effort = "high"\n',
    )
    from fo.skills import sync

    sync(root)
    git(root, "init", "-q")
    git(root, "config", "core.hooksPath", "hooks")
    paths = [
        "office.toml",
        "pyproject.toml",
        "AGENTS.md",
        "CLAUDE.md",
        ".gitignore",
        ".gitattributes",
        "profile",
        "data",
        "notebook",
        "hooks",
        ".claude/settings.json",
        ".codex/config.toml",
    ]
    git(root, "add", "--", *paths)
    git(
        root,
        "-c",
        "user.name=Family Office",
        "-c",
        "user.email=office@localhost",
        "commit",
        "-qm",
        "Initialize private office",
        "--",
        *paths,
    )
    return {"office": str(root), "created": True}
