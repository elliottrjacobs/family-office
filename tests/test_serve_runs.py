import json
import os
import re
import stat
import subprocess
import sys
import time
from pathlib import Path

import pytest

from fo import notebook
from fo.brief import start
from fo.errors import OfficeError
from fo.init import initialize
from fo.lock import office_lock
from fo.office import RUN_RESTRICTED
from fo.serve.runner import profile, scrub
from fo.serve.runner_claude import MODE, TOOLS, ClaudeRunner
from fo.serve.runs import ACTIVE, RunManager
from tests.offices import synthetic

FAKE = Path(__file__).parent / "fake_claude.py"
FIXTURES = Path(__file__).parent / "fixtures"
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)


@pytest.fixture
def office(tmp_path):
    return synthetic(tmp_path / "office")


def runner_for(tmp_path, lines, name="script"):
    folder = tmp_path / name
    folder.mkdir()
    path = folder / "script.jsonl"
    path.write_text("".join(json.dumps(line) + "\n" for line in lines))
    return ClaudeRunner(executable=[sys.executable, str(FAKE), str(path)]), folder


def settle(manager, root, run_id, timeout=30):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        record = manager.get(root, run_id)
        if record["status"] not in ACTIVE and not manager.running(run_id):
            return record
        time.sleep(0.05)
    raise AssertionError("the run did not finish")


COMPLETE = [
    {"fake": "init"},
    {"fake": "start"},
    {"fake": "journal"},
    {"fake": "report"},
    {"fake": "text", "text": "Done; the report is written."},
    {"fake": "result"},
]


def test_completed_run_records_report_decision_and_session(office, tmp_path):
    runner, folder = runner_for(tmp_path, COMPLETE)
    manager = RunManager(runner)
    expected = start(office, "research", "BETA", "household")["report"]["data"]["path"]
    record = manager.launch(office, "research", "BETA", "household")
    assert record["report"] == expected and record["status"] == "queued"
    done = settle(manager, office, record["id"])
    assert done["status"] == "completed", done
    assert done["verify"] == {"valid": True, "reason": None}
    assert done["report_written"] is True
    assert done["session_id"] == "session-1"
    assert len(done["decisions"]) == 1
    assert done["decisions"][0] in {d["id"] for d in notebook.decisions(office)}
    kinds = [e["kind"] for e in manager.events(office, record["id"])]
    assert kinds[0] == "user" and "init" in kinds and "decision" in kinds and "delta" not in kinds
    assert kinds[-1] == "status"
    assert manager.events(office, record["id"])[-1]["status"] == "completed"
    argv = json.loads((folder / "argv.json").read_text())
    assert (folder / "prompts.txt").read_text().startswith("/research BETA --level household")
    assert "/research BETA --level household" not in " ".join(argv)
    assert argv[argv.index("--permission-mode") + 1] == MODE
    assert argv[argv.index("--tools") + 1] == ",".join(TOOLS)
    assert "--resume" not in argv and "bypassPermissions" not in argv


@pytest.mark.parametrize(
    ("lines", "status", "reason"),
    [
        (
            [
                {"fake": "init"},
                {"fake": "start"},
                {"fake": "journal"},
                {"fake": "text", "text": "Stopping."},
                {"fake": "result"},
            ],
            "partial",
            None,
        ),
        (
            [{"fake": "init"}, {"fake": "start"}, {"fake": "journal"}, {"fake": "exit", "code": 1}],
            "partial",
            "runner_failed",
        ),
        (
            [{"fake": "init"}, {"fake": "start"}, {"fake": "exit", "code": 2}],
            "failed",
            "runner_failed",
        ),
        (
            [{"fake": "init"}, {"fake": "text", "text": "Which ticker?"}, {"fake": "result"}],
            "awaiting_input",
            None,
        ),
        (
            [
                {"fake": "init"},
                {"fake": "text", "text": "Over budget."},
                {"fake": "result", "ok": False, "subtype": "error_max_budget_usd"},
            ],
            "failed",
            "error_max_budget_usd",
        ),
        ([{"fake": "init"}, {"fake": "result"}], "failed", "runner_failed"),
    ],
)
def test_completion_follows_the_report_then_decisions_then_exit(
    office, tmp_path, lines, status, reason
):
    manager = RunManager(runner_for(tmp_path, lines)[0])
    record = settle(manager, office, manager.launch(office, "research", "BETA")["id"])
    assert record["status"] == status, record
    assert (record["error"] or {}).get("reason") == reason


def test_a_second_launch_waits_for_the_first(office, tmp_path):
    runner, _ = runner_for(
        tmp_path,
        [
            {"fake": "init"},
            {"fake": "sleep", "seconds": 1.5},
            {"fake": "text", "text": "x"},
            {"fake": "result"},
        ],
    )
    manager = RunManager(runner)
    first = manager.launch(office, "research", "BETA")
    with pytest.raises(OfficeError) as raised:
        manager.launch(office, "lynch", "ACME")
    assert raised.value.reason == "run_active"
    settle(manager, office, first["id"])
    second = manager.launch(office, "lynch", "ACME")
    settle(manager, office, second["id"])


def test_a_held_lock_refuses_launch_and_reads_never_probe(office, tmp_path, monkeypatch):
    manager = RunManager(runner_for(tmp_path, COMPLETE)[0])
    with office_lock(office):
        with pytest.raises(OfficeError) as raised:
            manager.launch(office, "research", "BETA")
    assert raised.value.reason == "office_locked"
    assert manager.active is None and manager.list(office) == []
    probes = []
    monkeypatch.setattr("fo.serve.runs.probe", lambda root: probes.append(root) or False)
    record = settle(manager, office, manager.launch(office, "research", "BETA")["id"])
    count = len(probes)
    manager.list(office), manager.get(office, record["id"]), manager.events(office, record["id"])
    assert len(probes) == count == 1


def test_launch_validates_the_advisor_level_and_subject(office, tmp_path):
    manager = RunManager(runner_for(tmp_path, COMPLETE)[0])
    for args, reason in (
        (("nobody", "ACME"), "unknown_skill"),
        (("onboard", "household"), "not_in_chat"),
        (("journal", "ACME"), "not_in_chat"),
        (("research", "ACME", "everything"), "invalid_context"),
        (("research", "../x"), "invalid_path"),
        (("lynch", "ACME", None, True), "deep_unavailable"),
        (("research", "ACME", None, True), "deep_unavailable"),
    ):
        with pytest.raises(OfficeError) as raised:
            manager.launch(office, *args)
        assert raised.value.reason == reason, args
    assert manager.active is None


def test_an_unisolated_session_is_stopped(office, tmp_path):
    lines = [
        {
            "fake": "init",
            "mcp_servers": [{"name": "personal", "status": "connected"}],
            "tools": [*TOOLS, "mcp__personal__read"],
        },
        {"fake": "sleep", "seconds": 5},
        {"fake": "result"},
    ]
    manager = RunManager(runner_for(tmp_path, lines)[0], grace=0.5)
    started = time.monotonic()
    record = settle(manager, office, manager.launch(office, "research", "BETA")["id"])
    assert time.monotonic() - started < 4
    assert record["status"] == "failed"
    assert record["error"]["reason"] == "runner_isolation"
    assert (
        "MCP servers" in record["error"]["message"]
        and "mcp__personal__read" in record["error"]["message"]
    )


def test_a_skill_that_was_not_discovered_stops_the_run(office, tmp_path):
    lines = [
        {"fake": "init", "slash_commands": ["clear"]},
        {"fake": "sleep", "seconds": 5},
        {"fake": "result"},
    ]
    manager = RunManager(runner_for(tmp_path, lines)[0], grace=0.5)
    record = settle(manager, office, manager.launch(office, "research", "BETA")["id"])
    assert (
        record["status"] == "failed"
        and "research skill was not found" in record["error"]["message"]
    )


def test_cancel_stops_the_process_and_keeps_the_session(office, tmp_path):
    lines = [{"fake": "init"}, {"fake": "sleep", "seconds": 30}, {"fake": "result"}]
    manager = RunManager(runner_for(tmp_path, lines)[0], grace=0.5)
    record = manager.launch(office, "research", "BETA")
    deadline = time.monotonic() + 10
    while manager.get(office, record["id"])["session_id"] is None and time.monotonic() < deadline:
        time.sleep(0.05)
    pid = manager.get(office, record["id"])["pid"]
    manager.cancel(office, record["id"])
    done = settle(manager, office, record["id"])
    assert done["status"] == "cancelled" and done["session_id"] == "session-1"
    time.sleep(0.2)
    with pytest.raises(OSError):
        os.kill(pid, 0)
    with pytest.raises(OfficeError):
        manager.cancel(office, record["id"])


def test_a_run_that_runs_too_long_is_stopped(office, tmp_path):
    config = office / "office.toml"
    config.write_text(
        config.read_text().replace("run_timeout_minutes = 30", "run_timeout_minutes = 0.01")
    )
    lines = [{"fake": "init"}, {"fake": "sleep", "seconds": 30}, {"fake": "result"}]
    manager = RunManager(runner_for(tmp_path, lines)[0], grace=0.5)
    record = settle(manager, office, manager.launch(office, "research", "BETA")["id"])
    assert record["status"] == "failed" and record["error"]["reason"] == "run_timeout"


def test_a_partial_run_resumes_on_its_report_without_duplicate_decisions(office, tmp_path):
    first, folder = runner_for(
        tmp_path,
        [{"fake": "init"}, {"fake": "start"}, {"fake": "journal"}, {"fake": "exit", "code": 1}],
        "first",
    )
    manager = RunManager(first)
    record = settle(manager, office, manager.launch(office, "research", "BETA", "household")["id"])
    assert record["status"] == "partial"
    second, folder = runner_for(
        tmp_path,
        [
            {"fake": "init"},
            {"fake": "start"},
            {"fake": "report"},
            {"fake": "text", "text": "Finished."},
            {"fake": "result"},
        ],
        "second",
    )
    manager.runner = second
    with pytest.raises(OfficeError):
        manager.message(office, record["id"], "x" * 9000)
    manager.message(office, record["id"], "")
    done = settle(manager, office, record["id"])
    prompt = (folder / "prompts.txt").read_text()
    assert f"--report {record['report']}" in prompt
    assert "fo start, fo report path, and fo report parts" in prompt
    argv = json.loads((folder / "argv.json").read_text())
    assert argv[argv.index("--resume") + 1] == "session-1"
    assert done["status"] == "completed", done
    assert done["report"] == record["report"]
    assert len([d for d in notebook.decisions(office) if d["subject"] == "BETA"]) == 1


def test_follow_ups_need_a_session_and_an_idle_run(office, tmp_path):
    lines = [{"fake": "init"}, {"fake": "text", "text": "Which ticker?"}, {"fake": "result"}]
    manager = RunManager(runner_for(tmp_path, lines)[0])
    record = settle(manager, office, manager.launch(office, "research", "BETA")["id"])
    with pytest.raises(OfficeError) as raised:
        manager.message(office, record["id"], " ")
    assert raised.value.reason == "invalid_request"
    manager.message(office, record["id"], "BETA, please.")
    assert settle(manager, office, record["id"])["status"] == "awaiting_input"
    texts = [e["text"] for e in manager.events(office, record["id"]) if e["kind"] == "user"]
    assert texts[-1] == "BETA, please."
    with pytest.raises(OfficeError):
        manager.get(office, "../../secrets")


def test_a_run_left_running_is_reconciled(office, tmp_path):
    manager = RunManager(runner_for(tmp_path, COMPLETE)[0])
    record = settle(manager, office, manager.launch(office, "research", "BETA")["id"])
    record.update(status="running", pid=2**22 + 7, verify=None)
    manager.save(office, record)
    restarted = RunManager(runner_for(tmp_path, COMPLETE, "again")[0])
    done = restarted.get(office, record["id"])
    assert done["status"] == "completed"
    assert done["error"]["reason"] == "server_restarted"
    seqs = [e["seq"] for e in restarted.events(office, record["id"])]
    assert seqs == sorted(set(seqs))


def test_wait_streams_live_events_then_replays_from_the_log(office, tmp_path):
    lines = [
        {"fake": "init"},
        {"fake": "sleep", "seconds": 0.5},
        {"fake": "text", "text": "Streaming text."},
        {"fake": "result"},
    ]
    manager = RunManager(runner_for(tmp_path, lines)[0])
    record = manager.launch(office, "research", "BETA")
    seen, after, live = [], 0, True
    while live:
        events, live = manager.wait(office, record["id"], after, timeout=5)
        seen += events
        after = max([after, *(e["seq"] for e in events)])
    kinds = [e["kind"] for e in seen]
    assert "delta" in kinds and "text" in kinds and kinds[-1] == "status"
    assert manager.wait(office, record["id"], 0, timeout=1)[1] is False
    assert "delta" not in [e["kind"] for e in manager.events(office, record["id"])]


def test_run_files_are_private_scrubbed_and_pruned(office, tmp_path):
    config = office / "office.toml"
    config.write_text(config.read_text().replace("keep_runs = 50", "keep_runs = 2"))
    secret = "https://user:pass@example.invalid/x and account 123456789012345 worth 12345678"
    lines = [{"fake": "init"}, {"fake": "text", "text": secret}, {"fake": "result"}]
    manager = RunManager(runner_for(tmp_path, lines)[0])
    ids = [
        settle(manager, office, manager.launch(office, "research", "BETA")["id"])["id"]
        for _ in range(3)
    ]
    folder = office / "cache/serve/runs"
    assert stat.S_IMODE(folder.stat().st_mode) == 0o700
    assert stat.S_IMODE((office / "cache/serve").stat().st_mode) == 0o700
    files = sorted(folder.iterdir())
    assert {f.stem for f in files} == set(ids[1:])
    assert all(stat.S_IMODE(f.stat().st_mode) == 0o600 for f in files)
    text = "".join(f.read_text() for f in files)
    assert "user:pass" not in text and "123456789012345" not in text
    assert "…2345" in text and "12345678" in text
    for key in ("HOME", "PATH", "FO_SERVE_RUN"):
        assert key not in text
    assert scrub({"accessToken": "x", "nested": [{"api_key": "y", "ok": "fine"}]}) == {
        "nested": [{"ok": "fine"}]
    }


def test_preflight_refuses_old_or_incomplete_claude(tmp_path):
    runner, folder = runner_for(tmp_path, [])
    assert runner.preflight()["version"] == "2.1.283"
    (folder / "version").write_text("2.0.9 (Claude Code)")
    with pytest.raises(OfficeError) as raised:
        runner.preflight()
    assert raised.value.reason == "runner_outdated"
    (folder / "version").unlink()
    (folder / "missing").write_text("--permission-prompts --strict-mcp-config")
    with pytest.raises(OfficeError) as raised:
        runner.preflight()
    assert raised.value.reason == "runner_unsupported"
    assert "--permission-prompts" in raised.value.message
    with pytest.raises(OfficeError) as raised:
        ClaudeRunner(executable=[]).preflight()
    assert raised.value.reason == "runner_missing"
    with pytest.raises(OfficeError) as raised:
        ClaudeRunner(executable=[str(tmp_path / "missing-claude")]).preflight()
    assert raised.value.reason == "runner_missing"


def test_a_failed_preflight_never_starts_a_run(office, tmp_path):
    runner, folder = runner_for(tmp_path, COMPLETE)
    (folder / "version").write_text("1.0.0")
    manager = RunManager(runner)
    with pytest.raises(OfficeError):
        manager.launch(office, "research", "BETA")
    assert manager.active is None and manager.list(office) == []


def test_environment_is_scrubbed_and_pins_the_office(office, monkeypatch):
    monkeypatch.setenv("SECRET_THING", "x")
    monkeypatch.setenv("FO_OFFICE", "/elsewhere")
    env = ClaudeRunner(executable=["/opt/claude/bin/claude"]).environment(office)
    assert env["FO_SERVE_RUN"] == env["FO_OFFICE"] == str(office)
    assert "SECRET_THING" not in env
    assert env["PATH"].split(os.pathsep)[0] == str(Path(sys.executable).parent)
    assert "/opt/claude/bin" in env["PATH"]


def test_settings_carry_the_profile_and_the_guard_hook(office):
    settings = json.loads(ClaudeRunner(executable=["claude"]).settings(office))
    assert settings["permissions"]["deny"] == profile()["deny"]
    command = settings["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
    assert "-m fo.serve.guard" in command and str(office) in command
    event = json.dumps({"tool_name": "Read", "tool_input": {"file_path": "/etc/hosts"}})
    result = subprocess.run(command, shell=True, input=event, capture_output=True, text=True)
    assert json.loads(result.stdout)["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_profile_covers_office_settings_and_restricted_commands(tmp_path):
    root = tmp_path / "office"
    initialize(root)
    office = json.loads((root / ".claude/settings.json").read_text())["permissions"]
    rules = profile()
    assert set(office["deny"]) <= set(rules["deny"])
    for command in RUN_RESTRICTED:
        tail = "-*" if command == "sync" else "*"
        assert {f"Bash(fo {command})", f"Bash(fo {command} {tail})"} <= set(rules["deny"]), command
    required = [
        "Read(secrets/**)",
        "Read(cache/**)",
        "Read(imports/**)",
        "Read(medical/**)",
        "Read(.git/**)",
        "Read(store.sqlite*)",
        "WebFetch",
        "WebSearch",
        "Bash(curl *)",
        "Bash(wget *)",
        "Bash(python *)",
        "Bash(ssh *)",
        "Bash(open *)",
        "Bash(osascript *)",
        "Bash(git push *)",
    ]
    assert set(required) <= set(rules["deny"])
    assert all(
        rule.startswith(("Bash(fo ", "Read(./", "Edit(./reports/", "Write(./reports/"))
        for rule in rules["allow"]
    )
    assert not any(rule.startswith(("Bash(fo sync", "Bash(fo auth")) for rule in rules["allow"])
    for path in Path("src/fo/serve").rglob("*"):
        if path.is_file() and path.name != "permission_profile.json":
            assert "bypass" not in path.read_text(errors="ignore").lower(), path


def test_parser_reads_a_recorded_run():
    runner = ClaudeRunner(executable=["claude"])
    events = [
        e
        for line in (FIXTURES / "stream-json/eli5.jsonl").read_text().splitlines()
        for e in runner.parse(line, Path("/office"))
    ]
    kinds = {e["kind"] for e in events}
    assert kinds >= {"init", "text", "tool", "tool_result", "delta", "result"}
    init = next(e for e in events if e["kind"] == "init")
    assert runner.check(init, "eli5") is None
    assert init["session_id"] == "session-1" and init["permission_mode"] == MODE
    tools = [e for e in events if e["kind"] == "tool"]
    assert tools[0]["name"] == "Bash" and tools[0]["command"].startswith("fo start eli5")
    assert any(e["name"] == "Write" and e["path"].startswith("reports/eli5/") for e in tools)
    results = [e for e in events if e["kind"] == "tool_result"]
    assert {e["id"] for e in results} <= {e["id"] for e in tools}
    result = next(e for e in events if e["kind"] == "result")
    assert result["ok"] and result["turns"] and result["cost_usd"] > 0
    assert runner.parse("not json", Path("/office")) == runner.parse("[1]", Path("/office")) == []


def test_fixtures_hold_no_home_paths_or_uuids():
    for path in FIXTURES.rglob("*"):
        if path.is_file():
            text = path.read_text(errors="ignore")
            assert not re.search(r"/(Users|home)/[^/\s]+", text), path
            assert not UUID.search(text), path
