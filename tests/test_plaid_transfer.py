"""Moving Plaid Items between two synthetic Macs that share one office.

Each Mac is a separate credentials folder (FO_CREDENTIALS_HOME) over the same office,
as two machines over one iCloud Drive office would be. Tokens are sentinels.
"""

import json
import stat

import httpx
import pytest
from typer.testing import CliRunner

from fo import sealed
from fo.auth import save_keys
from fo.cli import app
from fo.config import read_secrets
from fo.errors import OfficeError
from fo.init import initialize
from fo.providers import plaid
from fo.providers.plaid import load_items, save_items
from fo.providers.plaid_transfer import export_items, import_items
from fo.sync import synchronize
from tests.test_plaid import ACCESS, CLIENT, OTHER, SECRET, FakePlaid

PASSPHRASE = "PASSPHRASE_SENTINEL wombat kettle"
OWN = "access-sandbox-OWN_SENTINEL"
NEWER = "access-sandbox-NEWER_SENTINEL"
SENTINELS = (CLIENT, SECRET, ACCESS, OTHER, OWN, NEWER, PASSPHRASE, "CURSOR_SENTINEL")
BANK = {
    "item_id": "item-bank",
    "access_token": ACCESS,
    "institution": "First Platypus Bank",
    "institution_id": "ins_1",
    "cursor": "CURSOR_SENTINEL_1",
}
BROKER = {
    "item_id": "item-broker",
    "access_token": OTHER,
    "institution": "Wombat Brokerage",
    "institution_id": "ins_2",
    "cursor": "",
}
MINE = {
    "item_id": "item-own",
    "access_token": OWN,
    "institution": "Echidna Credit Union",
    "institution_id": "ins_3",
    "cursor": "",
}


@pytest.fixture(autouse=True)
def quick_scrypt(monkeypatch):
    monkeypatch.setattr(sealed, "SCRYPT_N", 2**10)


@pytest.fixture
def fake(monkeypatch):
    server = FakePlaid()
    server.items[OWN] = {"products": [], "accounts": []}
    monkeypatch.setattr(plaid, "TRANSPORT", httpx.MockTransport(server))
    return server


@pytest.fixture
def office(tmp_path, monkeypatch):
    monkeypatch.setattr("platform.node", lambda: "example-host")
    root = tmp_path / "office"
    initialize(root)
    registry = [
        {"id": f"plaid-{n}", "provider": "plaid", "last4": "", "provider_ref": ref}
        for n, ref in enumerate(("acc-checking", "acc-card", "acc-ira"), 1)
    ]
    (root / "profile/accounts.json").write_text(json.dumps({"accounts": registry}))
    return root


@pytest.fixture
def mac(tmp_path, monkeypatch):
    """mac("a") makes later credential reads and writes those of Mac a."""

    def use(name):
        monkeypatch.setenv("FO_CREDENTIALS_HOME", str(tmp_path / ("mac-" + name)))

    return use


def keys(root, client=CLIENT, environment="sandbox"):
    save_keys(root, {"plaid": {"client_id": client, "secret": SECRET, "environment": environment}})


def answers(*values):
    values = iter(values)
    return lambda *args, **kwargs: next(values)


def reply(value):
    asked = []

    def confirm(text, default=None):
        asked.append(text)
        return value

    confirm.asked = asked
    return confirm


def exported(root, path, wanted=None):
    return export_items(root, path, answers(PASSPHRASE), wanted)


def imported(root, path, confirm=None, prompt=None):
    return import_items(root, path, prompt or answers(PASSPHRASE), confirm or reply(False))


def macbook(root, mac):
    mac("a")
    keys(root)
    save_items(root, [BANK, BROKER])


def test_items_move_to_another_mac_and_keep_their_account_ids(office, fake, mac, tmp_path):
    macbook(office, mac)
    path = tmp_path / "items.fo-transfer"
    result = exported(office, path)
    assert result["exported"] == 2
    assert [i["institution"] for i in result["items"]] == [
        "First Platypus Bank",
        "Wombat Brokerage",
    ]
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    sealed_bytes = path.read_bytes()
    for sentinel in SENTINELS:
        assert sentinel.encode() not in sealed_bytes
    registry = (office / "profile/accounts.json").read_bytes()

    mac("b")
    keys(office)
    save_items(office, [MINE])
    result = imported(office, path)
    assert (result["imported"], result["already_linked"]) == (2, 0)
    assert result["file_removed"] is True and not path.exists()
    assert result["keys_saved"] is False
    # The target keeps its own Item, and the moved ones arrive whole, cursor and all.
    assert load_items(office) == [MINE, BANK, BROKER]
    assert not any(p == "/item/get" for p, _, _ in fake.requests)
    assert (office / "profile/accounts.json").read_bytes() == registry

    [synced] = synchronize(office)
    assert synced["status"] == "complete"
    assert sorted(synced["account_ids"]) == ["plaid-1", "plaid-2", "plaid-3"]
    assert (office / "profile/accounts.json").read_bytes() == registry

    mac("a")
    assert load_items(office) == [BANK, BROKER]


def test_export_chooses_items_by_institution_or_item_id(office, mac, tmp_path):
    macbook(office, mac)
    result = exported(office, tmp_path / "one", ["  wombat brokerage "])
    assert [i["item_id"] for i in result["items"]] == ["item-broker"]
    result = exported(office, tmp_path / "two", ["item-bank", "First Platypus Bank"])
    assert [i["item_id"] for i in result["items"]] == ["item-bank"]
    with pytest.raises(OfficeError) as caught:
        exported(office, tmp_path / "three", ["Quokka Savings"])
    assert caught.value.reason == "unknown_item"
    assert "First Platypus Bank, Wombat Brokerage" in caught.value.message
    assert not (tmp_path / "three").exists()

    mac("b")
    keys(office)
    result = imported(office, tmp_path / "one")
    assert result["imported"] == 1 and load_items(office) == [BROKER]


def test_an_item_already_on_the_target_keeps_the_targets_token(office, mac, tmp_path):
    macbook(office, mac)
    path = tmp_path / "items"
    exported(office, path)
    mac("b")
    keys(office)
    own_copy = {**BANK, "access_token": NEWER, "cursor": "c-target"}
    save_items(office, [own_copy])
    result = imported(office, path)
    assert (result["imported"], result["already_linked"]) == (1, 1)
    assert {i["item_id"]: i["status"] for i in result["items"]} == {
        "item-bank": "already_linked",
        "item-broker": "imported",
    }
    assert load_items(office) == [own_copy, BROKER]
    assert not path.exists()


def test_an_institution_linked_again_here_is_imported_only_on_a_yes(office, mac, tmp_path):
    macbook(office, mac)
    exported(office, tmp_path / "first")
    exported(office, tmp_path / "second")
    mac("b")
    keys(office)
    relinked = {**MINE, "item_id": "item-relinked", "institution_id": "ins_1"}
    save_items(office, [relinked])
    declined = reply(False)
    result = imported(office, tmp_path / "first", declined)
    assert result["skipped_same_institution"] == 1 and result["imported"] == 1
    assert [i["item_id"] for i in load_items(office)] == ["item-relinked", "item-broker"]
    assert len(declined.asked) == 1 and "First Platypus Bank" in declined.asked[0]
    assert not any(s in declined.asked[0] for s in SENTINELS)

    accepted = reply(True)
    result = imported(office, tmp_path / "second", accepted)
    assert (result["imported"], result["already_linked"]) == (1, 1)
    assert [i["item_id"] for i in load_items(office)] == [
        "item-relinked",
        "item-broker",
        "item-bank",
    ]


@pytest.mark.parametrize(
    "client, environment", [("CLIENT_OTHER", "sandbox"), (CLIENT, "production")]
)
def test_another_client_or_environment_changes_nothing(office, mac, tmp_path, client, environment):
    macbook(office, mac)
    path = tmp_path / "items"
    exported(office, path)
    mac("b")
    keys(office, client=client, environment=environment)
    save_items(office, [MINE])
    with pytest.raises(OfficeError) as caught:
        imported(office, path)
    assert caught.value.reason == "plaid_client_mismatch"
    assert load_items(office) == [MINE]
    assert path.exists()
    assert not any(s in caught.value.message for s in SENTINELS)


def test_wrong_passphrase_changed_file_or_other_office_change_nothing(
    office, mac, tmp_path, monkeypatch
):
    macbook(office, mac)
    path = tmp_path / "items"
    exported(office, path)
    mac("b")
    keys(office)
    with pytest.raises(OfficeError) as caught:
        imported(office, path, prompt=answers("not the passphrase at all"))
    assert caught.value.reason == "transfer_rejected"
    document = json.loads(path.read_bytes())
    first = document["ciphertext"][0]
    document["ciphertext"] = ("B" if first == "A" else "A") + document["ciphertext"][1:]
    changed = tmp_path / "changed"
    changed.write_text(json.dumps(document))
    with pytest.raises(OfficeError) as caught:
        imported(office, changed)
    assert caught.value.reason == "transfer_rejected"
    assert load_items(office) == [] and path.exists() and changed.exists()

    other = tmp_path / "other-office"
    initialize(other)
    with pytest.raises(OfficeError) as caught:
        imported(other, path)
    assert caught.value.reason == "office_mismatch"
    assert path.exists()


def test_a_mac_without_keys_saves_them_only_after_plaid_accepts(office, fake, mac, tmp_path):
    macbook(office, mac)
    path = tmp_path / "items"
    exported(office, path)
    mac("b")
    for typed, reason in (
        (("CLIENT_TYPO", SECRET), "plaid_client_mismatch"),
        ((CLIENT, "WRONG_SECRET"), "invalid_credentials"),
    ):
        with pytest.raises(OfficeError) as caught:
            imported(office, path, prompt=answers(PASSPHRASE, *typed))
        assert caught.value.reason == reason
        assert read_secrets(office) == {} and load_items(office) == []
        assert path.exists()
    fake.items[ACCESS]["error"] = {"error_code": "ITEM_LOGIN_REQUIRED"}
    result = imported(office, path, prompt=answers(PASSPHRASE, CLIENT, SECRET))
    assert result["keys_saved"] is True and result["imported"] == 2
    assert read_secrets(office)["plaid"] == {
        "client_id": CLIENT,
        "secret": SECRET,
        "environment": "sandbox",
    }
    assert load_items(office) == [BANK, BROKER] and not path.exists()


def test_export_refuses_unsafe_destinations_and_weak_passphrases(office, mac, tmp_path):
    with pytest.raises(OfficeError) as caught:
        exported(office, tmp_path / "none")
    assert caught.value.reason == "missing_credentials"
    macbook(office, mac)
    existing = tmp_path / "existing"
    existing.write_text("keep me")
    refusals = {
        office / "items": "unsafe_path",
        office / "reports/items": "unsafe_path",
        existing: "file_exists",
        tmp_path / "missing/items": "invalid_path",
    }
    for path, reason in refusals.items():
        with pytest.raises(OfficeError) as caught:
            exported(office, path)
        assert caught.value.reason == reason
    assert existing.read_text() == "keep me"
    cloud = tmp_path / "Library/Mobile Documents/com~apple~CloudDocs"
    cloud.mkdir(parents=True)
    assert "Recently Deleted" in exported(office, cloud / "items")["note"]
    assert "Recently Deleted" not in exported(office, tmp_path / "local")["note"]
    assert not (office / "items").exists() and not (office / "reports/items").exists()
    with pytest.raises(OfficeError) as caught:
        export_items(office, tmp_path / "weak", answers("short"))
    assert caught.value.reason == "weak_passphrase"
    assert not (tmp_path / "weak").exists()


def test_a_failed_write_leaves_no_file_and_a_failed_merge_keeps_it(
    office, mac, tmp_path, monkeypatch
):
    import os

    from fo.providers import plaid_transfer

    macbook(office, mac)

    def broken(fd):
        raise OSError("disk full")

    with monkeypatch.context() as patch:
        patch.setattr(os, "fsync", broken)
        with pytest.raises(OfficeError) as caught:
            exported(office, tmp_path / "partial")
    assert caught.value.reason == "transfer_failed"
    assert not (tmp_path / "partial").exists()

    path = tmp_path / "items"
    exported(office, path)
    mac("b")
    keys(office)
    with monkeypatch.context() as patch:
        patch.setattr(plaid_transfer, "save_items", lambda root, items: None)
        with pytest.raises(OfficeError) as caught:
            imported(office, path)
    assert caught.value.reason == "credentials_unavailable"
    assert path.exists() and load_items(office) == []

    class Stuck(type(path)):
        def unlink(self, missing_ok=False):
            raise PermissionError("read-only volume")

    monkeypatch.setattr(
        plaid_transfer, "read_transfer", lambda given: (Stuck(given), given.read_bytes())
    )
    result = imported(office, path)
    assert result["imported"] == 2 and result["file_removed"] is False
    assert "could not be deleted" in result["note"] and path.exists()


def test_cli_moves_items_without_printing_a_secret(office, fake, mac, tmp_path, monkeypatch):
    import typer

    macbook(office, mac)
    monkeypatch.setattr(typer, "prompt", lambda *args, **kwargs: PASSPHRASE)
    runner = CliRunner()
    path = tmp_path / "items"

    def fo(*args):
        result = runner.invoke(app, ["--office", str(office), "--json", "auth", "plaid", *args])
        for stream in (result.output, result.stdout, result.stderr):
            assert not any(s in stream for s in SENTINELS)
        return result

    result = fo("--export", str(path), "--item", "Wombat Brokerage")
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["exported"] == 1
    mac("b")
    keys(office)
    result = fo("--import", str(path))
    assert result.exit_code == 0, result.output
    body = json.loads(result.stdout)
    assert body["imported"] == 1 and body["file_removed"] is True
    assert not path.exists() and load_items(office) == [BROKER]

    for args, reason in (
        (["--import", str(path)], "invalid_path"),
        (["--export", str(path), "--import", str(path)], "invalid_request"),
        (["--import", str(path), "--item", "x"], "invalid_request"),
        (["--item", "x"], "invalid_request"),
    ):
        result = fo(*args)
        assert result.exit_code == 1 and json.loads(result.stdout)["reason"] == reason
    result = runner.invoke(
        app, ["--office", str(office), "--json", "auth", "simplefin", "--export", str(path)]
    )
    assert json.loads(result.stdout)["reason"] == "invalid_request"
    result = runner.invoke(
        app,
        ["--office", str(office), "--json", "--read-only", "auth", "plaid", "--export", str(path)],
    )
    assert json.loads(result.stdout)["reason"] == "read_only" and not path.exists()
