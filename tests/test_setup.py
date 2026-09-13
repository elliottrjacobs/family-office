import json

import httpx
import pytest

from fo.accounts import register
from fo.auth import save_keys
from fo.errors import OfficeError
from fo.init import initialize
from fo.providers.simplefin import SimpleFIN
from fo.setup import setup


def test_discovery_and_registration_preserve_user_metadata(tmp_path):
    root = tmp_path / "office"
    initialize(root)
    registry = root / "profile/accounts.json"
    registry.write_text(
        json.dumps(
            {
                "accounts": [
                    {
                        "id": "my-checking",
                        "provider": "simplefin",
                        "provider_ref": "a",
                        "last4": "1234",
                        "owner": "Household",
                    }
                ]
            }
        )
    )
    client = SimpleFIN(
        "https://user:SECRET@bridge.example/base",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200, json={"accounts": [{"id": "a", "name": "SECRET 123456789"}, {"id": "b"}]}
            )
        ),
    )
    discovered = client.discover()
    ids = register(root, "simplefin", discovered)
    assert ids == ["my-checking", "simplefin-1"]
    assert register(root, "simplefin", list(reversed(discovered))) == list(reversed(ids))
    assert json.loads(registry.read_text())["accounts"][0]["owner"] == "Household"
    assert "SECRET" not in registry.read_text()


def test_ambiguous_schwab_registration_is_atomic(tmp_path):
    root = tmp_path / "office"
    initialize(root)
    registry = root / "profile/accounts.json"
    before = registry.read_bytes()
    with pytest.raises(OfficeError, match="ambiguous"):
        register(root, "schwab", [{"last4": "1234"}, {"last4": "1234"}])
    assert registry.read_bytes() == before


def test_setup_reuses_connection_and_runs_real_sync_pipeline(tmp_path, monkeypatch):
    from fo import setup as workflow

    root = tmp_path / "office"
    initialize(root)
    save_keys(root, {"simplefin": {"access_url": "https://user:SECRET@bridge.example/base"}})
    monkeypatch.setattr(
        workflow, "authenticate", lambda *args: pytest.fail("Should reuse saved connection")
    )
    monkeypatch.setattr(SimpleFIN, "discover", lambda self: [{"provider_ref": "a", "last4": ""}])
    monkeypatch.setattr(
        SimpleFIN,
        "accounts",
        lambda self, registry, **kwargs: [
            {"account_id": registry[0]["id"], "balance": {"net_value": "10"}}
        ],
    )
    first = setup(root, ["simplefin"])
    assert first["status"] == "ready"
    assert first["live_validation"] == "connection_checked"
    second = setup(root, ["simplefin"])
    assert second["sync"][0]["unchanged_since"]
    assert len(json.loads((root / "profile/accounts.json").read_text())["accounts"]) == 1
    assert "SECRET" not in json.dumps(second)


def test_offline_setup_never_authenticates(tmp_path, monkeypatch):
    from fo import setup as workflow

    monkeypatch.setattr(
        workflow, "authenticate", lambda *args: pytest.fail("No authentication offline")
    )
    result = setup(tmp_path / "office", offline=True)
    assert result["status"] == "offline_ready"
    assert result["live_validation"] == "pending"
