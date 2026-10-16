import json
import os
import shlex
from datetime import UTC, datetime, timedelta

import pytest

from fo.init import initialize
from fo.serve.onboarding import derive
from fo.serve.server import Locator
from fo.sync import ingest
from tests.offices import synthetic
from tests.serving import serving


def commands(result):
    return [step["command"] for step in result["steps"]]


def secrets(root, text='[simplefin]\naccess_url = "https://example.invalid/fake"\n'):
    (root / "secrets").chmod(0o700)
    path = root / "secrets/keys.toml"
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


def test_doctor_warning_after_sync_is_stale_with_its_fix(tmp_path):
    root = synthetic(tmp_path / "office")
    secrets(root)
    expiry = (datetime.now(UTC) + timedelta(hours=10)).isoformat().replace("+00:00", "Z")
    token = root / "secrets/schwab-token.json"
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
    (root / "secrets/keys.toml").chmod(0o644)
    (root / ".agents/skills/.fo-stamp.json").unlink()
    profile = json.loads((root / "profile/accounts.json").read_text())
    profile["accounts"][0].pop("role")
    profile["accounts"][0]["type"] = "mystery"
    (root / "profile/accounts.json").write_text(json.dumps(profile))
    items = {item["name"]: item for item in derive(Locator(root))["doctor"]}
    quoted = shlex.quote(str(root))
    assert items["skills.fresh"]["command"] == f"fo skills sync --office {quoted}"
    assert items["secrets.perms"]["command"].startswith("chmod 700 ")
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
