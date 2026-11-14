"""Conversations with an advisor: free messages, web on by default, history, onboarding."""

import json
import subprocess
import sys

import pytest

from fo.config import set_config
from fo.errors import OfficeError
from fo.serve import refresh_skills
from fo.serve.guard import decide
from fo.serve.onboarding import derive
from fo.serve.runner_claude import TOOLS, WEB, ClaudeRunner
from fo.serve.runner_codex import CodexRunner
from fo.serve.runs import RunManager, title, web_allowed, web_scope
from fo.serve.server import Locator
from fo.skills import freshness
from tests.offices import synthetic
from tests.serving import serving
from tests.test_serve_runs import runner_for, settle

ANSWER = [{"fake": "init"}, {"fake": "text", "text": "Here is the answer."}, {"fake": "result"}]
QUESTION = "What is the tax impact of selling BETA this year?"


@pytest.fixture
def office(tmp_path):
    return synthetic(tmp_path / "office")


def conversation(office, tmp_path, lines=ANSWER, skill="cio", name="script", **options):
    runner, folder = runner_for(tmp_path, lines, name)
    manager = RunManager(runner)
    record = manager.launch(office, skill, message=QUESTION, **options)
    return manager, settle(manager, office, record["id"]), folder


def argv(folder):
    return json.loads((folder / "argv.json").read_text())


def flag(arguments, name):
    return arguments[arguments.index(name) + 1].split(",")


def hook(office, tmp_path, tool, scope="household", skill=None, web="1", **arguments):
    folder = tmp_path / "run"
    folder.mkdir(exist_ok=True)
    env = {
        "FO_SERVE_WEB": web,
        "FO_SERVE_WEB_SCOPE": scope,
        "FO_SERVE_RUN_DIR": str(folder),
        "FO_SERVE_WEB_FETCH_CAP": "5",
    }
    if skill:
        env["FO_SERVE_SKILL"] = skill
    event = {"tool_name": tool, "tool_input": arguments, "cwd": str(office)}
    return decide(str(office), event, env, lambda host: ["93.184.215.14"])


@pytest.mark.parametrize(
    ("level", "policy", "wanted", "household", "expected"),
    [
        ("none", "on", None, True, True),
        ("full", "on", None, True, True),
        ("household", "on", True, True, True),
        ("full", "on", False, True, False),
        ("none", "on", False, True, False),
        # Codex confines reads by command, so web never meets household data there.
        ("full", "on", None, False, False),
        ("none", "on", None, False, True),
        ("none", "isolated", None, True, True),
        ("full", "isolated", True, True, False),
        ("none", "off", True, True, False),
        ("full", "off", True, True, False),
    ],
)
def test_web_follows_the_policy_the_level_and_the_switch(
    level, policy, wanted, household, expected
):
    assert web_allowed(level, policy, wanted, household) is expected


def test_web_scope_and_the_engines():
    assert web_scope("none") == "isolated"
    assert web_scope("household") == web_scope("full") == "household"
    assert ClaudeRunner.web_household is True and ClaudeRunner.profile_writes is True
    assert getattr(CodexRunner, "web_household", False) is False
    assert getattr(CodexRunner, "profile_writes", False) is False


def test_a_conversation_sends_the_message_and_waits_for_the_next(office, tmp_path):
    manager, record, folder = conversation(office, tmp_path)
    assert record["status"] == "awaiting_input", record
    assert record["mode"] == "chat" and record["title"] == QUESTION
    assert record["report"] == "" and record["verify"] is None and record["error"] is None
    assert record["subject"] == "household" and record["level"] == "full"
    events = manager.events(office, record["id"])
    # The history shows what the user typed, not the instructions wrapped around it.
    assert events[0] == {**events[0], "kind": "user", "text": QUESTION}
    assert "verifying" not in [e.get("status") for e in events]
    prompt = (folder / "prompts.txt").read_text()
    assert prompt.startswith("/cio household --level full\n")
    assert "This is a conversation" in prompt and "Web search and fetch are on" in prompt
    assert prompt.rstrip("\n-").endswith(QUESTION)
    assert QUESTION not in " ".join(argv(folder))


def test_a_conversation_has_web_at_a_household_level_by_default(office, tmp_path):
    _, record, folder = conversation(office, tmp_path)
    assert record["web"] is True and record["web_wanted"] is None
    arguments = argv(folder)
    assert flag(arguments, "--tools") == [*TOOLS, *WEB]
    assert not set(WEB) & set(flag(arguments, "--disallowedTools"))
    settings = json.loads(arguments[arguments.index("--settings") + 1])
    assert set(WEB) <= set(settings["permissions"]["allow"])


def test_the_switch_and_the_policy_turn_web_off(office, tmp_path):
    _, record, folder = conversation(office, tmp_path, web=False)
    assert record["web"] is False and record["web_wanted"] is False
    assert flag(argv(folder), "--tools") == list(TOOLS)
    assert "Web search and fetch are off" in (folder / "prompts.txt").read_text()
    set_config(office, "serve.web", "off")
    _, record, folder = conversation(office, tmp_path, name="off", web=True)
    assert record["web"] is False and flag(argv(folder), "--tools") == list(TOOLS)
    (office / "office.toml").write_text(
        (office / "office.toml").read_text().replace('web = "off"', 'web = "sometimes"')
    )
    with pytest.raises(OfficeError) as raised:
        conversation(office, tmp_path, name="invalid")
    assert raised.value.reason == "invalid_config"


def test_a_follow_up_can_switch_web_and_tells_the_session(office, tmp_path):
    manager, record, folder = conversation(office, tmp_path)
    manager.message(office, record["id"], "And next year?", web=False)
    done = settle(manager, office, record["id"])
    assert done["status"] == "awaiting_input" and done["web"] is False
    arguments = argv(folder)
    assert flag(arguments, "--tools") == list(TOOLS)
    assert arguments[arguments.index("--resume") + 1] == "session-1"
    turns = (folder / "prompts.txt").read_text().split("\n---\n")
    assert turns[1] == "(Web search and fetch are now off for this conversation.)\n\nAnd next year?"
    users = [e["text"] for e in manager.events(office, record["id"]) if e["kind"] == "user"]
    assert users == [QUESTION, "And next year?"]
    # Without a change the message goes as typed.
    manager.message(office, record["id"], "Thanks.")
    settle(manager, office, record["id"])
    assert (folder / "prompts.txt").read_text().split("\n---\n")[2] == "Thanks."
    with pytest.raises(OfficeError) as raised:
        manager.message(office, record["id"], "   ")
    assert raised.value.reason == "invalid_request"


def test_a_conversation_that_files_a_report_is_completed(office, tmp_path):
    lines = [
        {"fake": "init"},
        {"fake": "start"},
        {"fake": "filed"},
        {"fake": "text", "text": "Saved the report."},
        {"fake": "result"},
    ]
    manager, record, _ = conversation(office, tmp_path, lines)
    assert record["status"] == "completed", record
    assert record["report"].startswith("reports/cio/household/") and record["report_written"]
    assert record["verify"] == {"valid": True, "reason": None}
    assert (office / record["report"]).is_file()
    # The conversation goes on after its report.
    manager.message(office, record["id"], "Shorter, please.")
    assert settle(manager, office, record["id"])["status"] == "completed"


def test_a_conversation_without_an_answer_failed(office, tmp_path):
    _, record, _ = conversation(office, tmp_path, [{"fake": "init"}, {"fake": "result"}])
    assert record["status"] == "failed"
    assert record["error"]["message"] == "The advisor ended without an answer."
    lines = [
        {"fake": "init"},
        {"fake": "text", "text": "Partway."},
        {"fake": "result", "ok": False, "subtype": "error_max_budget_usd"},
    ]
    _, record, _ = conversation(office, tmp_path, lines, name="budget")
    assert record["status"] == "failed" and "spending limit" in record["error"]["message"]


def test_the_fetch_cap_counts_one_turn(office, tmp_path):
    set_config(office, "serve.web_fetch_cap", "2")
    fetches = [
        {"fake": "hook", "tool": "WebFetch", "input": {"url": f"https://93.184.215.14/{n}"}}
        for n in range(3)
    ]
    lines = [{"fake": "init"}, *fetches, {"fake": "text", "text": "Read them."}, {"fake": "result"}]
    manager, record, _ = conversation(office, tmp_path, lines)
    assert record["web_count"] == 2
    manager.message(office, record["id"], "Look again.")
    done = settle(manager, office, record["id"])
    assert done["web_count"] == 4
    visits = [e["value"] for e in manager.events(office, record["id"]) if e["kind"] == "web"]
    assert visits == [f"https://93.184.215.14/{n}" for n in (0, 1, 0, 1)]


def test_a_household_web_run_reads_the_office_and_limits_what_it_sends(office, tmp_path):
    assert hook(office, tmp_path, "Read", file_path="profile/accounts.json") is None
    assert hook(office, tmp_path, "Bash", command="fo networth --json") is None
    assert hook(office, tmp_path, "Bash", command="fo start tax household --level full") is None
    assert hook(office, tmp_path, "WebSearch", query="2026 401k contribution limit") is None
    assert (
        hook(office, tmp_path, "WebFetch", url="https://www.irs.gov/pub/irs-pdf/p550.pdf") is None
    )
    log = [json.loads(line) for line in (tmp_path / "run/web.jsonl").read_text().splitlines()]
    assert [(entry["kind"], entry["value"]) for entry in log] == [
        ("search", "2026 401k contribution limit"),
        ("fetch", "https://www.irs.gov/pub/irs-pdf/p550.pdf"),
    ]
    for query in ("account 123456789 balance", "ssn 123-45-6789", "x" * 401):
        reason = hook(office, tmp_path, "WebSearch", query=query)
        assert reason and reason.endswith(("(web_identifier)", "(web_too_long)")), query
    assert hook(office, tmp_path, "WebFetch", url="https://example.com/" + "a" * 600).endswith(
        "(web_too_long)"
    )
    assert hook(office, tmp_path, "WebFetch", url="http://127.0.0.1/x") is not None
    assert len((tmp_path / "run/web.jsonl").read_text().splitlines()) == 2
    # Private folders stay private, and writes stay under reports/.
    assert hook(office, tmp_path, "Read", file_path="secrets/keys.toml")
    assert hook(office, tmp_path, "Write", file_path="profile/tax.json", content="{}")
    # At level none the run stays isolated from household data, as before.
    assert hook(office, tmp_path, "Read", scope="isolated", file_path="profile/accounts.json")
    assert hook(office, tmp_path, "Bash", scope="isolated", command="fo networth --json")
    assert hook(office, tmp_path, "WebSearch", web="0", query="anything").endswith("(web_off)")


def test_fo_reads_the_household_in_a_household_web_run(office, tmp_path):
    def brief(scope):
        env = {
            "PATH": str(tmp_path),
            "FO_SERVE_RUN": str(office),
            "FO_SERVE_WEB": "1",
            "FO_SERVE_WEB_SCOPE": scope,
            "FO_SERVE_HOOK_ACTIVE": "1",
        }
        arguments = ["--json", "--office", str(office), "brief", "--level", "household"]
        result = subprocess.run(
            [sys.executable, "-m", "fo.cli", *arguments], capture_output=True, text=True, env=env
        )
        return result.returncode, json.loads(result.stdout)

    code, data = brief("household")
    assert code == 0 and data["level"] == "household" and "holdings" in data
    code, data = brief("isolated")
    assert code != 0 and data["reason"] == "serve_run_restricted"


def test_the_onboard_interview_runs_in_the_app_and_writes_the_profile(office, tmp_path):
    lines = [
        {"fake": "init"},
        {
            "fake": "hook",
            "tool": "Write",
            "input": {"file_path": "profile/tax.json", "content": '{"notes": []}'},
        },
        {"fake": "hook", "tool": "Write", "input": {"file_path": "office.toml", "content": "x"}},
        {"fake": "text", "text": "Who is in the household?"},
        {"fake": "result"},
    ]
    # What the interview leaves under profile/ is recorded once the turn ends.
    (office / "profile/household.md").write_text("# Household\n\nTwo adults, one child.\n")
    (office / "office.toml").write_text((office / "office.toml").read_text() + "\n# mine\n")
    manager, record, folder = conversation(office, tmp_path, lines, skill="onboard")
    assert record["status"] == "awaiting_input", record
    status = subprocess.run(
        ["git", "status", "--porcelain"], cwd=office, capture_output=True, text=True
    ).stdout
    assert "profile/" not in status and "office.toml" in status
    last = subprocess.run(
        ["git", "log", "-1", "--format=%s", "--name-only"],
        cwd=office,
        capture_output=True,
        text=True,
    ).stdout.split()
    assert last[-1] == "profile/household.md" and "interview" in last
    prompt = (folder / "prompts.txt").read_text()
    assert prompt.startswith("/onboard household --level full\n")
    assert "intake interview" in prompt and "Never ask the user to open a terminal" in prompt
    arguments = argv(folder)
    settings = json.loads(arguments[arguments.index("--settings") + 1])
    assert "Edit(./profile/**)" in settings["permissions"]["allow"]
    assert "Edit(profile/**)" not in settings["permissions"]["deny"]
    assert "Edit(data/**)" in settings["permissions"]["deny"]
    result = next(e for e in manager.events(office, record["id"]) if e["kind"] == "result")
    assert [d["label"] for d in result["denials"]] == ["Write office.toml"]
    # Every other advisor keeps the profile read-only, in the rules and in the hook.
    _, _, folder = conversation(office, tmp_path, name="cio")
    arguments = argv(folder)
    settings = json.loads(arguments[arguments.index("--settings") + 1])
    assert "Edit(profile/**)" in settings["permissions"]["deny"]
    assert "Edit(./profile/**)" not in settings["permissions"]["allow"]
    for path in ("profile/.claude/settings.json", "data/balances.jsonl", "notebook/x.md"):
        assert hook(office, tmp_path, "Write", skill="onboard", file_path=path, content="x"), path
    assert hook(office, tmp_path, "Edit", skill="onboard", file_path="profile/goals.json") is None
    assert hook(office, tmp_path, "Edit", skill="cio", file_path="profile/goals.json")


def test_the_history_lists_and_deletes_conversations_through_the_api(office, tmp_path):
    lines = [
        {"fake": "init"},
        {"fake": "text", "text": "Thinking."},
        {"fake": "sleep", "seconds": 0.4},
        {"fake": "result"},
    ]
    runner, _ = runner_for(tmp_path, lines)
    with serving(office, tmp_path, runs=RunManager(runner, grace=0.5)) as (app, client):
        status, record = client.post("/api/runs", {"skill": "cio", "message": QUESTION})
        assert status == 200 and record["mode"] == "chat" and record["web"] is True
        status, data = client.request("DELETE", f"/api/runs/{record['id']}")[::2]
        assert status == 409 and json.loads(data)["reason"] == "run_active"
        settle(app.runs, office, record["id"])
        status, second = client.post(
            "/api/runs", {"skill": "onboard", "message": "Let's begin.", "web": False}
        )
        assert status == 200 and second["web"] is False
        settle(app.runs, office, second["id"])
        listed = client.get("/api/runs")[1]
        assert [(r["skill"], r["title"]) for r in listed] == [
            ("onboard", "Let's begin."),
            ("cio", QUESTION),
        ]
        status, data = client.post(
            f"/api/runs/{record['id']}/message", {"text": "Go on.", "web": 1}
        )
        assert status == 400 and data["reason"] == "invalid_request"
        status, _, data = client.request("DELETE", f"/api/runs/{record['id']}")
        assert status == 200 and json.loads(data) == {"deleted": record["id"]}
        assert [r["id"] for r in client.get("/api/runs")[1]] == [second["id"]]
        assert client.get(f"/api/runs/{record['id']}")[0] == 404
        folder = office / "cache/serve/runs"
        assert not list(folder.glob(f"{record['id']}*"))
        status, _, data = client.request(
            "DELETE", f"/api/runs/{second['id']}", headers={"Origin": "http://evil.example"}
        )
        assert status == 403
        assert client.get("/api/runner")[1]["web"] == "on"


def test_titles_are_one_short_line():
    assert title("  \n First line \nsecond") == "First line"
    assert title("x" * 200) == "x" * 79 + "…"


def test_serve_renders_stale_skills_itself(office):
    assert refresh_skills(office) is False
    (office / ".agents/skills/.fo-stamp.json").unlink()
    assert any(check["status"] != "pass" for check in freshness(office))
    assert refresh_skills(office) is True
    assert all(check["status"] == "pass" for check in freshness(office))


def test_onboarding_steps_name_what_the_app_can_do(tmp_path):
    from fo.init import initialize

    root = tmp_path / "office"
    initialize(root)
    data = derive(Locator(root))
    assert data["state"] == "unconnected"
    assert [step["action"] for step in data["steps"]] == ["connect:schwab", "connect:simplefin"]
    assert "Onboard advisor" in data["note"]
    data = derive(Locator(tmp_path / "empty"))
    assert data["state"] == "uninitialized_path" and data["steps"][0]["action"] == "setup"


def test_sync_runs_from_the_app_and_reports_each_provider(office, tmp_path):
    lines = [{"fake": "init"}, {"fake": "sleep", "seconds": 1}, {"fake": "result"}]
    runner, _ = runner_for(tmp_path, lines)
    with serving(office, tmp_path, runs=RunManager(runner, grace=0.5)) as (app, client):
        # The synthetic accounts belong to no live provider.
        status, data = client.post("/api/sync")
        assert (status, data["reason"]) == (400, "no_accounts")
        accounts = json.loads((office / "profile/accounts.json").read_text())
        accounts["accounts"][0]["provider"] = "csv"
        (office / "profile/accounts.json").write_text(json.dumps(accounts))
        status, data = client.post("/api/sync")
        assert status == 200 and data["complete"] is True
        assert [(row["provider"], row["status"]) for row in data["providers"]] == [
            ("csv", "complete")
        ]
        assert set(data["providers"][0]) == {"provider", "status", "reason", "message", "as_of"}
        record = client.post("/api/runs", {"skill": "cio", "message": QUESTION})[1]
        status, data = client.post("/api/sync")
        assert (status, data["reason"]) == (409, "run_active")
        client.post(f"/api/runs/{record['id']}/cancel")
        settle(app.runs, office, record["id"])
        status, data = client.post("/api/sync", headers={"Origin": "http://evil.example"})
        assert status == 403
    with serving(office, tmp_path, read_only=True) as (_, client):
        assert client.post("/api/sync")[0] == 404
