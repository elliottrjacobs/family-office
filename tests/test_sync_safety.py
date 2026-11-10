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


@pytest.mark.parametrize(
    "relative", ["reports/.claude/settings.json", "reports/x/.git/config", "reports/a/.hooks.md"]
)
def test_commit_refuses_hidden_paths_under_reports(office, relative):
    from fo.commits import commit_office

    head = git(office, "rev-parse", "HEAD").stdout
    (office / "reports/research").mkdir(parents=True, exist_ok=True)
    (office / "reports/research/ok.md").write_text("fine\n")
    target = office / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("{}\n")
    with pytest.raises(OfficeError) as error:
        commit_office(office)
    assert error.value.reason == "unsafe_path"
    assert git(office, "rev-parse", "HEAD").stdout == head
    assert not git(office, "diff", "--cached", "--name-only").stdout


@pytest.mark.parametrize("ambiguous", [False, True])
def test_simplefin_unmapped_accounts_do_not_block_sync(office, monkeypatch, ambiguous):
    import httpx

    from fo.auth import save_keys
    from fo.doctor import diagnose
    from fo.providers.simplefin import SimpleFIN
    from fo.store.jsonl import read_rows

    registry = [{"id": "a", "provider": "simplefin", "provider_ref": "bridge-a", "last4": ""}]
    if ambiguous:
        registry.append({**registry[0], "id": "b"})
    (office / "profile/accounts.json").write_text(json.dumps({"accounts": registry}))
    save_keys(office, {"simplefin": {"access_url": "https://u:p@bridge.example/base"}})
    body = {
        "accounts": [
            {"id": "bridge-a", "balance": "15.20", "balance-date": 1789200000},
            {"id": "PRIVATE-UNMAPPED"},
        ]
    }
    original = SimpleFIN.__init__

    def initialize_adapter(self, access_url, timezone):
        original(
            self,
            access_url,
            timezone=timezone,
            transport=httpx.MockTransport(lambda req: httpx.Response(200, json=body)),
        )

    monkeypatch.setattr(SimpleFIN, "__init__", initialize_adapter)
    result = synchronize(office, provider="simplefin")[0]
    log = read_rows(office, "data/sync_log.jsonl")[-1]
    assert (log["status"], log.get("unmapped_accounts")) == (
        ("failed", None) if ambiguous else ("complete", 1)
    )
    if ambiguous:
        assert result["status"] == "failed"
        assert result["reason"] == "unmapped_account"
        assert project(office)["balances"] == []
    else:
        assert result["status"] == "complete"
        assert result["unmapped_accounts"] == 1
        assert result["account_ids"] == ["a"]
        assert project(office)["balances"][0]["net_value"] == "15.20"
        assert any(
            c["name"] == "sync.unmapped.simplefin" and c["status"] == "warn"
            for c in diagnose(office)
        )
        body["accounts"].pop()
        assert synchronize(office, provider="simplefin")[0]["unmapped_accounts"] == 0
        assert not any(c["name"] == "sync.unmapped.simplefin" for c in diagnose(office))
    assert "PRIVATE-UNMAPPED" not in json.dumps(result)
