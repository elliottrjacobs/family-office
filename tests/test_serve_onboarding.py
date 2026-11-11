import json
import os
import shlex
from datetime import UTC, datetime, timedelta

import pytest

from fo.config import credentials_dir
from fo.errors import OfficeError
from fo.init import initialize
from fo.serve.onboarding import derive
from fo.serve.runs import RunManager
from fo.serve.server import ONBOARDING_TTL, Locator
from fo.sync import ingest
from tests.offices import synthetic
from tests.serving import serving
from tests.test_serve_devices import OWNER, paired, remote
from tests.test_serve_runs import COMPLETE, runner_for


@pytest.fixture(autouse=True)
def placeholder_hostname(monkeypatch):
    monkeypatch.setattr("platform.node", lambda: "example-host")


def commands(result):
    return [step["command"] for step in result["steps"]]


def secrets(root, text='[simplefin]\naccess_url = "https://example.invalid/fake"\n'):
    credentials_dir(root).chmod(0o700)
    path = credentials_dir(root) / "keys.toml"
    path.write_text(text)
    path.chmod(0o600)


def accounts(root, rows):
    (root / "profile/accounts.json").write_text(json.dumps({"accounts": rows}))


def test_no_office_asks_for_a_folder():
    result = derive(Locator(None))
    assert result["state"] == "no_office"
    assert result["office"] is None and result["steps"] == []


def test_uninitialized_path_shows_setup_then_unconnected(tmp_path):
    folder = tmp_path / "My Office"
    folder.mkdir()
    result = derive(Locator(folder))
    assert result["state"] == "uninitialized_path"
    quoted = shlex.quote(str(folder))
    assert commands(result) == [
        f"fo setup {quoted}",
        f"fo setup {quoted} --offline",
        f"fo setup {quoted} --provider schwab",
        f"fo setup {quoted} --provider simplefin",
    ]
    initialize(folder)
    result = derive(Locator(folder))
    assert result["state"] == "unconnected"
    assert commands(result)[:2] == [
        f"fo auth schwab --office {quoted}",
        f"fo auth simplefin --office {quoted}",
    ]


def test_csv_registry_without_providers_is_offline(tmp_path):
    root = tmp_path / "office"
    initialize(root)
    accounts(root, [{"id": "joint", "provider": "csv", "last4": "", "role": "cash"}])
    result = derive(Locator(root))
    assert result["state"] == "offline"
    assert any("imports/" in step["purpose"] for step in result["steps"])
    assert commands(result)[0] == f"fo sync --provider csv --office {shlex.quote(str(root))}"


def test_connected_without_a_sync_is_never_synced(tmp_path, monkeypatch):
    root = tmp_path / "office"
    initialize(root)
    secrets(root)
    accounts(root, [{"id": "simplefin-1", "provider": "simplefin", "last4": "", "role": "cash"}])
    result = derive(Locator(root))
    assert result["state"] == "never_synced"
    assert commands(result) == [f"fo sync --office {shlex.quote(str(root))}"]
    assert result["note"] is None
    assert result["providers"] == [
        {"provider": "simplefin", "connected": True, "accounts": 1},
    ]
    monkeypatch.setattr("platform.node", lambda: "another-host")
    note = derive(Locator(root))["note"]
    assert "writer host" in note and "not this machine" in note


@pytest.mark.parametrize("hostname", ["another-host", "example host's name", ""])
def test_writer_suggestion_quotes_the_command_and_office(tmp_path, monkeypatch, hostname):
    root = tmp_path / "My Office"
    initialize(root)
    secrets(root)
    monkeypatch.setattr("platform.node", lambda: hostname)
    note = derive(Locator(root))["note"]
    assert "Only the writer host (example-host) syncs" in note
    if hostname:
        command = note.split("with:\n", 1)[1]
        assert command == (
            f"fo config set hosts.writer {shlex.quote(hostname)} --office {shlex.quote(str(root))}"
        )
        assert shlex.split(command) == [
            "fo",
            "config",
            "set",
            "hosts.writer",
            hostname,
            "--office",
            str(root),
        ]
    else:
        assert note.endswith("Run fo sync there.")
        assert "fo config set" not in note


@pytest.mark.parametrize("provider", ["simplefin", "schwab"])
def test_unmapped_accounts_suggest_auth_to_register_them(tmp_path, provider):
    root = tmp_path / "My Office"
    initialize(root)
    secrets(root)
    accounts(root, [{"id": "a", "provider": provider, "last4": "1234", "role": "cash"}])
    ingest(
        root, provider, [{"account_id": "a", "balance": {"net_value": "1"}}], unmapped_accounts=2
    )
    result = derive(Locator(root))
    item = next(item for item in result["doctor"] if item["name"] == f"sync.unmapped.{provider}")
    assert item["status"] == "warn"
    assert item["reason"] == (
        f"2 account(s) skipped; run `fo auth {provider}` to register the new accounts."
    )
    assert item["command"] == f"fo auth {provider} --office {shlex.quote(str(root))}"
    assert item["hint"] is None
    assert item["command"] in commands(result)


def test_doctor_warning_after_sync_is_stale_with_its_fix(tmp_path):
    root = synthetic(tmp_path / "office")
    secrets(root)
    expiry = (datetime.now(UTC) + timedelta(hours=10)).isoformat().replace("+00:00", "Z")
    token = credentials_dir(root) / "schwab-token.json"
    token.write_text(json.dumps({"refresh_token_expires_at": expiry}))
    token.chmod(0o600)
    result = derive(Locator(root))
    assert result["state"] == "stale"
    items = {item["name"]: item for item in result["doctor"]}
    assert items["schwab.token"]["status"] == "warn"
    assert items["schwab.token"]["command"] == f"fo auth schwab --office {shlex.quote(str(root))}"
    assert commands(result) == [items["schwab.token"]["command"]]
    assert result["last_sync"]


def test_healthy_synced_office_is_ready(tmp_path):
    root = synthetic(tmp_path / "office")
    secrets(root)
    result = derive(Locator(root))
    assert result["state"] == "ready", result["doctor"]
    assert result["doctor"] == [] and result["steps"] == []
    assert result["last_sync"].endswith("Z")


def test_csv_only_office_ignores_the_offline_provider_warning(tmp_path):
    root = tmp_path / "office"
    initialize(root)
    accounts(root, [{"id": "joint", "provider": "csv", "last4": "", "role": "cash"}])
    ingest(root, "csv", [{"account_id": "joint", "positions": [], "balance": {"net_value": "1"}}])
    assert derive(Locator(root))["state"] == "ready"


def test_doctor_fixes_name_their_commands(tmp_path):
    root = synthetic(tmp_path / "office")
    secrets(root)
    (credentials_dir(root) / "keys.toml").chmod(0o644)
    (root / ".agents/skills/.fo-stamp.json").unlink()
    profile = json.loads((root / "profile/accounts.json").read_text())
    profile["accounts"][0].pop("role")
    profile["accounts"][0]["type"] = "mystery"
    (root / "profile/accounts.json").write_text(json.dumps(profile))
    items = {item["name"]: item for item in derive(Locator(root))["doctor"]}
    quoted = shlex.quote(str(root))
    assert items["skills.fresh"]["command"] == f"fo skills sync --office {quoted}"
    assert "doctor --fix" in items["credentials.perms"]["command"]
    assert items["accounts.roles"]["command"] is None
    assert "onboard" in items["accounts.roles"]["hint"]


def test_onboarding_route_advances_without_a_restart(tmp_path):
    folder = tmp_path / "new-office"
    with serving(None, tmp_path) as (app, client):
        assert client.get("/api/onboarding")[1]["state"] == "no_office"
        status, data = client.post("/api/onboarding/path", {"path": str(folder)})
        assert status == 200 and data["state"] == "uninitialized_path"
        assert not folder.exists()
        initialize(folder)
        assert client.get("/api/onboarding")[1]["state"] == "unconnected"
        assert client.get("/api/status")[1]["mode"] == "office"
        status, data = client.post("/api/onboarding/path", {"path": str(tmp_path / "x")})
        assert (status, data["reason"]) == (409, "office_already_open")


@pytest.mark.parametrize(
    ("path", "reason"),
    [
        ("relative/office", "invalid_path"),
        ("", "invalid_request"),
        ("NESTED", "nested_repository"),
        ("FULL", "target_not_empty"),
        ("LINK", "unsafe_path"),
    ],
)
def test_onboarding_path_uses_the_init_rules(tmp_path, path, reason):
    repository = tmp_path / "repo"
    (repository / ".git").mkdir(parents=True)
    full = tmp_path / "full"
    full.mkdir()
    (full / "notes.txt").write_text("x")
    os.symlink(tmp_path, tmp_path / "link")
    path = {
        "NESTED": str(repository / "office"),
        "FULL": str(full),
        "LINK": str(tmp_path / "link"),
    }.get(path, path)
    with serving(None, tmp_path) as (_, client):
        status, data = client.post("/api/onboarding/path", {"path": path})
        assert (status, data["reason"]) == (400, reason)
        assert client.get("/api/onboarding")[1]["state"] == "no_office"


def test_onboarding_post_validates_the_body(tmp_path):
    with serving(None, tmp_path) as (_, client):
        status, _, data = client.request(
            "POST", "/api/onboarding/path", body=None, headers={"Content-Length": "0"}
        )
        assert status == 400 and json.loads(data)["reason"] == "invalid_request"
        status, _, data = client.request(
            "POST", "/api/onboarding/path", body=["list"], headers={"Content-Type": "text/plain"}
        )
        assert status == 400 and json.loads(data)["reason"] == "invalid_request"
        assert client.post("/api/onboarding/path", ["list"])[1]["reason"] == "invalid_request"
        status, _, data = client.raw_post("/api/onboarding/path", b"{not json")
        assert status == 400 and json.loads(data)["reason"] == "invalid_request"
        status, _, data = client.request(
            "POST", "/api/onboarding/path", body={}, headers={"Content-Length": "x"}
        )
        assert status == 400


def checklist(result):
    return {item["id"]: item["done"] for item in result["checklist"]}


def test_checklist_follows_the_office(tmp_path):
    assert derive(Locator(None))["checklist"] == []
    root = tmp_path / "office"
    initialize(root)
    result = derive(Locator(root))
    assert [item["id"] for item in result["checklist"]] == [
        "account_connected",
        "first_sync",
        "first_run",
        "device_paired",
    ]
    assert all(item["label"] for item in result["checklist"])
    assert not any(checklist(result).values())

    secrets(root)
    accounts(root, [{"id": "simplefin-1", "provider": "simplefin", "last4": "", "role": "cash"}])
    assert checklist(derive(Locator(root))) == {
        "account_connected": True,
        "first_sync": False,
        "first_run": False,
        "device_paired": False,
    }

    ingest(
        root,
        "simplefin",
        [{"account_id": "simplefin-1", "positions": [], "balance": {"net_value": "1"}}],
    )
    assert checklist(derive(Locator(root)))["first_sync"] is True

    runs = root / "cache/serve/runs"
    runs.mkdir(parents=True)
    (runs / "notes.txt").write_text("not a run")
    assert checklist(derive(Locator(root)))["first_run"] is False
    (runs / "run-1.json").write_text("{}")
    assert checklist(derive(Locator(root)))["first_run"] is True

    devices = credentials_dir(root) / "devices.json"
    devices.write_text(json.dumps({"devices": []}))
    assert checklist(derive(Locator(root)))["device_paired"] is False
    devices.write_text("{not json")
    assert checklist(derive(Locator(root)))["device_paired"] is False
    devices.write_text(json.dumps({"devices": [{"id": "d1", "name": "Phone"}]}))
    assert all(checklist(derive(Locator(root))).values())


def test_checklist_reaches_the_route(tmp_path):
    root = synthetic(tmp_path / "office")
    with serving(root, tmp_path) as (_, client):
        items = checklist(client.get("/api/onboarding")[1])
    assert items["account_connected"] and items["first_sync"]
    assert not items["device_paired"]


def test_derive_with_unmigrated_credentials_still_returns_doctor(tmp_path):
    from fo.init import initialize
    from fo.serve.onboarding import derive
    from fo.serve.server import Locator

    root = tmp_path / "office"
    initialize(root)
    config = root / "office.toml"
    config.write_text('[office]\ntimezone = "UTC"\n')
    before = config.read_bytes(), config.stat().st_mtime_ns
    result = derive(Locator(root))
    check = next(c for c in result["doctor"] if c["name"] == "credentials.perms")
    assert check["status"] == "fail"
    assert "doctor --fix" in check["command"]
    assert (config.read_bytes(), config.stat().st_mtime_ns) == before


@pytest.mark.parametrize("ready", [True, False])
def test_onboarding_caches_only_ready_for_25_seconds(tmp_path, monkeypatch, ready):
    from fo.serve import onboarding

    assert ONBOARDING_TTL == 25
    root = synthetic(tmp_path / "office")
    secrets(root)
    calls = []
    checks = [] if ready else [{"name": "providers", "status": "warn", "reason": "Connect"}]

    def diagnose(root):
        calls.append(root)
        return checks

    monkeypatch.setattr(onboarding, "diagnose", diagnose)
    now = [0]
    with serving(root, tmp_path) as (app, client):
        app.cache.clock = lambda: now[0]
        expected = "ready" if ready else "stale"
        assert client.get("/api/onboarding")[1]["state"] == expected
        now[0] = ONBOARDING_TTL - 1
        assert client.get("/api/onboarding")[1]["state"] == expected
        assert len(calls) == (1 if ready else 2)
        checks[:] = [{"name": "providers", "status": "warn", "reason": "Connect"}]
        now[0] = ONBOARDING_TTL
        assert client.get("/api/onboarding")[1]["state"] == "stale"
        assert len(calls) == (2 if ready else 3)
        checks.clear()
        assert client.get("/api/onboarding")[1]["state"] == "ready"
        assert len(calls) == (3 if ready else 4)
        (root / "profile/household.md").write_text("Updated synthetic household")
        now[0] += app.cache.cycle
        assert client.get("/api/onboarding")[1]["state"] == "ready"
        assert len(calls) == (4 if ready else 5)


def test_pairing_and_revoking_refresh_cached_onboarding(tmp_path):
    root = synthetic(tmp_path / "office")
    secrets(root)
    with serving(root, tmp_path, access=remote()) as (app, client):
        app.cache.clock = lambda: 0

        def current():
            status, value = client.get("/api/onboarding", headers=OWNER)
            assert status == 200 and value["state"] == "ready"
            assert ("/api/onboarding", ()) in app.cache.entries
            return checklist(value)["device_paired"]

        assert current() is False
        device = paired(client)
        assert current() is True
        assert client.request("DELETE", f"/api/devices/{device['id']}", headers=OWNER)[0] == 200
        assert current() is False


def test_launching_an_advisor_refreshes_cached_onboarding(tmp_path, monkeypatch):
    root = synthetic(tmp_path / "office")
    secrets(root)
    runner, _ = runner_for(tmp_path, COMPLETE)
    runs = RunManager(runner)
    # Persist the queued run without starting an advisor process.
    monkeypatch.setattr(runs, "begin", lambda *args: None)
    with serving(root, tmp_path, runs=runs) as (app, client):
        app.cache.clock = lambda: 0
        status, before = client.get("/api/onboarding")
        assert status == 200 and before["state"] == "ready"
        assert checklist(before)["first_run"] is False
        assert ("/api/onboarding", ()) in app.cache.entries
        status, record = client.post("/api/runs", {"skill": "research", "subject": "BETA"})
        assert status == 200 and record["status"] == "queued"
        status, after = client.get("/api/onboarding")
        assert status == 200 and after["state"] == "ready"
        assert checklist(after)["first_run"] is True


@pytest.mark.parametrize("stage", ["signature", "fingerprint"])
@pytest.mark.parametrize("error", [OfficeError("unsafe_path", "Unsafe test path"), OSError()])
def test_onboarding_falls_back_when_cache_fingerprinting_fails(tmp_path, monkeypatch, stage, error):
    root = synthetic(tmp_path / "office")
    secrets(root)
    expected = derive(Locator(root))
    assert expected["state"] == "ready"

    def fail(*args):
        raise error

    with serving(root, tmp_path) as (app, client):
        with monkeypatch.context() as failing:
            failing.setattr(f"fo.serve.cache.{stage}", fail)
            status, value = client.get("/api/onboarding")
            assert status == 200 and value == expected
            assert ("/api/onboarding", ()) not in app.cache.entries
        status, value = client.get("/api/onboarding")
        assert status == 200 and value == expected
