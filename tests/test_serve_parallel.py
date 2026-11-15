"""Several advisors answering at once."""

import json
import threading
import time

import pytest

from fo.config import set_config
from fo.errors import OfficeError
from fo.lock import office_lock
from fo.serve.runner_codex import CodexRunner
from fo.serve.runs import RunManager, run_settings
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


def test_a_queued_message_can_be_stopped_before_it_starts(office, tmp_path):
    manager = RunManager(runner_for(tmp_path, SLOW)[0])
    manager.pause()
    record = manager.launch(office, "cio", message=QUESTION)
    manager.cancel(office, record["id"])
    done = settle(manager, office, record["id"])
    assert done["status"] == "cancelled" and done["pid"] is None
    manager.resume()
