import json
import os
import subprocess
import sys
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
    ["config", "set", "serve.port", "4800", "--json"],
    ["auth", "schwab", "--json"],
    ["init", "elsewhere", "--json"],
    ["schedule", "install", "--json"],
    ["notify", "hello", "--json"],
    ["migrate-v1", "elsewhere", "--dry-run", "--json"],
    ["serve", "--port", "0", "--json"],
    ["doctor", "--fix", "--json"],
    ["--json", "--", "doctor", "--fix"],
    ["doctor", "--json", "--fix", "--read-only"],
    # Click drops a "--" separator, so the check must see the command after it.
    ["--json", "--", "sync"],
    ["--json", "--", "reindex"],
    ["--json", "--", "commit"],
    ["--json", "--", "notify", "-e", "hello"],
    ["--json", "--", "init", "elsewhere"],
    ["--json", "--", "setup", "elsewhere"],
    ["--json", "--", "auth", "schwab"],
    ["--json", "--", "schedule", "install"],
    ["--json", "--", "serve", "--port", "0"],
    ["--json", "--", "migrate-v1", "elsewhere", "--dry-run"],
    ["--json", "--", "skills", "sync"],
    ["--json", "skills", "--", "sync"],
    ["--json", "--", "sync", "status", "--dry-run"],
    ["--json", "sync", "--"],
    ["--json", "reindex", "--"],
    # Retiring corrections and settling decisions stay with the owner.
    ["corrections", "retire", "1", "--json"],
    ["--json", "corrections", "--", "retire", "1"],
    ["--json", "--", "corrections", "retire", "--", "1"],
    ["journal", "close", "01ARZ3NDEKTSV4RRFFQ69G5FAV", "--outcome", "hit", "--json"],
    ["journal", "reopen", "01ARZ3NDEKTSV4RRFFQ69G5FAV", "--reason", "x", "--json"],
    ["journal", "judge", "01ARZ3NDEKTSV4RRFFQ69G5FAV", "--until", "2026-12-31", "--json"],
    ["--json", "journal", "--", "close", "01ARZ3NDEKTSV4RRFFQ69G5FAV", "--outcome", "hit"],
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
    notes = notebook_state(office)
    code, data = invoke(*args)
    assert (code, data["reason"]) == (1, "serve_run_restricted")
    assert notebook_state(office) == notes
    assert not store.exists()
    assert git(office, "rev-parse", "HEAD").stdout == head
    assert not Path("elsewhere").exists()


def test_serve_run_marker_refuses_through_the_console_script(office):
    script = Path(sys.executable).with_name("fo")
    env = {**os.environ, "FO_SERVE_RUN": str(office), "FO_OFFICE": str(office)}
    for args in (["--json", "--", "reindex"], ["--json", "skills", "--", "sync"]):
        result = subprocess.run(
            [str(script), *args], capture_output=True, text=True, env=env, timeout=60
        )
        assert result.returncode == 1, args
        assert json.loads(result.stdout)["reason"] == "serve_run_restricted", args
    assert not (office / "store.sqlite").exists()


@pytest.mark.parametrize("flag", ["--install-completion", "--show-completion"])
def test_shell_completion_is_not_offered(office, tmp_path, monkeypatch, flag):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("SHELL", "/bin/bash")
    monkeypatch.setenv("FO_SERVE_RUN", str(office))
    response = CliRunner().invoke(app, [flag])
    assert response.exit_code != 0
    assert list(home.iterdir()) == []
    monkeypatch.delenv("FO_SERVE_RUN")
    assert flag not in CliRunner().invoke(app, ["--help"]).output


@pytest.mark.parametrize(
    "args",
    [
        ["status"],
        ["doctor"],
        ["sync", "status"],
        ["journal", "list"],
        ["skills", "list"],
        ["reports", "list"],
    ],
)
def test_serve_run_marker_allows_read_commands(office, monkeypatch, args):
    monkeypatch.setenv("FO_SERVE_RUN", str(office))
    monkeypatch.setenv("FO_OFFICE", str(office))
    code, _ = invoke(*args, "--json")
    assert code == 0


@pytest.mark.parametrize("args", [["--", "status"], ["sync", "--", "status"]])
def test_serve_run_marker_allows_read_commands_after_a_separator(office, monkeypatch, args):
    monkeypatch.setenv("FO_SERVE_RUN", str(office))
    monkeypatch.setenv("FO_OFFICE", str(office))
    code, _ = invoke("--json", *args)
    assert code == 0


def test_serve_run_marker_allows_new_notes_that_mention_restricted_words(office, monkeypatch):
    monkeypatch.setenv("FO_SERVE_RUN", str(office))
    monkeypatch.setenv("FO_OFFICE", str(office))
    code, data = invoke(
        "journal",
        "add",
        "ACME",
        "--action",
        "close",
        "--thesis",
        "judge",
        "--invalidate",
        "reopen",
        "--json",
    )
    assert code == 0 and data["action"] == "close"
    code, data = invoke("--json", "corrections", "add", "--", "retire")
    assert code == 0 and data["text"] == "retire"


@pytest.mark.parametrize("web", [None, "0"])
@pytest.mark.parametrize("action", ["search", "fetch", "deep"])
@pytest.mark.parametrize("separator", [[], ["--"]])
def test_serve_run_refuses_research_outside_web_runs(office, monkeypatch, web, action, separator):
    monkeypatch.setenv("FO_SERVE_RUN", str(office))
    if web is None:
        monkeypatch.delenv("FO_SERVE_WEB", raising=False)
    else:
        monkeypatch.setenv("FO_SERVE_WEB", web)
    code, data = invoke("--json", *separator, "research", action, "ACME")
    assert (code, data["reason"]) == (1, "serve_run_restricted")
    assert data["message"].endswith("(web_off)")


@pytest.mark.parametrize(
    "args",
    [
        ["export"],
        ["positions"],
        ["networth"],
        ["lots", "ACME"],
        ["--", "export"],
        ["journal", "list"],
        ["brief", "--level", "full"],
        ["start", "research", "ACME"],
        ["start", "research", "ACME", "--level", "household"],
        ["brief", "--for", "--level=none"],
        ["--", "brief", "--level", "none"],
    ],
)
def test_serve_web_run_refuses_household_commands(office, monkeypatch, args):
    monkeypatch.setenv("FO_SERVE_RUN", str(office))
    monkeypatch.setenv("FO_SERVE_WEB", "1")
    code, data = invoke("--json", *args, "--office", str(office))
    assert (code, data["reason"]) == (1, "serve_run_restricted")
    assert data["message"].endswith("(web_household_command)")
