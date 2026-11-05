"""Web access by context level: offered only at level none, and checked, capped, logged."""

import json

import pytest

from fo.serve.runner_claude import DISALLOWED, TOOLS, WEB, ClaudeRunner
from fo.serve.runs import RunManager
from tests.offices import synthetic
from tests.serving import serving
from tests.test_serve_runs import COMPLETE, runner_for, settle


@pytest.fixture
def office(tmp_path):
    return synthetic(tmp_path / "office")


def launched(office, tmp_path, level, lines=COMPLETE):
    runner, folder = runner_for(tmp_path, lines)
    manager = RunManager(runner)
    record = settle(manager, office, manager.launch(office, "research", "BETA", level)["id"])
    argv = json.loads((folder / "argv.json").read_text())
    return manager, record, argv


def flag(argv, name):
    return argv[argv.index(name) + 1].split(",")


def init_tools(manager, office, record):
    init = next(e for e in manager.events(office, record["id"]) if e["kind"] == "init")
    return set(init["tools"])


def test_a_household_run_has_no_web_tools(office, tmp_path):
    manager, record, argv = launched(office, tmp_path, "household")
    assert record["status"] == "completed" and record["web"] is False
    assert flag(argv, "--tools") == list(TOOLS)
    assert set(WEB) <= set(flag(argv, "--disallowedTools"))
    settings = json.loads(argv[argv.index("--settings") + 1])
    assert not set(WEB) & set(settings["permissions"]["allow"])
    assert not set(WEB) & init_tools(manager, office, record)


def test_a_level_none_run_searches_and_fetches(office, tmp_path):
    manager, record, argv = launched(office, tmp_path, "none")
    assert record["status"] == "completed", record
    assert record["web"] is True
    assert set(WEB) <= set(flag(argv, "--tools")) and set(TOOLS) <= set(flag(argv, "--tools"))
    assert not set(WEB) & set(flag(argv, "--disallowedTools"))
    assert "NotebookEdit" in flag(argv, "--disallowedTools")
    settings = json.loads(argv[argv.index("--settings") + 1])
    assert set(WEB) <= set(settings["permissions"]["allow"])
    assert set(WEB) <= init_tools(manager, office, record)


def test_web_tools_at_another_level_fail_the_isolation_check(office, tmp_path):
    lines = [{"fake": "init", "tools": [*TOOLS, *WEB]}, *COMPLETE[1:]]
    _, record, _ = launched(office, tmp_path, "household", lines)
    assert record["status"] == "failed"
    assert record["error"]["reason"] == "runner_isolation"
    assert "WebFetch" in record["error"]["message"]


def test_the_isolation_check_accepts_web_tools_only_with_web():
    runner = ClaudeRunner(executable=["claude"])
    init = {
        "mcp_servers": [],
        "tools": [*TOOLS, *WEB],
        "permission_mode": "dontAsk",
        "slash_commands": ["research"],
    }
    assert runner.check(init, "research", web=True) is None
    assert "WebSearch" in runner.check(init, "research")
    assert set(DISALLOWED) - set(WEB) == {"NotebookEdit"}


def test_a_resume_derives_web_from_the_level_again(office, tmp_path):
    lines = [{"fake": "init"}, {"fake": "text", "text": "Which ticker?"}, {"fake": "result"}]
    manager, record, _ = launched(office, tmp_path, "household", lines)
    assert record["status"] == "awaiting_input"
    # A tampered record cannot widen the resumed run.
    path = office / "cache/serve/runs" / f"{record['id']}.json"
    path.write_text(json.dumps({**json.loads(path.read_text()), "web": True}))
    manager.message(office, record["id"], "ACME, please.")
    assert settle(manager, office, record["id"])["web"] is False


def test_the_preview_and_the_run_routes_carry_web(office, tmp_path):
    runner, _ = runner_for(tmp_path, COMPLETE)
    with serving(office, tmp_path, runs=RunManager(runner)) as (app, client):
        for level, web in (("none", True), ("household", False), ("full", False)):
            status, data = client.get(f"/api/advisors/research/preview?subject=ACME&level={level}")
            assert status == 200 and data["web"] is web, level
        status, record = client.post(
            "/api/runs", {"skill": "research", "subject": "BETA", "level": "none"}
        )
        assert status == 200 and record["web"] is True
        settle(app.runs, office, record["id"])
        status, detail = client.get(f"/api/runs/{record['id']}")
        assert status == 200 and detail["web"] is True and detail["level"] == "none"
