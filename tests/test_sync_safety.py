import json
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from fo.cli import app
from fo.errors import OfficeError
from fo.init import initialize
from fo.office import git
from fo.store.index import project, read_state, reindex
from fo.sync import ingest, synchronize
from tests.test_store import snapshot


@pytest.fixture
def office(tmp_path, monkeypatch):
    monkeypatch.setattr("platform.node", lambda: "example-host")
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
        assert result["reason"] == "ambiguous_account"
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


@pytest.mark.parametrize("provider", ["simplefin", "schwab"])
@pytest.mark.parametrize("returned_accounts", [False, True])
@pytest.mark.parametrize("dry_run", [False, True])
def test_no_mapped_accounts_fail_without_completing(
    office, monkeypatch, provider, returned_accounts, dry_run
):
    import httpx

    from fo.auth import save_keys
    from fo.doctor import diagnose
    from fo.providers.schwab import Schwab
    from fo.providers.simplefin import SimpleFIN
    from fo.serve.onboarding import derive
    from fo.serve.server import Locator
    from fo.store.jsonl import read_rows

    registry = [
        {
            "id": "a",
            "provider": provider,
            "provider_ref": "bridge-a",
            "last4": "1234",
            "role": "cash",
        }
    ]
    (office / "profile/accounts.json").write_text(json.dumps({"accounts": registry}))
    save_keys(office, {provider: {"access_url": "https://u:p@bridge.example/base"}})
    if provider == "simplefin":
        body = {"accounts": [{"id": "PRIVATE-UNMAPPED"}] if returned_accounts else []}
        original = SimpleFIN.__init__

        def initialize_adapter(self, access_url, timezone):
            original(
                self,
                access_url,
                timezone=timezone,
                transport=httpx.MockTransport(lambda req: httpx.Response(200, json=body)),
            )

        monkeypatch.setattr(SimpleFIN, "__init__", initialize_adapter)
    else:
        body = [{"securitiesAccount": {"accountNumber": "99990000"}}] if returned_accounts else []

        class Client:
            def get_accounts(self, fields=None):
                return httpx.Response(
                    200, json=body, request=httpx.Request("GET", "https://api.example/accounts")
                )

        original = Schwab.__init__

        def initialize_adapter(self, root, timezone):
            original(self, root, client=Client(), timezone=timezone)

        monkeypatch.setattr(Schwab, "__init__", initialize_adapter)

    commits = []
    monkeypatch.setattr("fo.commits.commit_office", lambda *args, **kwargs: commits.append(True))
    args = ["sync", "--provider", provider, "--commit", "--json", "--office", str(office)]
    if dry_run:
        args.append("--dry-run")
    response = CliRunner().invoke(app, args)
    result = json.loads(response.output)[0]
    assert response.exit_code == (1 if returned_accounts else 0)
    assert result["status"] == ("failed" if returned_accounts else "complete")
    assert commits == ([] if dry_run else [True])
    logs = read_rows(office, "data/sync_log.jsonl")
    log = {k: v for k, v in result.items() if k != "dry_run"}
    assert logs == ([] if dry_run else [log])
    if returned_accounts:
        assert result["reason"] == "no_mapped_accounts"
        assert result["unmapped_accounts"] == 1
        assert f"fo auth {provider}" in result["message"] and "then `fo sync`" in result["message"]
        if provider == "simplefin":
            assert "new SimpleFIN setup token" in result["message"]
        assert "PRIVATE-UNMAPPED" not in response.output and "99990000" not in response.output
        assert project(office)["providers"] == {}
        checks = {c["name"]: c for c in diagnose(office)}
        assert checks["sync.age"]["status"] == "warn"
        assert f"sync.age.{provider}" not in checks
        if not dry_run:
            assert checks[f"sync.unmapped.{provider}"]["status"] == "warn"
            assert f"fo auth {provider}" in checks[f"sync.unmapped.{provider}"]["reason"]
            if provider == "simplefin":
                assert "new SimpleFIN setup token" in checks[f"sync.unmapped.{provider}"]["reason"]
        onboarding = derive(Locator(office))
        assert onboarding["last_sync"] is None
        assert not next(c["done"] for c in onboarding["checklist"] if c["id"] == "first_sync")
        if not dry_run:
            assert onboarding["steps"][0]["command"].startswith(f"fo auth {provider} ")
            assert onboarding["steps"][-1]["command"].startswith("fo sync ")
    else:
        assert result["account_ids"] == []


@pytest.mark.parametrize("dry_run", [False, True])
@pytest.mark.parametrize("mapped", [False, True])
def test_simplefin_institution_errors_keep_counts_and_point_to_provider(
    office, monkeypatch, dry_run, mapped
):
    import httpx

    from fo.auth import save_keys
    from fo.doctor import diagnose
    from fo.providers.simplefin import SimpleFIN
    from fo.serve.onboarding import derive
    from fo.serve.server import Locator
    from fo.store.jsonl import read_rows

    registry = [
        {
            "id": "a",
            "provider": "simplefin",
            "provider_ref": "bridge-a",
            "last4": "",
            "role": "cash",
        }
    ]
    (office / "profile/accounts.json").write_text(json.dumps({"accounts": registry}))
    save_keys(office, {"simplefin": {"access_url": "https://u:p@bridge.example/base"}})
    body = {
        "accounts": [{"id": "PRIVATE-UNMAPPED"}],
        "errors": ["PRIVATE-INSTITUTION-ERROR"],
    }
    if mapped:
        body["accounts"].append({"id": "bridge-a", "balance": "15.20", "balance-date": 1789200000})
    original = SimpleFIN.__init__

    def initialize_adapter(self, access_url, timezone):
        original(
            self,
            access_url,
            timezone=timezone,
            transport=httpx.MockTransport(lambda req: httpx.Response(200, json=body)),
        )

    monkeypatch.setattr(SimpleFIN, "__init__", initialize_adapter)
    result = synchronize(office, provider="simplefin", dry_run=dry_run)[0]
    assert result["status"] == ("complete" if mapped else "failed")
    assert result["provider_errors"] == 1
    assert result["unmapped_accounts"] == 1
    if not mapped:
        assert result["reason"] == "institution_errors"
        assert "repair them at the provider" in result["message"]
        assert "fo auth" not in result["message"]
        assert project(office)["providers"] == {}
    logs = read_rows(office, "data/sync_log.jsonl")
    assert logs == ([] if dry_run else [{k: v for k, v in result.items() if k != "dry_run"}])
    if not dry_run:
        checks = [c for c in diagnose(office) if c["name"] == "sync.errors.simplefin"]
        assert len(checks) == 1 and checks[0]["status"] == "warn"
        if not mapped:
            onboarding = derive(Locator(office))
            assert onboarding["state"] == "never_synced"
            assert len(onboarding["steps"]) == 1
            assert onboarding["steps"][0]["command"].startswith("fo sync ")
            assert "Repair the institution connection" in onboarding["steps"][0]["purpose"]
            assert "fo auth" not in json.dumps(onboarding["steps"])
        body["errors"] = []
        body["accounts"] = [{"id": "bridge-a", "balance": "15.20", "balance-date": 1789200000}]
        assert synchronize(office, provider="simplefin")[0]["status"] == "complete"
        assert not any(c["name"] == "sync.errors.simplefin" for c in diagnose(office))
    assert "PRIVATE-UNMAPPED" not in json.dumps(result)
    assert "PRIVATE-INSTITUTION-ERROR" not in json.dumps(result) + json.dumps(logs)


def test_empty_ingest_with_institution_errors_does_not_complete(office):
    from fo.store.jsonl import read_rows

    with pytest.raises(OfficeError) as error:
        ingest(office, "simplefin", [], provider_errors=2)
    assert error.value.reason == "institution_errors"
    assert read_rows(office, "data/sync_log.jsonl") == []


def test_record_includes_a_new_managed_file_and_skips_unchanged_files(office):
    from fo.commits import record

    path = office / ".claude/local.json"
    path.write_text("{}\n")
    record(office, [".claude/local.json"], "Record synthetic settings")
    assert git(office, "show", "HEAD:.claude/local.json").stdout == "{}\n"
    assert git(office, "status", "--porcelain").stdout == ""
    head = git(office, "rev-parse", "HEAD").stdout
    record(office, [".claude/local.json"], "No changes")
    assert git(office, "rev-parse", "HEAD").stdout == head


@pytest.mark.parametrize("source", ["Unrelated.md", "profile/unrelated.md"])
def test_record_preserves_unrelated_staged_rename(office, source):
    from fo.commits import record

    (office / source).write_text("Unrelated contents\n")
    record(office, [source], "Create synthetic note")
    git(office, "mv", "--", source, "profile/renamed.md")
    before = git(office, "diff", "--cached", "--raw").stdout
    (office / ".claude/local.json").write_text("{}\n")
    record(office, [".claude/local.json"], "Record synthetic settings")
    assert git(office, "show", f"HEAD:{source}").stdout == "Unrelated contents\n"
    assert git(office, "cat-file", "-e", "HEAD:profile/renamed.md", check=False).returncode
    assert git(office, "diff", "--cached", "--raw").stdout == before
    assert git(office, "show", "--format=", "--name-only", "HEAD").stdout.splitlines() == [
        ".claude/local.json"
    ]


def test_record_without_a_repository_does_not_create_one(tmp_path):
    from fo.commits import record

    (tmp_path / "office.toml").write_text('[office]\nid = "fixture"\n')
    record(tmp_path, ["office.toml"], "Record synthetic settings")
    assert sorted(p.name for p in tmp_path.iterdir()) == ["office.toml"]


@pytest.mark.parametrize("command", ["office", "record"])
def test_commits_do_not_conclude_a_conflicted_merge(office, command):
    from fo.commits import commit_office, record

    identity = ["-c", "user.name=t", "-c", "user.email=t@example.invalid"]
    note = office / "notebook/plan.md"
    base = git(office, "symbolic-ref", "--short", "HEAD").stdout.strip()
    git(office, "checkout", "-qb", "other")
    note.write_text("other host\n")
    git(office, "add", "--", "notebook")
    git(office, *identity, "commit", "-qm", "other")
    git(office, "checkout", "-q", base)
    note.write_text("this host\n")
    git(office, "add", "--", "notebook")
    git(office, *identity, "commit", "-qm", "mine")
    assert git(office, *identity, "merge", "other", check=False).returncode
    head = git(office, "rev-parse", "HEAD").stdout
    status = git(office, "status", "--porcelain").stdout
    with pytest.raises(OfficeError) as error:
        if command == "office":
            commit_office(office)
        else:
            record(office, ["notebook/plan.md"], "Record plan")
    assert error.value.reason == "merge_in_progress"
    assert (
        error.value.message
        == "Finish or abort the Git merge or rebase in the office before fo commits."
    )
    assert git(office, "rev-parse", "HEAD").stdout == head
    assert git(office, "status", "--porcelain").stdout == status
    assert "<<<<<<<" not in git(office, "show", "HEAD:notebook/plan.md").stdout


@pytest.mark.parametrize("command", ["office", "record"])
@pytest.mark.parametrize(
    "marker", ["MERGE_HEAD", "REBASE_HEAD", "CHERRY_PICK_HEAD", "rebase-merge", "rebase-apply"]
)
def test_commits_refuse_unfinished_git_operations_even_when_clean(office, marker, command):
    from fo.commits import commit_office, record

    marker_path = Path(git(office, "rev-parse", "--git-path", marker).stdout.strip())
    marker_path = office / marker_path
    if marker.startswith("rebase-"):
        marker_path.mkdir()
    else:
        marker_path.write_text(git(office, "rev-parse", "HEAD").stdout)
    with pytest.raises(OfficeError) as error:
        if command == "office":
            commit_office(office)
        else:
            record(office, ["office.toml"], "Record settings")
    assert error.value.reason == "merge_in_progress"


@pytest.mark.parametrize("command", ["office", "record"])
@pytest.mark.parametrize(
    "status,stages",
    [
        ("DD", [1]),
        ("AU", [2]),
        ("UD", [1, 2]),
        ("UA", [3]),
        ("DU", [1, 3]),
        ("AA", [2, 3]),
        ("UU", [1, 2, 3]),
    ],
)
def test_commits_refuse_unmerged_index_without_operation_markers(office, status, stages, command):
    from fo.commits import commit_office, record

    path = "notebook/corrections.md"
    oid = git(office, "rev-parse", f"HEAD:{path}").stdout.strip()
    entries = f"0 {'0' * 40}\t{path}\n" + "".join(
        f"100644 {oid} {stage}\t{path}\n" for stage in stages
    )
    subprocess.run(
        ["git", "-C", str(office), "update-index", "--index-info"],
        input=entries,
        text=True,
        check=True,
    )
    before = git(office, "status", "--porcelain").stdout
    assert before.startswith(status + " ")
    head = git(office, "rev-parse", "HEAD").stdout
    with pytest.raises(OfficeError) as error:
        if command == "office":
            commit_office(office)
        else:
            record(office, ["office.toml"], "Record settings")
    assert error.value.reason == "merge_in_progress"
    assert git(office, "status", "--porcelain").stdout == before
    assert git(office, "rev-parse", "HEAD").stdout == head


@pytest.mark.parametrize("writer", [False, True])
def test_sync_if_writer_skips_without_writes_or_syncs(office, monkeypatch, writer):
    from fo.config import set_config
    from fo.store.jsonl import read_rows

    (office / "profile/accounts.json").write_text(
        json.dumps({"accounts": [{"id": "a", "provider": "csv", "last4": "", "role": "cash"}]})
    )
    (office / "imports/monarch.csv").write_text(
        "Date,Merchant,Category,Account,Original Statement,Amount\n2026-08-01,Shop,Shopping,a,Shop,-10\n"
    )
    if not writer:
        set_config(office, "hosts.writer", "example-mac.local")
    commits = []
    monkeypatch.setattr("fo.commits.commit_office", lambda *args, **kwargs: commits.append(True))
    monkeypatch.setattr(
        "fo.operations.notification", lambda *args: pytest.fail("Unexpected notification")
    )
    before = {p: p.read_bytes() for p in office.rglob("*") if p.is_file()}
    args = ["sync", "--commit", "--if-writer", "--json", "--office", str(office)]
    response = CliRunner().invoke(app, args)
    assert response.exit_code == 0, response.output
    results = json.loads(response.output)
    if writer:
        assert results[0]["status"] == "complete"
        assert results[0]["transaction_rows"] == 1
        assert read_rows(office, "data/sync_log.jsonl") == [
            {k: v for k, v in results[0].items() if k != "dry_run"}
        ]
        assert commits == [True]
    else:
        assert results[0]["status"] == "skipped"
        assert results[0]["reason"] == "not_writer"
        assert commits == []
        assert {p: p.read_bytes() for p in office.rglob("*") if p.is_file()} == before
        assert read_rows(office, "data/sync_log.jsonl") == []
        assert commits == []
        response = CliRunner().invoke(app, [a for a in args if a != "--if-writer"])
        assert response.exit_code == 1
        assert json.loads(response.output)["reason"] == "not_writer"
