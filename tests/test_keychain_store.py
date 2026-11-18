"""Credentials in the macOS Keychain: storage, migration both ways, and safe failures.

The Keychain is faked with a dict, so these run on any system and never touch a real
keychain. One opt-in test at the end round-trips synthetic bytes through the real one.
"""

import json
import os
import secrets
import sys

import pytest

from fo import keychain
from fo.config import (
    credential_exists,
    credential_store,
    credentials_dir,
    ensure_credentials,
    provider_key,
    read_secrets,
    set_config,
)
from fo.errors import OfficeError

KEYS = b'[fred]\n"api_key" = "synthetic-fred"\n'
ITEMS = {"items": [{"item_id": "item-1", "access_token": "synthetic-access", "cursor": ""}]}


class FakeKeychain:
    def __init__(self, monkeypatch):
        self.items = {}
        self.refuse = set()
        self.calls = 0
        for name in ("read", "exists", "write", "delete"):
            monkeypatch.setattr(keychain, name, getattr(self, name))

    def check(self, operation):
        self.calls += 1
        if operation in self.refuse:
            raise keychain.KeychainError(-25308)

    def read(self, service, account):
        self.check("read")
        return self.items.get((service, account))

    def exists(self, service, account):
        self.check("exists")
        return (service, account) in self.items

    def write(self, service, account, data, label):
        self.check("write")
        assert isinstance(data, bytes) and data and label.startswith("Family Office: ")
        self.items[(service, account)] = data

    def delete(self, service, account):
        self.check("delete")
        self.items.pop((service, account), None)

    def names(self):
        return sorted(account for _, account in self.items)


@pytest.fixture
def fake(monkeypatch):
    monkeypatch.setattr("fo.config.sys.platform", "darwin")
    return FakeKeychain(monkeypatch)


@pytest.fixture
def office(tmp_path):
    from fo.init import initialize

    root = tmp_path / "office"
    initialize(root)
    return root


def service(root):
    return "com.familyoffice.credentials." + credentials_dir(root).name


def checks(root):
    from fo.doctor import diagnose

    return {c["name"]: c for c in diagnose(root)}


def test_store_choice(office, fake, monkeypatch):
    assert credential_store(office) == "file"  # FO_CREDENTIALS_HOME is set in tests
    monkeypatch.delenv("FO_CREDENTIALS_HOME")
    monkeypatch.setattr("pathlib.Path.home", lambda: office.parent)
    assert credential_store(office) == "keychain"
    set_config(office, "credentials.store", "file")
    assert credential_store(office) == "file"
    monkeypatch.setattr("fo.config.sys.platform", "linux")
    set_config(office, "credentials.store", "keychain")
    assert credential_store(office) == "file"
    (office / "office.toml").write_text('[credentials]\nstore = "vault"\n')
    with pytest.raises(OfficeError, match="keychain or file"):
        credential_store(office)


def test_tests_never_reach_the_keychain_by_default(office, fake):
    from fo.auth import save_keys, save_secret_json

    save_keys(office, {"fred": {"api_key": "synthetic"}})
    save_secret_json(office, "exa", {"api_key": "synthetic"})
    assert read_secrets(office)["fred"]["api_key"] == "synthetic"
    assert provider_key(office, "exa") == "synthetic"
    assert checks(office)["credentials.store"]["status"] == "pass"
    assert fake.calls == 0 and fake.items == {}


def test_keychain_holds_secrets_and_leaves_no_file(office, fake):
    from fo import connect
    from fo.auth import save_keys, save_secret_json
    from fo.providers.plaid import load_items, save_items

    set_config(office, "credentials.store", "keychain")
    directory = credentials_dir(office)
    save_keys(office, {"plaid": {"client_id": "synthetic-id", "secret": "synthetic-secret"}})
    save_secret_json(office, "firecrawl", {"api_key": "synthetic-firecrawl"})
    save_items(office, ITEMS["items"])
    assert fake.names() == ["firecrawl.json", "keys.toml", "plaid-items.json"]
    assert not any(directory.glob("*"))
    assert read_secrets(office)["plaid"]["secret"] == "synthetic-secret"
    assert provider_key(office, "firecrawl") == "synthetic-firecrawl"
    assert load_items(office) == ITEMS["items"]
    assert credential_exists(office, "firecrawl.json")
    report = checks(office)
    assert report["credentials.store"]["status"] == "pass"
    assert "macOS Keychain" in report["credentials.store"]["reason"]
    assert "providers" not in report
    connect.remove(office, "firecrawl")
    assert fake.names() == ["keys.toml", "plaid-items.json"]
    assert provider_key(office, "firecrawl") is None


def test_files_move_to_the_keychain_once_read_back(office, fake):
    directory = ensure_credentials(office)
    files = {
        "keys.toml": KEYS,
        "exa.json": b'{"api_key": "synthetic-exa"}\n',
        "plaid-items.json": json.dumps(ITEMS).encode(),
        "devices.json": b'{"devices": []}\n',
    }
    for name, data in files.items():
        (directory / name).write_bytes(data)
        (directory / name).chmod(0o600)
    assert read_secrets(office)["fred"]["api_key"] == "synthetic-fred"
    set_config(office, "credentials.store", "keychain")
    assert sorted(p.name for p in directory.iterdir()) == ["devices.json"]
    for name in ("keys.toml", "exa.json", "plaid-items.json"):
        assert fake.items[(service(office), name)] == files[name]
    assert read_secrets(office)["fred"]["api_key"] == "synthetic-fred"
    assert provider_key(office, "exa") == "synthetic-exa"
    assert checks(office)["credentials.store"]["status"] == "pass"


def test_unmigrated_file_is_still_read(office, fake):
    directory = ensure_credentials(office)
    (office / "office.toml").write_text(
        (office / "office.toml").read_text() + '\n[credentials]\nstore = "keychain"\n'
    )
    (directory / "keys.toml").write_bytes(KEYS)
    assert read_secrets(office)["fred"]["api_key"] == "synthetic-fred"
    assert (directory / "keys.toml").exists() and fake.items == {}
    report = checks(office)["credentials.store"]
    assert report["status"] == "fail" and "keys.toml" in report["reason"]
    assert "synthetic" not in report["reason"]


@pytest.mark.parametrize("failure", ["write", "read-back"])
def test_failed_move_keeps_the_file(office, fake, monkeypatch, failure):
    directory = ensure_credentials(office)
    (directory / "keys.toml").write_bytes(KEYS)
    if failure == "write":
        fake.refuse.add("write")
    else:
        monkeypatch.setattr(
            keychain, "write", lambda *args: None
        )  # reports success, stores nothing
    set_config(office, "credentials.store", "keychain")
    assert (directory / "keys.toml").read_bytes() == KEYS
    assert fake.items == {}
    fake.refuse.clear()
    assert read_secrets(office)["fred"]["api_key"] == "synthetic-fred"
    assert checks(office)["credentials.store"]["status"] == "fail"


def test_differing_copies_stay_and_the_keychain_wins(office, fake):
    directory = ensure_credentials(office)
    set_config(office, "credentials.store", "keychain")
    fake.items[(service(office), "keys.toml")] = b'[fred]\n"api_key" = "from-keychain"\n'
    (directory / "keys.toml").write_bytes(KEYS)
    ensure_credentials(office)
    assert (directory / "keys.toml").read_bytes() == KEYS
    assert read_secrets(office)["fred"]["api_key"] == "from-keychain"
    assert checks(office)["credentials.store"]["status"] == "fail"


def test_refused_write_never_drops_the_only_copy(office, fake):
    from fo.auth import save_keys

    set_config(office, "credentials.store", "keychain")
    save_keys(office, {"fred": {"api_key": "first"}})
    fake.refuse.add("write")
    with pytest.raises(OfficeError) as caught:
        save_keys(office, {"fred": {"api_key": "second"}})
    assert caught.value.reason == "credentials_unavailable"
    assert "second" not in caught.value.message and "first" not in caught.value.message
    fake.refuse.clear()
    assert read_secrets(office)["fred"]["api_key"] == "first"


def test_refused_read_is_a_safe_error(office, fake):
    from fo.auth import save_keys

    set_config(office, "credentials.store", "keychain")
    save_keys(office, {"fred": {"api_key": "synthetic"}})
    fake.refuse.add("read")
    for call in (read_secrets, lambda root: provider_key(root, "fred")):
        with pytest.raises(OfficeError) as caught:
            call(office)
        assert caught.value.reason == "credentials_unavailable"
        assert "credentials.store file" in caught.value.message
        assert "synthetic" not in caught.value.message


def test_switching_to_files_moves_secrets_back(office, fake, monkeypatch):
    from fo.auth import save_keys, save_secret_json

    monkeypatch.delenv("FO_CREDENTIALS_HOME")
    monkeypatch.setattr("pathlib.Path.home", lambda: office.parent)
    save_keys(office, {"fred": {"api_key": "synthetic"}})
    save_secret_json(office, "exa", {"api_key": "synthetic-exa"})
    directory = credentials_dir(office)
    assert fake.names() == ["exa.json", "keys.toml"] and not any(directory.glob("*"))
    set_config(office, "credentials.store", "file")
    assert fake.items == {}
    assert sorted(p.name for p in directory.iterdir()) == ["exa.json", "keys.toml"]
    assert all(p.stat().st_mode & 0o777 == 0o600 for p in directory.iterdir())
    assert read_secrets(office)["fred"]["api_key"] == "synthetic"
    assert provider_key(office, "exa") == "synthetic-exa"
    assert checks(office)["credentials.store"]["status"] == "pass"


def test_choosing_files_after_the_keychain_moves_secrets_back(office, fake):
    from fo.auth import save_keys

    set_config(office, "credentials.store", "keychain")
    save_keys(office, {"fred": {"api_key": "synthetic"}})
    assert fake.names() == ["keys.toml"]
    set_config(office, "credentials.store", "file")
    assert fake.items == {}
    assert (credentials_dir(office) / "keys.toml").stat().st_mode & 0o777 == 0o600
    assert read_secrets(office)["fred"]["api_key"] == "synthetic"


def test_other_systems_keep_files(office, fake, monkeypatch):
    from fo.auth import save_keys

    set_config(office, "credentials.store", "keychain")
    monkeypatch.setattr("fo.config.sys.platform", "linux")
    calls = fake.calls
    save_keys(office, {"fred": {"api_key": "synthetic"}})
    assert (credentials_dir(office) / "keys.toml").exists()
    assert read_secrets(office)["fred"]["api_key"] == "synthetic"
    assert checks(office)["credentials.store"]["status"] == "pass"
    assert fake.calls == calls and fake.items == {}


def test_devices_stay_a_file(office, fake):
    from fo.serve.devices import Devices

    set_config(office, "credentials.store", "keychain")
    devices = Devices(lambda: office)
    devices.save([{"id": "dev_synthetic", "name": "Phone", "hash": "0" * 64}])
    assert (credentials_dir(office) / "devices.json").exists()
    assert fake.items == {}


@pytest.mark.skipif(
    sys.platform != "darwin" or os.environ.get("FO_KEYCHAIN_TEST") != "1",
    reason="touches the real login keychain; needs macOS and FO_KEYCHAIN_TEST=1",
)
def test_real_keychain_round_trip():
    name = "com.familyoffice.credentials.selftest-" + secrets.token_hex(6)
    label = "Family Office self-test (safe to delete)"
    blob = b'{"synthetic": true}\n' + bytes(range(256))
    try:
        assert keychain.read(name, "a.json") is None
        assert not keychain.exists(name, "a.json")
        keychain.write(name, "a.json", blob, label)
        assert keychain.exists(name, "a.json")
        assert keychain.read(name, "a.json") == blob
        keychain.write(name, "a.json", b"replaced", label)
        assert keychain.read(name, "a.json") == b"replaced"
        with pytest.raises(keychain.KeychainError):
            keychain.write(name, "a.json", b"", label)
        assert keychain.read(name, "a.json") == b"replaced"
    finally:
        keychain.delete(name, "a.json")
        keychain.delete(name, "a.json")
    assert not keychain.exists(name, "a.json")
