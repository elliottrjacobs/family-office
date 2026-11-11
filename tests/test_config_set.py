import json
import threading
import time
import tomllib
from zoneinfo import available_timezones

import pytest
from typer.testing import CliRunner

from fo.cli import app
from fo.config import config_value, get_config, read_config, set_config
from fo.errors import OfficeError
from fo.init import initialize
from fo.lock import office_lock
from fo.office import git


def cli(root, *args):
    response = CliRunner().invoke(app, [*args, "--json", "--office", str(root)])
    return response.exit_code, json.loads(response.output)


@pytest.fixture
def office(tmp_path, monkeypatch):
    monkeypatch.setattr("platform.node", lambda: "example-host")
    root = tmp_path / "office"
    initialize(root)
    return root


def test_port_out_of_range_is_refused(office):
    before = (office / "office.toml").read_bytes()
    for bad in ("99999", "0", "8182", "80.5", "true", "port"):
        code, data = cli(office, "config", "set", "serve.port", bad)
        assert (code, data["reason"]) == (1, "invalid_value"), bad
        assert "integer from 1 to 65535" in data["message"]
    assert (office / "office.toml").read_bytes() == before
    code, data = cli(office, "config", "set", "serve.port", "4800")
    assert (code, data) == (0, {"key": "serve.port", "value": 4800})
    assert read_config(office)["serve"]["port"] == 4800


def test_engine_effort_round_trips_through_the_reader(office):
    code, data = cli(office, "config", "set", "serve.engines.codex.effort", "high")
    assert (code, data["value"]) == (0, "high")
    assert read_config(office)["serve"]["engines"]["codex"]["effort"] == "high"
    code, data = cli(office, "config", "get", "serve.engines.codex.effort")
    assert (code, data) == (0, {"key": "serve.engines.codex.effort", "value": "high", "set": True})
    set_config(office, "serve.engines.codex.effort", "low")
    set_config(office, "serve.engines.codex.model", "fixture-model")
    set_config(office, "serve.engines.codex.max_budget_usd", "1.5")
    set_config(office, "serve.engines.codex.enabled", "false")
    assert read_config(office)["serve"]["engines"]["codex"] == {
        "effort": "low",
        "model": "fixture-model",
        "max_budget_usd": 1.5,
        "enabled": False,
    }
    code, data = cli(office, "config", "set", "serve.engines.codex.effort", "max")
    assert (code, data["reason"]) == (1, "invalid_value")


def test_unknown_keys_are_refused(office):
    for key in ("serve.host", "providers.schwab.daily_limit", "serve", "x"):
        code, data = cli(office, "config", "set", key, "1")
        assert (code, data["reason"]) == (1, "invalid_key"), key
    code, data = cli(office, "config", "get", "secrets.alphavantage")
    assert (code, data["reason"]) == (1, "invalid_key")


def test_values_are_typed_by_the_schema():
    assert config_value("serve.allowed_logins", '["a@example.test", "b@example.test"]') == [
        "a@example.test",
        "b@example.test",
    ]
    assert config_value("serve.allowed_logins", "a@example.test, b@example.test") == [
        "a@example.test",
        "b@example.test",
    ]
    assert config_value("serve.allowed_logins", "[]") == []
    assert config_value("serve.tailnet_name", "machine.your-tailnet.ts.net") == (
        "machine.your-tailnet.ts.net"
    )
    assert config_value("serve.web_fetch_cap", "0") == 0
    assert config_value("providers.gemini.max_tasks_per_day", "3") == 3
    assert config_value("providers.edgar.user_agent", "Fixture Office ops@example.test") == (
        "Fixture Office ops@example.test"
    )
    assert config_value("serve.engines.default", "codex") == "codex"
    for key, bad in (
        ("serve.allowed_logins", '["a b"]'),
        ("serve.allowed_logins", "[1]"),
        ("serve.tailnet_name", "bad name"),
        ("serve.tailnet_name", ""),
        ("serve.tailnet_name", "-lead.example"),
        ("serve.web_fetch_cap", "-1"),
        ("serve.engines.default", "other"),
        ("serve.engines.claude.max_budget_usd", "0"),
        ("serve.engines.claude.max_budget_usd", "nan"),
        ("serve.engines.claude.max_budget_usd", "inf"),
        ("serve.engines.claude.enabled", "yes"),
        ("serve.engines.claude.model", ""),
        ("providers.fred.daily_limit", "ten"),
        ("providers.edgar.user_agent", "line\nbreak"),
    ):
        with pytest.raises(OfficeError) as caught:
            config_value(key, bad)
        assert caught.value.reason == "invalid_value", (key, bad)


def test_the_rest_of_the_file_survives_a_set(office):
    path = office / "office.toml"
    original = (
        path.read_text().replace("[serve]\n", "# The companion app.\n[serve]  # kept\n")
        + "\n[custom]\n# A table fo does not know.\nanswer = 42\n"
    )
    path.write_text(original)
    path.chmod(0o600)
    set_config(office, "serve.port", "4801")
    text = path.read_text()
    assert text == original.replace("port = 4790\n", "port = 4801\n")
    assert path.stat().st_mode & 0o777 == 0o600
    set_config(office, "serve.web_fetch_cap", "5")
    set_config(office, "providers.alphavantage.daily_limit", "30")
    set_config(office, "providers.fred.daily_limit", "100")
    after = tomllib.loads(path.read_text())
    before = tomllib.loads(original)
    assert after["serve"] == {**before["serve"], "port": 4801, "web_fetch_cap": 5}
    assert after["providers"] == {
        "alphavantage": {"daily_limit": 30},
        "fred": {"daily_limit": 100},
    }
    for table in ("office", "hosts", "schedule", "notebook", "models", "custom"):
        assert after[table] == before[table]
    text = path.read_text()
    assert "# The companion app.\n[serve]  # kept\n" in text
    assert "# A table fo does not know.\nanswer = 42\n" in text
    assert text.index("[serve]") < text.index("web_fetch_cap = 5") < text.index("[custom]")


def test_a_multiline_value_is_replaced_whole(office):
    path = office / "office.toml"
    path.write_text(
        path.read_text().replace(
            "[serve]\n", '[serve]\nallowed_logins = [\n  "old@example.test",\n]\n'
        )
    )
    set_config(office, "serve.allowed_logins", "new@example.test")
    assert read_config(office)["serve"]["allowed_logins"] == ["new@example.test"]
    assert "old@example.test" not in path.read_text()


def test_a_layout_it_cannot_edit_safely_is_refused(office):
    path = office / "office.toml"
    path.write_text(path.read_text().replace("[serve]\n", "[serve]\nengines = {codex = {}}\n"))
    before = path.read_bytes()
    with pytest.raises(OfficeError) as caught:
        set_config(office, "serve.engines.codex.effort", "high")
    assert caught.value.reason == "config_layout"
    assert path.read_bytes() == before


def test_concurrent_sets_serialize_on_the_lock(office):
    results = []

    def setter(key, value):
        try:
            results.append(set_config(office, key, value))
        except OfficeError as exc:
            results.append(exc.reason)

    with office_lock(office):
        threads = [
            threading.Thread(target=setter, args=("serve.port", "4802")),
            threading.Thread(target=setter, args=("serve.web_fetch_cap", "7")),
        ]
        for thread in threads:
            thread.start()
        time.sleep(0.3)
        # Both writers wait on the lock, so nothing has changed yet.
        assert results == []
        assert "web_fetch_cap" not in read_config(office)["serve"]
    for thread in threads:
        thread.join(timeout=15)
    assert sorted(r["key"] for r in results) == ["serve.port", "serve.web_fetch_cap"]
    serve = read_config(office)["serve"]
    assert (serve["port"], serve["web_fetch_cap"]) == (4802, 7)


def test_a_held_lock_eventually_refuses(office, monkeypatch):
    monkeypatch.setattr("fo.config.LOCK_WAIT", 0.1)
    with office_lock(office):
        with pytest.raises(OfficeError) as caught:
            set_config(office, "serve.port", "4803")
    assert caught.value.reason == "office_locked"


def test_config_set_is_refused_in_runs_and_read_only(office, monkeypatch):
    code, data = cli(office, "config", "set", "serve.port", "4804", "--read-only")
    assert (code, data["reason"]) == (1, "read_only")
    monkeypatch.setenv("FO_SERVE_RUN", str(office))
    monkeypatch.delenv("FO_OFFICE", raising=False)
    code, data = cli(office, "config", "set", "serve.port", "4804")
    assert (code, data["reason"]) == (1, "serve_run_restricted")
    assert read_config(office)["serve"]["port"] == 4790
    code, data = cli(office, "config", "get", "serve.port")
    assert (code, data["value"]) == (0, 4790)
    code, data = cli(office, "config")
    assert code == 0 and data["settings"]["serve"]["port"] == 4790


def test_get_reports_an_unset_key(office):
    assert get_config(office, "serve.tailnet_name") == {
        "key": "serve.tailnet_name",
        "value": None,
        "set": False,
    }


def test_run_cap_keys_are_settable(office):
    from fo.config import config_value, read_config

    assert config_value("serve.max_budget_usd", "3.5") == 3.5
    assert config_value("serve.run_timeout_minutes", "45") == 45.0
    assert config_value("serve.keep_runs", "10") == 10
    for key, bad in (
        ("serve.max_budget_usd", "0"),
        ("serve.run_timeout_minutes", "-1"),
        ("serve.keep_runs", "-1"),
    ):
        with pytest.raises(OfficeError) as info:
            config_value(key, bad)
        assert info.value.reason == "invalid_value"
    cli(office, "config", "set", "serve.keep_runs", "7")
    assert read_config(office)["serve"]["keep_runs"] == 7


@pytest.mark.parametrize(
    "key,value",
    [
        ("hosts.writer", "example-mac.local"),
        ("office.timezone", "Europe/London"),
        ("office.timezone", "UTC"),
    ],
)
def test_writer_and_timezone_are_settable(office, key, value):
    code, data = cli(office, "config", "set", key, value)
    assert code == 0
    assert data["key"] == key and data["value"] == value
    if key == "hosts.writer":
        assert data["note"] == (
            f"Run `fo schedule install` on {value} if it has not been scheduled there. "
            "The old host's sync job will now skip (with --if-writer)."
        )
        code, data = cli(office, "config", "set", key, value)
    assert (code, data) == (0, {"key": key, "value": value})
    table, name = key.split(".")
    assert read_config(office)[table][name] == value


@pytest.mark.parametrize("staged", [False, True])
def test_config_set_records_only_its_file(office, staged):
    unrelated = office / "profile/household.md"
    before = git(office, "show", "HEAD:profile/household.md").stdout
    unrelated.write_text("Unrelated household edit\n")
    if staged:
        git(office, "add", "--", "profile/household.md")
    code, data = cli(office, "config", "set", "hosts.writer", "x")
    assert code == 0, data
    assert git(office, "show", "--format=", "--name-only", "HEAD").stdout.splitlines() == [
        "office.toml"
    ]
    assert git(office, "show", "HEAD:profile/household.md").stdout == before
    assert git(office, "status", "--porcelain", "--", "office.toml").stdout == ""
    assert git(office, "status", "--porcelain", "--", "profile/household.md").stdout.startswith(
        "M " if staged else " M"
    )
    head = git(office, "rev-parse", "HEAD").stdout
    assert cli(office, "config", "set", "hosts.writer", "x")[0] == 0
    assert git(office, "rev-parse", "HEAD").stdout == head


def test_config_set_retries_recording_after_index_lock(office):
    head = git(office, "rev-parse", "HEAD").stdout
    lock = office / ".git/index.lock"
    lock.touch()
    code, data = cli(office, "config", "set", "hosts.writer", "other-host")
    assert (code, data["reason"]) == (1, "git_failed")
    assert read_config(office)["hosts"]["writer"] == "other-host"
    assert git(office, "rev-parse", "HEAD").stdout == head
    lock.unlink()
    code, data = cli(office, "config", "set", "hosts.writer", "other-host")
    assert code == 0, data
    assert git(office, "status", "--porcelain").stdout == ""
    assert git(office, "rev-parse", "HEAD").stdout != head
    assert cli(office, "commit")[0] == 0


@pytest.mark.parametrize(
    "key,value",
    [
        ("hosts.writer", ""),
        ("hosts.writer", "line\nbreak"),
        ("office.timezone", ""),
        ("office.timezone", "Bad/Zone"),
        ("office.timezone", "/etc/passwd"),
        ("office.timezone", "../UTC"),
    ],
)
def test_invalid_writer_and_timezone_are_refused(office, key, value):
    before = (office / "office.toml").read_bytes()
    code, data = cli(office, "config", "set", key, value)
    assert (code, data["reason"]) == (1, "invalid_value")
    assert (office / "office.toml").read_bytes() == before


@pytest.mark.parametrize(
    "value",
    [
        "localtime",
        "posixrules",
        "posix/UTC",
        "right/UTC",
        "utc",
        "europe/london",
        "America/new_york",
    ],
)
def test_timezone_requires_a_listed_key(office, value):
    if value in available_timezones():
        pytest.skip("This system lists the key as an available timezone.")
    before = (office / "office.toml").read_bytes()
    code, data = cli(office, "config", "set", "office.timezone", value)
    assert (code, data["reason"]) == (1, "invalid_value")
    assert (office / "office.toml").read_bytes() == before
