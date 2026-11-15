"""Several advisors answering at once, and account sync from the server."""

import json
import platform
import threading
import time

import pytest

from fo.config import set_config
from fo.errors import OfficeError
from fo.lock import office_lock
from fo.office import git
from fo.serve.runner_codex import CodexRunner
from fo.serve.runs import ACTIVE, RunManager, run_settings
from fo.serve.server import Locator
from fo.serve.syncer import Syncer, settings, stamp
from fo.store.jsonl import read_rows
from tests.offices import synthetic
from tests.serving import serving
from tests.test_serve_runs import COMPLETE, runner_for, settle

SLOW = [
    {"fake": "init"},
    {"fake": "sleep", "seconds": 1.2},
    {"fake": "text", "text": "Here is the answer."},
    {"fake": "result"},
]
QUESTION = "Where should new cash go?"


@pytest.fixture
def office(tmp_path):
    return synthetic(tmp_path / "office")


def connect(office, provider="csv"):
    """Give the synthetic office one account a sync can pull, on this writer host."""
    accounts = json.loads((office / "profile/accounts.json").read_text())
    accounts["accounts"][0]["provider"] = provider
    (office / "profile/accounts.json").write_text(json.dumps(accounts))
    git(office, "add", "-A")
    git(office, "-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-qm", "csv")


def wait_for(check, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if check():
            return
        time.sleep(0.02)
    raise AssertionError("the condition never held")


# Several advisors ------------------------------------------------------------------


def test_two_advisors_answer_at_once_and_each_stops_on_its_own(office, tmp_path):
    manager = RunManager(runner_for(tmp_path, SLOW)[0], grace=0.5)
    tax = manager.launch(office, "cio", message=QUESTION)
    research = manager.launch(office, "research", message="What does BETA sell?")
    assert set(manager.active) == {tax["id"], research["id"]}
    wait_for(lambda: all(slot.process is not None for slot in manager.active.values()))
    pids = {slot.process.pid for slot in manager.active.values()}
    assert len(pids) == 2
    manager.cancel(office, tax["id"])
    assert settle(manager, office, tax["id"])["status"] == "cancelled"
    done = settle(manager, office, research["id"])
    assert done["status"] == "awaiting_input" and done["error"] is None
    assert not manager.active
    texts = [e["text"] for e in manager.events(office, research["id"]) if e["kind"] == "text"]
    assert texts == ["Here is the answer."]


def test_the_office_limit_refuses_one_more_advisor(office, tmp_path):
    assert run_settings(office)["parallel_runs"] == 3
    set_config(office, "serve.parallel_runs", "2")
    with serving(office, tmp_path, runs=RunManager(runner_for(tmp_path, SLOW)[0])) as (app, client):
        first = client.post("/api/runs", {"skill": "cio", "message": QUESTION})[1]
        second = client.post("/api/runs", {"skill": "research", "message": QUESTION})[1]
        status, data = client.post("/api/runs", {"skill": "lynch", "message": QUESTION})
        assert (status, data["reason"]) == (409, "run_limit")
        assert "2 advisors" in data["message"]
        assert client.get("/api/runner")[1]["parallel_runs"] == 2
        for record in (first, second):
            settle(app.runs, office, record["id"])
        status, third = client.post("/api/runs", {"skill": "lynch", "message": QUESTION})
        assert status == 200
        # A follow-up counts against the limit like a launch does.
        fourth = client.post("/api/runs", {"skill": "cio", "message": QUESTION})[1]
        status, data = client.post(f"/api/runs/{first['id']}/message", {"text": "And bonds?"})
        assert (status, data["reason"]) == (409, "run_limit")
        for record in (third, fourth):
            settle(app.runs, office, record["id"])


def test_one_conversation_takes_one_turn_at_a_time(office, tmp_path):
    manager = RunManager(runner_for(tmp_path, SLOW)[0])
    record = manager.launch(office, "research", "BETA")
    with pytest.raises(OfficeError) as raised:
        manager.message(office, record["id"], "And the margins?")
    assert raised.value.reason == "run_active"
    # The same report cannot be written by two runs at once.
    with pytest.raises(OfficeError) as raised:
        manager.launch(office, "research", "BETA")
    assert raised.value.reason == "run_active" and set(manager.active) == {record["id"]}
    settle(manager, office, record["id"])


def test_concurrent_runs_each_finish_their_own_report(office, tmp_path):
    manager = RunManager(runner_for(tmp_path, COMPLETE)[0])
    first = manager.launch(office, "research", "BETA")
    second = manager.launch(office, "lynch", "ACME")
    one, two = (settle(manager, office, r["id"]) for r in (first, second))
    assert (one["status"], two["status"]) == ("completed", "completed")
    assert one["report"] != two["report"] and len(one["decisions"]) == len(two["decisions"]) == 1
    assert one["decisions"] != two["decisions"]


def test_a_run_waits_for_the_office_lock_instead_of_failing(office, tmp_path, monkeypatch):
    lines = [{"fake": "init"}, {"fake": "sleep", "seconds": 0.4}, *COMPLETE[1:]]
    manager = RunManager(runner_for(tmp_path, lines)[0])
    record = manager.launch(office, "research", "BETA")
    # Held while the run reaches its fo commands, as another conversation's command would.
    with office_lock(office):
        time.sleep(1.2)
    assert settle(manager, office, record["id"])["status"] == "completed"
    # Outside a run nothing waits unless the environment asks for it.
    held = threading.Event()

    def hold():
        with office_lock(office):
            held.set()
            time.sleep(0.5)

    threading.Thread(target=hold, daemon=True).start()
    held.wait(5)
    with pytest.raises(OfficeError) as raised:
        with office_lock(office):
            pass
    assert raised.value.reason == "office_locked"
    monkeypatch.setenv("FO_LOCK_WAIT", "5")
    with office_lock(office):
        pass
    monkeypatch.setenv("FO_LOCK_WAIT", "soon")
    threading.Thread(target=hold, daemon=True).start()
    time.sleep(0.1)
    with pytest.raises(OfficeError):
        with office_lock(office):
            pass


def test_a_codex_run_parses_with_its_own_state():
    runner = CodexRunner(executable=["codex"])
    one, two = runner.parser(), runner.parser()
    one.parse(json.dumps({"type": "thread.started", "thread_id": "thread-one"}), None)
    assert (one.thread, two.thread, runner.thread) == ("thread-one", None, None)


# Sync ------------------------------------------------------------------------------


def test_sync_settings_default_to_automatic_every_six_hours(office):
    assert settings(office) == {"auto": True, "hours": 6.0}
    set_config(office, "serve.auto_sync", "false")
    set_config(office, "serve.auto_sync_hours", "12")
    assert settings(office) == {"auto": False, "hours": 12.0}
    for key, value in (("serve.parallel_runs", "9"), ("serve.auto_sync_hours", "0")):
        with pytest.raises(OfficeError) as raised:
            set_config(office, key, value)
        assert raised.value.reason == "invalid_value"


def test_automatic_sync_runs_when_the_data_is_stale(office, tmp_path):
    clock = [time.time()]
    syncer = Syncer(Locator(office), clock=lambda: clock[0])
    # The synthetic accounts belong to no provider a sync pulls.
    assert syncer.next_at(office) == (None, "no_accounts")
    assert syncer.tick() is False
    connect(office)
    assert syncer.next_at(office) == (0.0, None)
    before = len(read_rows(office, "data/sync_log.jsonl"))
    assert syncer.tick() is True
    rows = read_rows(office, "data/sync_log.jsonl")
    assert len(rows) == before + 1
    assert (rows[-1]["provider"], rows[-1]["status"]) == ("csv", "complete")
    # What the sync wrote is recorded in the office's history.
    assert git(office, "status", "--porcelain", "--", "data").stdout == ""
    due, reason = syncer.next_at(office)
    assert reason is None and due == pytest.approx(stamp(rows[-1]["as_of"]) + 6 * 3600)
    assert syncer.tick() is False and len(read_rows(office, "data/sync_log.jsonl")) == before + 1
    clock[0] += 6 * 3600 + 60
    assert syncer.tick() is True and len(read_rows(office, "data/sync_log.jsonl")) == before + 2
    set_config(office, "serve.auto_sync", "false")
    clock[0] += 24 * 3600
    assert syncer.next_at(office) == (None, "off") and syncer.tick() is False


def test_automatic_sync_stays_off_another_computers_office(office, monkeypatch):
    connect(office)
    monkeypatch.setattr(platform, "node", lambda: "another-mac")
    syncer = Syncer(Locator(office))
    assert syncer.next_at(office) == (None, "not_writer") and syncer.tick() is False
    assert syncer.state(office)["reason"] == "not_writer"


def test_a_failing_sync_is_retried_with_a_growing_wait(office):
    connect(office)
    clock, calls = [1_000_000.0], []

    def failing(root, *args, timeout=60):
        calls.append(args)
        return 1, {"reason": "missing_credentials", "message": "Run fo auth simplefin locally."}

    syncer = Syncer(Locator(office), clock=lambda: clock[0], run=failing)
    assert syncer.tick() is True and calls == [("sync", "--if-writer")]
    assert syncer.next_at(office)[0] == clock[0] + 1800
    clock[0] += 1700
    assert syncer.tick() is False and len(calls) == 1
    clock[0] += 200
    assert syncer.tick() is True and len(calls) == 2
    assert syncer.next_at(office)[0] == clock[0] + 3600
    # The wait never passes the interval itself.
    syncer.failures = 10
    assert syncer.next_at(office)[0] == clock[0] + 6 * 3600


def test_a_message_sent_during_a_sync_is_queued_until_it_ends(office, tmp_path):
    connect(office)
    started, release = threading.Event(), threading.Event()

    def slow(root, *args, timeout=60):
        started.set()
        release.wait(10)
        return 0, [{"provider": "csv", "status": "complete", "as_of": "2026-01-01T00:00:00Z"}]

    manager = RunManager(runner_for(tmp_path, SLOW[:1] + SLOW[2:])[0])
    syncer = Syncer(Locator(office), manager, run=slow)
    outcome = []
    thread = threading.Thread(target=lambda: outcome.append(syncer.sync(office)))
    thread.start()
    started.wait(5)
    assert syncer.state(office)["running"] == "manual"
    with pytest.raises(OfficeError) as raised:
        syncer.sync(office)
    assert raised.value.reason == "sync_active"
    record = manager.launch(office, "cio", message=QUESTION)
    time.sleep(0.5)
    waiting = manager.get(office, record["id"])
    assert waiting["status"] == "queued" and manager.active[record["id"]].process is None
    release.set()
    thread.join(10)
    assert outcome[0]["complete"] is True and syncer.state(office)["running"] is None
    assert settle(manager, office, record["id"])["status"] == "awaiting_input"


def test_a_queued_message_can_be_stopped_before_it_starts(office, tmp_path):
    manager = RunManager(runner_for(tmp_path, SLOW)[0])
    manager.pause()
    record = manager.launch(office, "cio", message=QUESTION)
    manager.cancel(office, record["id"])
    done = settle(manager, office, record["id"])
    assert done["status"] == "cancelled" and done["pid"] is None
    manager.resume()


def test_sync_waits_for_advisors_and_the_status_reports_it(office, tmp_path):
    connect(office)
    with serving(office, tmp_path, runs=RunManager(runner_for(tmp_path, SLOW)[0])) as (app, client):
        state = client.get("/api/status")[1]["sync"]
        assert state["running"] is None and state["auto"] is True and state["hours"] == 6.0
        assert state["reason"] is None and stamp(state["next"]) is not None
        record = client.post("/api/runs", {"skill": "cio", "message": QUESTION})[1]
        status, data = client.post("/api/sync")
        assert (status, data["reason"]) == (409, "run_active")
        assert app.syncer.tick() is False
        settle(app.runs, office, record["id"])
        assert all(row["status"] not in ACTIVE for row in app.runs.list(office))
        status, data = client.post("/api/sync")
        assert status == 200 and data["complete"] is True
    with serving(office, tmp_path, read_only=True) as (app, client):
        assert app.syncer is None and client.get("/api/status")[1]["sync"] is None
