"""Passphrase-sealed transfer files, with synthetic secrets only."""

import base64
import json

import pytest

from fo import sealed
from fo.errors import OfficeError

PASSPHRASE = "correct horse battery staple"
SECRET = b'{"token": "access-sandbox-SEALED_SENTINEL"}'


@pytest.fixture(autouse=True)
def quick_scrypt(monkeypatch):
    monkeypatch.setattr(sealed, "SCRYPT_N", 2**10)


def edited(data, change):
    document = json.loads(data)
    change(document)
    return json.dumps(document).encode()


def flip(text):
    raw = bytearray(base64.b64decode(text))
    raw[len(raw) // 2] ^= 1
    return base64.b64encode(bytes(raw)).decode()


def test_round_trip_hides_the_plaintext_and_salts_every_file():
    first = sealed.seal(SECRET, PASSPHRASE, "plaid-items")
    second = sealed.seal(SECRET, PASSPHRASE, "plaid-items")
    assert b"SEALED_SENTINEL" not in first and b"access-sandbox" not in first
    assert first != second
    assert json.loads(first)["ciphertext"] != json.loads(second)["ciphertext"]
    assert sealed.unseal(first, PASSPHRASE, "plaid-items") == SECRET
    assert sealed.unseal(second, PASSPHRASE, "plaid-items") == SECRET
    for edge in (b"", b"\x00\x00\x01", bytes(range(256)) * 3):
        assert sealed.unseal(sealed.seal(edge, PASSPHRASE, "x"), PASSPHRASE, "x") == edge


def test_default_cost_parameters_work(monkeypatch):
    monkeypatch.setattr(sealed, "SCRYPT_N", 2**17)
    data = sealed.seal(SECRET, PASSPHRASE, "plaid-items")
    assert json.loads(data)["kdf"]["n"] == 2**17
    assert sealed.unseal(data, PASSPHRASE, "plaid-items") == SECRET


def test_unicode_passphrases_match_across_normalization():
    composed, decomposed = "café au lait, please", "café au lait, please"
    data = sealed.seal(SECRET, composed, "plaid-items")
    assert sealed.unseal(data, decomposed, "plaid-items") == SECRET


@pytest.mark.parametrize("passphrase", ["", "short", "           ", None])
def test_weak_passphrases_are_refused(passphrase):
    with pytest.raises(OfficeError) as caught:
        sealed.seal(SECRET, passphrase, "plaid-items")
    assert caught.value.reason == "weak_passphrase"


def test_wrong_passphrase_and_changed_files_fail_the_tag():
    data = sealed.seal(SECRET, PASSPHRASE, "plaid-items")
    changes = [
        lambda d: d.update(ciphertext=flip(d["ciphertext"])),
        lambda d: d.update(tag=flip(d["tag"])),
        lambda d: d["kdf"].update(salt=flip(d["kdf"]["salt"])),
        lambda d: d["kdf"].update(n=2**11),
        lambda d: d["kdf"].update(r=4),
    ]
    for change in changes:
        with pytest.raises(OfficeError) as caught:
            sealed.unseal(edited(data, change), PASSPHRASE, "plaid-items")
        assert caught.value.reason == "transfer_rejected"
    with pytest.raises(OfficeError) as caught:
        sealed.unseal(data, PASSPHRASE + "!", "plaid-items")
    assert caught.value.reason == "transfer_rejected"
    assert "SEALED_SENTINEL" not in caught.value.message


def test_other_kinds_and_damaged_headers_are_not_transfer_files():
    data = sealed.seal(SECRET, PASSPHRASE, "plaid-items")
    damaged = [
        b"not json",
        b"[]",
        edited(data, lambda d: d.update(context="keys")),
        edited(data, lambda d: d.update(version=2)),
        edited(data, lambda d: d.update(format="other")),
        edited(data, lambda d: d["kdf"].update(n=2**21)),
        edited(data, lambda d: d["kdf"].update(n=3000)),
        edited(data, lambda d: d["kdf"].update(r=True)),
        edited(data, lambda d: d["kdf"].update(p=9)),
        edited(data, lambda d: d.update(tag="!!")),
        edited(data, lambda d: d.pop("ciphertext")),
        b" " * (sealed.MAX_SEALED + 1),
    ]
    for case in damaged:
        with pytest.raises(OfficeError) as caught:
            sealed.unseal(case, PASSPHRASE, "plaid-items")
        assert caught.value.reason == "invalid_transfer"
