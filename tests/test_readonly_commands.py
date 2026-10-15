import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from fo import notebook
from fo.cli import app
from fo.lock import office_lock
from fo.office import git
from fo.providers.cache import Cache
from tests.offices import synthetic


def invoke(*args):
    response = CliRunner().invoke(app, list(args))
    return response.exit_code, json.loads(response.output)


@pytest.fixture
def office(tmp_path):
    return synthetic(tmp_path / "office")


def test_status_reports_sync_and_probes_the_lock_only_when_asked(office, monkeypatch):
    lock = office / ".fo.lock"
    lock.unlink(missing_ok=True)
    code, data = invoke("status", "--json", "--read-only", "--office", str(office))
    assert code == 0
    assert data["office"] == str(office)
    assert data["read_only"] is True
    assert data["writer_host"] is True
    assert data["last_sync"]["status"] == "complete"
    assert data["lock"] is None
    assert not lock.exists()
    assert invoke("status", "--lock", "--json", "--office", str(office))[1]["lock"] == {
        "held": False
    }
    with office_lock(office):
        held = invoke("status", "--lock", "--json", "--office", str(office))[1]
        assert held["lock"] == {"held": True}
    assert invoke("status", "--lock", "--json", "--office", str(office))[1]["lock"] == {
        "held": False
    }
    monkeypatch.setattr("platform.node", lambda: "another-host")
    assert invoke("status", "--json", "--office", str(office))[1]["writer_host"] is False


def notebook_state(root):
    return {
        str(p.relative_to(root)): p.read_bytes()
        for p in sorted((root / "notebook").rglob("*"))
        if p.is_file()
    }


def test_review_dry_run_evaluates_without_writing(office):
    Cache(office).get("alpha:GLOBAL_QUOTE:ACME", 900, lambda: {"Global Quote": {"05. price": "95"}})
    decision = notebook.add(office, "ACME", "TRIM", "Overvalued", "Price breaks", ["price < 100"])
    before = notebook_state(office)
    code, data = invoke("review", "--dry-run", "--json", "--read-only", "--office", str(office))
    assert code == 1
    assert data["dry_run"] is True and data["breaches"] == 1
    states = {row["id"]: row for row in data["decisions"]}
    assert states[decision["id"]]["breached"] is True
    assert states[decision["id"]]["due_for_verdict"] is True
    assert any(row["needs_judgment"] for row in data["decisions"])
    assert notebook_state(office) == before
    code, data = invoke("review", "--json", "--office", str(office))
    assert code == 1 and "dry_run" not in data
    after = notebook_state(office)
    assert after["notebook/reviews.jsonl"] != before["notebook/reviews.jsonl"]
    assert f"notebook/reviews/{data['date']}.md" in after


def test_positions_filters_through_compute(office):
    code, data = invoke(
        "positions", "--symbol", "BOND", "--json", "--read-only", "--office", str(office)
    )
    assert code == 0
    assert [p["symbol"] for p in data["positions"]] == ["BOND"]
    assert list(data) == ["positions", "as_of", "stale_accounts", "stale_providers"]
    code, data = invoke(
        "positions", "--account", "checking", "--json", "--read-only", "--office", str(office)
    )
    assert data["positions"] == [] and data["as_of"] is None


RESTRICTED = [
    ["--json", "sync"],
    ["sync", "--provider", "csv", "--json"],
    ["sync", "--dry-run", "status", "--json"],
    ["--read-only", "commit", "--json"],
    ["reindex", "--json"],
    ["skills", "sync", "--json"],
    ["setup", "elsewhere", "--json"],
    ["auth", "schwab", "--json"],
    ["init", "elsewhere", "--json"],
    ["schedule", "install", "--json"],
    ["notify", "hello", "--json"],
    ["migrate-v1", "elsewhere", "--dry-run", "--json"],
]


def test_serve_run_marker_pins_the_office(office, tmp_path, monkeypatch):
    other = synthetic(tmp_path / "other")
    monkeypatch.setenv("FO_SERVE_RUN", str(office))
    monkeypatch.delenv("FO_OFFICE", raising=False)
    code, data = invoke("--office", str(other), "status", "--json")
    assert (code, data["reason"]) == (1, "serve_run_restricted")
    code, data = invoke("status", "--json", f"--office={other}")
    assert (code, data["reason"]) == (1, "serve_run_restricted")
    monkeypatch.setenv("FO_OFFICE", str(other))
    code, data = invoke("status", "--json")
    assert (code, data["reason"]) == (1, "serve_run_restricted")
    monkeypatch.setenv("FO_OFFICE", str(office) + "/")
    assert invoke("status", "--json")[1]["office"] == str(office)
    monkeypatch.delenv("FO_OFFICE")
    monkeypatch.chdir(tmp_path)
    assert invoke("status", "--json")[1]["office"] == str(office)


@pytest.mark.parametrize("args", RESTRICTED)
def test_serve_run_marker_refuses_restricted_commands(office, monkeypatch, args):
    monkeypatch.setenv("FO_SERVE_RUN", str(office))
    monkeypatch.setenv("FO_OFFICE", str(office))
    store = office / "store.sqlite"
    store.unlink(missing_ok=True)
    head = git(office, "rev-parse", "HEAD").stdout
    code, data = invoke(*args)
    assert (code, data["reason"]) == (1, "serve_run_restricted")
    assert not store.exists()
    assert git(office, "rev-parse", "HEAD").stdout == head
    assert not Path("elsewhere").exists()


@pytest.mark.parametrize(
    "args",
    [["status"], ["sync", "status"], ["journal", "list"], ["skills", "list"], ["reports", "list"]],
)
def test_serve_run_marker_allows_read_commands(office, monkeypatch, args):
    monkeypatch.setenv("FO_SERVE_RUN", str(office))
    monkeypatch.setenv("FO_OFFICE", str(office))
    code, _ = invoke(*args, "--json")
    assert code == 0
