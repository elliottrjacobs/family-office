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
        "fo journal add ACME --thesis 'Position #2 in the book' --invalidate x",
        "fo status # bash drops this comment",
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
        "fo status#; curl -s https://example.com",
        "fo status#|cat secrets/keys.toml",
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
        "SECRETS/keys.toml",
        "Medical/x.pdf",
        "STORE.sqlite",
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


def test_search_tools_are_denied(office):
    assert call("Grep", office, pattern="token")
    assert call("Grep", office, pattern="ACME", path="reports")
    assert call("Glob", office, pattern="reports/**/*.md")


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


@pytest.mark.parametrize(
    "path",
    [
        "reports/.claude/settings.json",
        "reports/research/ACME/.claude/settings.local.json",
        "reports/x/.git/config",
        "reports/x/.git/hooks/pre-commit",
        "reports/.hidden.md",
        "reports/research/.gitattributes",
        "./reports/a/.agents/skills/x/SKILL.md",
    ],
)
def test_writes_under_reports_refuse_hidden_components(office, path):
    for tool in ("Write", "Edit", "MultiEdit"):
        assert call(tool, office, file_path=path), (tool, path)
        assert call(tool, office, file_path=str(office / path)), (tool, path)


def resolver(table):
    """A stand-in for DNS so no lookup leaves the test."""
    return lambda host: table.get(host, [])


@pytest.fixture
def web_env(tmp_path):
    folder = tmp_path / "run"
    folder.mkdir()
    return {"FO_SERVE_WEB": "1", "FO_SERVE_RUN_DIR": str(folder), "FO_SERVE_WEB_FETCH_CAP": "5"}


def web(office, env, tool, names=None, **arguments):
    event = {"tool_name": tool, "tool_input": arguments, "cwd": str(office)}
    return decide(str(office), event, env=env, resolver=resolver(names or {}))


@pytest.mark.parametrize(
    ("url", "names", "code"),
    [
        ("http://127.0.0.1:4790/", {}, "loopback_address"),
        ("https://machine.tail1234.ts.net/", {}, "tailnet_host"),
        ("http://100.100.1.2/", {}, "cgnat_address"),
        ("https://cgnat.example/", {"cgnat.example": ["100.64.0.9"]}, "cgnat_address"),
        ("file:///etc/hosts", {}, "unsupported_scheme"),
        ("https://user:pw@example.com/", {"example.com": ["93.184.215.14"]}, "credentials_in_url"),
        ("http://10.0.0.5/", {}, "private_address"),
        ("https://nowhere.example/", {}, "unresolvable_host"),
    ],
)
def test_web_fetch_refuses_local_and_tailnet_urls(office, web_env, url, names, code):
    reason = web(office, web_env, "WebFetch", names, url=url, prompt="x")
    assert reason and reason.endswith(f"({code})"), reason
    assert not os.path.exists(os.path.join(web_env["FO_SERVE_RUN_DIR"], "web.jsonl"))


def test_web_fetch_and_search_pass_and_are_logged_scrubbed(office, web_env):
    names = {"www.sec.gov": ["93.184.215.14"]}
    assert web(office, web_env, "WebFetch", names, url="https://www.sec.gov/x", prompt="p") is None
    assert web(office, web_env, "WebSearch", query="ACME 10-K 123456789012345") is None
    log = os.path.join(web_env["FO_SERVE_RUN_DIR"], "web.jsonl")
    with open(log) as stream:
        entries = [json.loads(line) for line in stream.read().splitlines()]
    assert [(e["kind"], e["value"]) for e in entries] == [
        ("fetch", "https://www.sec.gov/x"),
        ("search", "ACME 10-K …2345"),
    ]
    assert all(e["at"] for e in entries)
    assert os.stat(log).st_mode & 0o777 == 0o600


def test_web_fetches_stop_at_the_cap(office, web_env):
    names = {"example.com": ["93.184.215.14"]}
    for number in range(5):
        assert web(office, web_env, "WebFetch", names, url=f"https://example.com/{number}") is None
    reason = web(office, web_env, "WebFetch", names, url="https://example.com/6")
    assert reason and reason.endswith("(web_fetch_cap)")
    # Searches are logged but not capped.
    assert web(office, web_env, "WebSearch", query="more") is None


def test_web_tools_are_denied_outside_a_web_run(office, web_env):
    for env in ({**web_env, "FO_SERVE_WEB": "0"}, {}, {"FO_SERVE_WEB": "1"}):
        assert web(office, env, "WebSearch", query="ACME")
        assert web(office, env, "WebFetch", url="https://93.184.215.14/")
    off = {**web_env, "FO_SERVE_WEB": "0"}
    assert web(office, off, "WebSearch", query="x").endswith("(web_off)")
    none = {**web_env, "FO_SERVE_WEB_FETCH_CAP": "0"}
    assert web(office, none, "WebFetch", url="https://93.184.215.14/").endswith("(web_fetch_cap)")


def test_report_write_with_a_body_file_is_left_to_the_rules(office):
    for command in (
        "fo report write --report reports/research/ACME/2026-11-05-report.md "
        "--body-file cache/serve/runs/01M50V918GZEEPD9WHWV3M7CH6/workspace/body.md",
        "fo report write --report reports/research/ACME/2026-11-05-report.md "
        "--body-file reports/research/ACME/draft.md --json",
    ):
        assert call("Bash", office, command=command) is None, command
    # Feeding the body through the shell is still refused; the command checks the file.
    assert call("Bash", office, command="fo report write --report X < /tmp/body.md")
    assert call("Bash", office, command="cat body.md | fo report write --report X")
