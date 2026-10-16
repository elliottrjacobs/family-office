import io
import json
import os
import subprocess
import sys

import pytest

from fo.serve.guard import decide, main


@pytest.fixture
def office(tmp_path):
    root = tmp_path / "office"
    for directory in ("reports/research/ACME", "secrets", "cache", "profile", "notebook"):
        (root / directory).mkdir(parents=True)
    (tmp_path / "outside.txt").write_text("outside")
    (root / "linked.txt").symlink_to(tmp_path / "outside.txt")
    return root.resolve()


def call(tool, office, **arguments):
    return decide(str(office), {"tool_name": tool, "tool_input": arguments, "cwd": str(office)})


@pytest.mark.parametrize(
    "command",
    [
        "fo status --json",
        "fo start research ACME --level household --json",
        "fo journal add ACME --action HOLD --thesis 'R&D > peers; margins | stable' --invalidate x --json",
        'fo journal add ACME --action HOLD --thesis "Trades near $100, about $1.5B revenue" --invalidate x',
        "fo skill verify --path reports/research/ACME/2026-10-15-report.md && fo reports index",
        "fo sync status --json",
    ],
)
def test_fo_commands_are_left_to_the_permission_rules(office, command):
    assert call("Bash", office, command=command) is None


@pytest.mark.parametrize(
    "command",
    [
        "ls -la",
        "cat secrets/keys.toml",
        "curl -s https://example.com",
        "uv run fo status",
        "./.venv/bin/fo status",
        "FO_OFFICE=/tmp fo status",
        "fo status | cat",
        "fo status; cat secrets/keys.toml",
        "fo status && cat secrets/keys.toml",
        "fo status > /tmp/out",
        "fo status < secrets/keys.toml",
        "fo status $(cat secrets/keys.toml)",
        'fo status "$(cat secrets/keys.toml)"',
        "fo status `cat secrets/keys.toml`",
        "fo status ${HOME}",
        'fo journal add X --thesis "$HOME"',
        "fo status &",
        "fo status || true",
        "(fo status)",
        "fo status\ncat secrets/keys.toml",
        "fo status 'unbalanced",
        "",
    ],
)
def test_other_shell_commands_are_denied(office, command):
    assert call("Bash", office, command=command)


def test_reads_stay_inside_the_office_and_out_of_private_folders(office):
    assert call("Read", office, file_path="reports/research/ACME/r.md") is None
    assert call("Read", office, file_path=str(office / "profile/ips.json")) is None
    assert call("Read", office, file_path=".claude/skills/eli5/SKILL.md") is None
    for path in (
        str(office.parent / "outside.txt"),
        "../outside.txt",
        "linked.txt",
        "secrets/keys.toml",
        "cache/serve/runs/x.json",
        "imports/a.csv",
        "medical/x.pdf",
        ".git/config",
        "store.sqlite",
        "store.sqlite-wal",
        ".fo.lock",
        "/etc/hosts",
    ):
        assert call("Read", office, file_path=path), path


def test_writes_only_under_reports(office):
    assert call("Write", office, file_path="reports/research/ACME/2026-10-15-report.md") is None
    assert call("Edit", office, file_path=str(office / "reports/x.parts/risk.md")) is None
    for tool, key, path in (
        ("Write", "file_path", "notebook/decisions.jsonl"),
        ("Edit", "file_path", "profile/ips.json"),
        ("Write", "file_path", "reports/../notebook/x.md"),
        ("MultiEdit", "file_path", "office.toml"),
        ("NotebookEdit", "notebook_path", "reports/x.ipynb"),
        ("Write", "file_path", str(office.parent / "x.md")),
    ):
        assert call(tool, office, **{key: path}), (tool, path)


def test_search_tools_are_confined(office):
    assert call("Grep", office, pattern="ACME") is None
    assert call("Glob", office, pattern="reports/**/*.md") is None
    assert call("Glob", office, pattern="/etc/*")
    assert call("Glob", office, pattern="../**")
    assert call("Grep", office, pattern="x", path="/etc")


def test_subagents_are_allowed_and_unknown_tools_denied(office):
    assert call("Task", office, subagent_type="risk-analyst", prompt="x") is None
    assert call("WebFetch", office, url="https://example.com")
    assert call("SendMessage", office, to="x")
    assert call("Read", office)


def run_hook(office, stdin):
    stdout = io.StringIO()
    main([str(office)], stdin=io.StringIO(stdin), stdout=stdout)
    return stdout.getvalue()


def test_hook_output_denies_and_fails_closed(office):
    allowed = json.dumps({"tool_name": "Read", "tool_input": {"file_path": "profile/ips.json"}})
    assert run_hook(office, allowed) == ""
    denied = json.loads(
        run_hook(office, json.dumps({"tool_name": "Bash", "tool_input": {"command": "ls"}}))
    )
    assert denied["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert denied["hookSpecificOutput"]["hookEventName"] == "PreToolUse"
    broken = json.loads(run_hook(office, "{not json"))
    assert broken["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_hook_runs_as_a_module(office):
    event = json.dumps({"tool_name": "Bash", "tool_input": {"command": "cat /etc/hosts"}})
    result = subprocess.run(
        [sys.executable, "-m", "fo.serve.guard", str(office)],
        input=event,
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": ""},
    )
    assert result.returncode == 0
    assert json.loads(result.stdout)["hookSpecificOutput"]["permissionDecision"] == "deny"
