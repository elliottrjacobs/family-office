import json

import pytest

from fo.errors import OfficeError
from fo.init import initialize
from fo.office import git
from fo.store.index import project, read_state, reindex
from fo.sync import ingest, synchronize
from tests.test_store import snapshot


@pytest.fixture
def office(tmp_path):
    root = tmp_path / "office"
    initialize(root)
    return root


def test_read_only_index_never_creates_sidecars(office):
    ingest(office, "fixture", snapshot({"ACME": 100}))
    reindex(office)
    before = {str(p.relative_to(office)) for p in office.rglob("*")}
    assert read_state(office, read_only=True)["positions"][0]["symbol"] == "ACME"
    assert {str(p.relative_to(office)) for p in office.rglob("*")} == before


def test_unexpected_provider_shape_does_not_block_other_provider(office, monkeypatch):
    from fo.auth import save_keys
    from fo.providers.schwab import Schwab
    from fo.providers.simplefin import SimpleFIN

    (office / "profile/accounts.json").write_text(
        json.dumps(
            {
                "accounts": [
                    {"id": "a", "provider": "schwab", "last4": "1234"},
                    {"id": "b", "provider": "simplefin", "last4": "5678"},
                ]
            }
        )
    )
    save_keys(office, {"simplefin": {"access_url": "https://u:p@bridge.example/base"}})
    monkeypatch.setattr(
        Schwab, "__init__", lambda *args: (_ for _ in ()).throw(ValueError("SENTINEL"))
    )
    monkeypatch.setattr(SimpleFIN, "accounts", lambda *args, **kwargs: [])
    results = synchronize(office)
    assert [r["status"] for r in results] == ["failed", "complete"]
    assert "SENTINEL" not in json.dumps(results)


def test_remote_publication_requires_history_scan(office, tmp_path, monkeypatch):
    import shutil

    from fo.commits import commit_office

    remote = tmp_path / "remote"
    remote.mkdir()
    git(remote, "init", "--bare", "-q")
    git(office, "remote", "add", "origin", str(remote))
    settings = office / "office.toml"
    settings.write_text(settings.read_text().replace('remote = ""', 'remote = "origin"'))
    git(office, "add", "office.toml")
    git(
        office,
        "-c",
        "user.name=Fixture",
        "-c",
        "user.email=fixture@example.invalid",
        "commit",
        "-qm",
        "Configure remote",
    )
    monkeypatch.setattr(shutil, "which", lambda name: None)
    with pytest.raises(OfficeError) as error:
        commit_office(office)
    assert error.value.reason == "scanner_missing"
    assert not git(remote, "show-ref", check=False).stdout


def test_import_consumed_once_and_live_snapshot_preserved(office):
    registry = {
        "accounts": [
            {"id": "a", "provider": "simplefin", "provider_ref": "bridge-a", "last4": "1234"}
        ]
    }
    (office / "profile/accounts.json").write_text(json.dumps(registry))
    ingest(office, "simplefin", snapshot({"ACME": 100}))
    (office / "imports/monarch.csv").write_text(
        "Date,Merchant,Category,Account,Original Statement,Amount\n2026-08-01,Shop,Shopping,a,Shop,-10\n"
    )
    with pytest.raises(OfficeError, match="historical"):
        from fo.providers.imports import accounts

        accounts(office)
    result = synchronize(office, provider="csv", before="2026-09-01")
    assert result[0]["transaction_rows"] == 1
    assert project(office)["positions"][0]["symbol"] == "ACME"
    assert synchronize(office, provider="csv", before="2026-09-01")[0]["transaction_rows"] == 0
