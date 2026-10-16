import json
import subprocess
import sys

import pytest

from fo import notebook
from fo.lock import office_lock
from fo.serve.runs import RunManager
from tests.offices import synthetic
from tests.serving import serving, tree
from tests.test_serve_runs import COMPLETE, runner_for, settle


@pytest.fixture
def office(tmp_path):
    return synthetic(tmp_path / "office")


def chat(office, tmp_path, lines=COMPLETE, **options):
    runner, _ = runner_for(tmp_path, lines, "script-" + str(len(list(tmp_path.iterdir()))))
    return serving(office, tmp_path, runs=RunManager(runner, **options))


def sse(client, path, headers=None):
    status, response_headers, data = client.request("GET", path, headers=headers)
    assert status == 200 and response_headers["content-type"].startswith("text/event-stream")
    events, ended = [], False
    for block in data.decode().split("\n\n"):
        lines = dict(
            line.split(": ", 1)
            for line in block.splitlines()
            if ": " in line and not line.startswith(":")
        )
        if lines.get("event") == "end":
            ended = True
        elif "data" in lines:
            event = json.loads(lines["data"])
            assert lines["id"] == str(event["seq"])
            events.append(event)
    return events, ended


def cli(office, *args):
    result = subprocess.run(
        [sys.executable, "-m", "fo.cli", "--json", "--office", str(office), *args],
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def test_preview_shows_what_the_run_reads_without_side_effects(office, tmp_path):
    before = tree(office)
    with chat(office, tmp_path) as (_, client):
        status, data = client.get("/api/advisors/research/preview?subject=ACME&level=household")
        assert status == 200
        assert data["level"] == "household" and data["subject"] == "ACME"
        assert data["brief"]["status"] == "ok" and "estimated_tokens" in data["brief"]["data"]
        assert data["report"]["data"]["path"].startswith("reports/research/ACME/")
        assert data["prior"]["data"]["path"].startswith("reports/research/ACME/")
        assert data["chat"] is True
        status, data = client.get("/api/advisors/cio/preview")
        assert status == 200 and data["level"] == "full" and data["subject"] == "household"
        assert client.get("/api/advisors/journal/preview")[1]["chat"] is False
        status, data = client.get("/api/advisors/research/preview?level=everything")
        assert (status, data["reason"]) == (400, "invalid_context")
        assert client.get("/api/advisors/nobody/preview")[0] == 404
        assert (
            client.get("/api/advisors/research/preview?subject=../x")[1]["reason"] == "invalid_path"
        )
    assert tree(office) == before


def test_runner_status_is_reported_and_cached(office, tmp_path):
    with chat(office, tmp_path, deep=True) as (app, client):
        status, data = client.get("/api/runner")
        assert status == 200 and data == {
            "ready": True,
            "runner": "claude",
            "version": "2.1.283",
            "deep": True,
        }
        app.runs.runner.executable = []
        assert client.get("/api/runner")[1]["ready"] is True
        app.runner_status = None
        data = client.get("/api/runner")[1]
        assert data["ready"] is False and data["reason"] == "runner_missing"


def test_a_run_launches_streams_and_replays(office, tmp_path):
    with chat(office, tmp_path) as (app, client):
        status, record = client.post(
            "/api/runs", {"skill": "research", "subject": "BETA", "level": "household"}
        )
        assert status == 200 and record["status"] == "queued"
        events, ended = sse(client, f"/api/runs/{record['id']}/events")
        assert ended
        kinds = [e["kind"] for e in events]
        assert kinds[0] == "user" and "decision" in kinds
        assert events[-1] == {**events[-1], "kind": "status", "status": "completed"}
        replay, ended = sse(client, f"/api/runs/{record['id']}/events")
        assert ended and [e["seq"] for e in replay] == [
            e["seq"] for e in events if e["kind"] != "delta"
        ]
        tail, _ = sse(
            client, f"/api/runs/{record['id']}/events", {"Last-Event-ID": str(replay[-2]["seq"])}
        )
        assert [e["seq"] for e in tail] == [replay[-1]["seq"]]
        assert client.get(f"/api/runs/{record['id']}")[1]["status"] == "completed"
        assert [r["id"] for r in client.get("/api/runs")[1]] == [record["id"]]
        assert client.get("/api/runs/01M00000000000000000000000")[0] == 404
        assert client.get(f"/api/runs/{record['id']}/events?after=x")[0] == 400


def test_a_running_run_streams_until_it_finishes(office, tmp_path):
    lines = [
        {"fake": "init"},
        {"fake": "sleep", "seconds": 1},
        {"fake": "text", "text": "Live text."},
        {"fake": "result"},
    ]
    with chat(office, tmp_path, lines) as (_, client):
        record = client.post("/api/runs", {"skill": "research", "subject": "BETA"})[1]
        events, ended = sse(client, f"/api/runs/{record['id']}/events")
        kinds = [e["kind"] for e in events]
        assert ended and "delta" in kinds and kinds[-1] == "status"
        assert events[-1]["status"] == "awaiting_input"


def test_follow_up_and_cancel_through_the_api(office, tmp_path):
    lines = [
        {"fake": "init"},
        {"fake": "text", "text": "Which ticker?"},
        {"fake": "sleep", "seconds": 0.3},
        {"fake": "result"},
    ]
    with chat(office, tmp_path, lines, grace=0.5) as (app, client):
        record = client.post("/api/runs", {"skill": "research", "subject": "BETA"})[1]
        status, data = client.post("/api/runs", {"skill": "lynch", "subject": "ACME"})
        assert (status, data["reason"]) == (409, "run_active")
        settle(app.runs, office, record["id"])
        status, data = client.post(f"/api/runs/{record['id']}/message", {"text": "BETA, please."})
        assert status == 200
        status, data = client.post(f"/api/runs/{record['id']}/cancel")
        assert status == 200
        assert settle(app.runs, office, record["id"])["status"] == "cancelled"
        status, data = client.post(f"/api/runs/{record['id']}/cancel")
        assert (status, data["reason"]) == (409, "not_running")
        assert client.post(f"/api/runs/{record['id']}/message", {"text": 5})[0] == 400


def test_launch_validates_its_body(office, tmp_path):
    with chat(office, tmp_path) as (_, client):
        for body, reason in (
            ({"skill": "research"}, "invalid_request"),
            ({"skill": "research", "subject": "BETA", "deep": "yes"}, "invalid_request"),
            ({"skill": "research", "subject": "BETA", "level": 3}, "invalid_request"),
            ({"skill": "onboard", "subject": "household"}, "not_in_chat"),
        ):
            status, data = client.post("/api/runs", body)
            assert data["reason"] == reason, body
        status, data = client.post(
            "/api/runs",
            {"skill": "research", "subject": "BETA"},
            headers={"Origin": "http://evil.example"},
        )
        assert (status, data["reason"]) == (403, "forbidden_origin")


def test_closing_twice_conflicts(office, tmp_path):
    decision = notebook.decisions(office)[0]["id"]
    with chat(office, tmp_path) as (_, client):
        status, data = client.post(
            f"/api/decisions/{decision}/close", {"outcome": "hit", "note": "Worked."}
        )
        assert status == 200 and data["event"] == "closed" and data["outcome"] == "hit"
        status, data = client.post(f"/api/decisions/{decision}/close", {"outcome": "hit"})
        assert (status, data["reason"]) == (409, "invalid_transition")
        status, data = client.post(f"/api/decisions/{decision}/reopen", {"reason": "New evidence."})
        assert status == 200 and data["event"] == "reopened"
        status, data = client.post(
            f"/api/decisions/{decision}/judge", {"until": "2099-01-01", "note": "Wait."}
        )
        assert status == 200 and data["judged_until"] == "2099-01-01"
        assert (
            client.post(f"/api/decisions/{decision}/close", {"outcome": "great"})[1]["reason"]
            == "invalid_request"
        )
        assert (
            client.post(f"/api/decisions/{decision}/judge", {"until": "soon"})[1]["reason"]
            == "invalid_request"
        )
        status, data = client.post(
            "/api/decisions/01M00000000000000000000000/close", {"outcome": "hit"}
        )
        assert (status, data["reason"]) == (404, "unknown_decision")
    assert notebook.decisions(office)[0]["status"] == "open"


def test_ui_corrections_match_terminal_ones(office, tmp_path):
    terminal = cli(office, "corrections", "add", "--scope=subject:ACME", "--", "Terminal note.")
    with chat(office, tmp_path) as (_, client):
        status, web = client.post(
            "/api/corrections", {"text": "-5% is a floor.", "scope": "subject:ACME"}
        )
        assert status == 200
        assert (
            client.post("/api/corrections", {"text": "x", "scope": "bad scope"})[1]["reason"]
            == "invalid_scope"
        )
        listed = {r["id"]: r for r in cli(office, "corrections", "list", "--for", "ACME")}
        assert listed[web["id"]].keys() == listed[terminal["id"]].keys()
        assert listed[web["id"]]["text"] == "-5% is a floor."
        status, data = client.post(f"/api/corrections/{web['id']}/retire")
        assert status == 200 and data["event"] == "retired"
        assert web["id"] not in {
            r["id"] for r in cli(office, "corrections", "list", "--for", "ACME")
        }
        assert client.post("/api/corrections/99/retire")[1]["reason"] == "unknown_correction"


def test_ui_decisions_match_terminal_ones(office, tmp_path):
    form = {
        "subject": "BETA",
        "action": "TRIM",
        "thesis": "--office /tmp is just text here.",
        "invalidate": "Margins recover.",
        "conviction": "LOW",
        "context_level": "household",
        "when": ["price > 300"],
        "report": "reports/research/ACME/2026-10-15-report.md",
    }
    terminal = cli(
        office,
        "journal",
        "add",
        "--action=TRIM",
        f"--thesis={form['thesis']}",
        "--invalidate=Margins recover.",
        "--conviction=LOW",
        "--context-level=household",
        "--when=price > 300",
        f"--report={form['report']}",
        "--",
        "BETA",
    )
    with chat(office, tmp_path) as (_, client):
        status, web = client.post("/api/decisions", form)
        assert status == 200
        assert (
            client.post("/api/decisions", {**form, "conviction": "MAYBE"})[1]["reason"]
            == "invalid_request"
        )
        assert (
            client.post("/api/decisions", {**form, "subject": "a/b"})[1]["reason"] == "invalid_path"
        )
        assert (
            client.post("/api/decisions", {**form, "when": "price > 1"})[1]["reason"]
            == "invalid_request"
        )
    listed = {d["id"]: d for d in cli(office, "journal", "list", "--subject", "BETA")}
    differ = {k for k in listed[web["id"]] if listed[web["id"]][k] != listed[terminal["id"]][k]}
    assert listed[web["id"]].keys() == listed[terminal["id"]].keys()
    assert differ <= {"id", "as_of", "source"}
    assert (listed[web["id"]]["source"], listed[terminal["id"]]["source"]) == ("web", "journal")
    briefed = cli(office, "brief", "--level", "none", "--for", "BETA")["decisions"]
    assert {d["id"] for d in briefed} == {web["id"], terminal["id"]}
    assert len({tuple(d) for d in briefed}) == 1


def test_a_held_lock_gives_a_retry_hint(office, tmp_path):
    decision = notebook.decisions(office)[0]["id"]
    with chat(office, tmp_path) as (_, client):
        with office_lock(office):
            status, data = client.post(f"/api/decisions/{decision}/close", {"outcome": "hit"})
            assert (status, data["reason"]) == (409, "office_locked")
            assert "try again" in data["message"]
            status, data = client.post("/api/runs", {"skill": "research", "subject": "BETA"})
            assert (status, data["reason"]) == (409, "office_locked")


def test_read_only_has_no_chat_or_write_routes(office, tmp_path):
    with serving(office, tmp_path, read_only=True) as (_, client):
        assert client.get("/api/status")[1]["chat"] is False
        assert client.get("/api/runs")[0] == 404
        assert client.get("/api/advisors/research/preview")[0] == 404
        assert client.post("/api/runs", {"skill": "research", "subject": "BETA"})[0] == 404
        assert client.post("/api/corrections", {"text": "x"})[0] == 404
