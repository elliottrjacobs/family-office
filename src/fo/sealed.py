"""Passphrase-sealed files, for carrying a secret from one machine to another.

A sealed file is JSON: a versioned header and a base64 ciphertext with its tag. scrypt
turns the passphrase and a random salt into an encryption key and a MAC key. The
plaintext is XORed with HMAC-SHA256 in counter mode, and HMAC-SHA256 authenticates the
header and the ciphertext together (encrypt-then-MAC). A wrong passphrase, a sealed file
of another kind, or any change to the file fails the tag check before anything is
decrypted.

Only standard-library primitives are used, so sealing adds no dependency. Every file has
its own salt and so its own keys, which is why the counter needs no separate nonce.
"""

import base64
import binascii
import hashlib
import hmac
import json
import secrets
import struct
import unicodedata

from fo.errors import OfficeError

FORMAT = "family-office.sealed"
VERSION = 1
# About 0.2 s and 128 MiB on an Apple Silicon Mac, once per export and once per import.
SCRYPT_N = 2**17
SCRYPT_R = 8
SCRYPT_P = 1
# Bounds for a file's own parameters, so a damaged or hostile header cannot ask for more
# than about a gigabyte of memory.
MAX_N = 2**20
MAX_R = 8
MAX_P = 4
SALT_BYTES = 16
MIN_PASSPHRASE = 12
MAX_SEALED = 4 << 20
NOT_SEALED = "That is not a family-office transfer file, or it is damaged."
REJECTED = "The passphrase is wrong, or the transfer file was changed after it was written."


def check_passphrase(passphrase):
    if not isinstance(passphrase, str) or len(passphrase.strip()) < MIN_PASSPHRASE:
        raise OfficeError(
            "weak_passphrase",
            f"Use a passphrase of at least {MIN_PASSPHRASE} characters, such as four or more "
            "random words you have not used anywhere else.",
        )


def _keys(passphrase, salt, n, r, p):
    material = hashlib.scrypt(
        unicodedata.normalize("NFC", passphrase).encode(),
        salt=salt,
        n=n,
        r=r,
        p=p,
        maxmem=128 * r * (n + p + 2) + (1 << 20),
        dklen=64,
    )
    return material[:32], material[32:]


def _xor(data, key):
    """data XOR the HMAC-SHA256 counter-mode keystream for key."""
    if not data:
        return b""
    blocks = -(-len(data) // 32)
    stream = b"".join(
        hmac.digest(key, counter.to_bytes(8, "big"), "sha256") for counter in range(blocks)
    )[: len(data)]
    return (int.from_bytes(data, "big") ^ int.from_bytes(stream, "big")).to_bytes(len(data), "big")


def _authenticated(context, n, r, p, salt, ciphertext):
    """The bytes the tag covers: format, version, context, scrypt parameters, salt, data."""
    header = f"{FORMAT}\0{VERSION}\0{context}\0".encode()
    return header + struct.pack(">III", n, r, p) + salt + ciphertext


def _b64(data):
    return base64.b64encode(data).decode("ascii")


def seal(plaintext: bytes, passphrase: str, context: str) -> bytes:
    """The sealed file's bytes for plaintext; context names what kind of secret it holds."""
    check_passphrase(passphrase)
    n, r, p = SCRYPT_N, SCRYPT_R, SCRYPT_P
    salt = secrets.token_bytes(SALT_BYTES)
    encryption, authentication = _keys(passphrase, salt, n, r, p)
    ciphertext = _xor(plaintext, encryption)
    tag = hmac.digest(authentication, _authenticated(context, n, r, p, salt, ciphertext), "sha256")
    document = {
        "format": FORMAT,
        "version": VERSION,
        "context": context,
        "kdf": {"name": "scrypt", "n": n, "r": r, "p": p, "salt": _b64(salt)},
        "cipher": "hmac-sha256-ctr",
        "mac": "hmac-sha256",
        "ciphertext": _b64(ciphertext),
        "tag": _b64(tag),
    }
    return (json.dumps(document, indent=2) + "\n").encode()


def _bounded(value, maximum):
    return isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= maximum


def unseal(data: bytes, passphrase: str, context: str) -> bytes:
    """The plaintext of a sealed file of this context, or a safe OfficeError."""
    try:
        if len(data) > MAX_SEALED:
            raise ValueError("too large")
        document = json.loads(data)
        kdf = document["kdf"]
        n, r, p = kdf["n"], kdf["r"], kdf["p"]
        salt = base64.b64decode(kdf["salt"], validate=True)
        ciphertext = base64.b64decode(document["ciphertext"], validate=True)
        tag = base64.b64decode(document["tag"], validate=True)
        valid = (
            document["format"] == FORMAT
            and document["version"] == VERSION
            and document["context"] == context
            and kdf["name"] == "scrypt"
            and document["cipher"] == "hmac-sha256-ctr"
            and document["mac"] == "hmac-sha256"
            and _bounded(n, MAX_N)
            and n > 1
            and n & (n - 1) == 0
            and _bounded(r, MAX_R)
            and _bounded(p, MAX_P)
            and len(salt) == SALT_BYTES
            and len(tag) == 32
        )
    except (ValueError, TypeError, KeyError, binascii.Error) as exc:
        raise OfficeError("invalid_transfer", NOT_SEALED) from exc
    if not valid:
        raise OfficeError("invalid_transfer", NOT_SEALED)
    if not isinstance(passphrase, str):
        raise OfficeError("transfer_rejected", REJECTED)
    encryption, authentication = _keys(passphrase, salt, n, r, p)
    expected = hmac.digest(
        authentication, _authenticated(context, n, r, p, salt, ciphertext), "sha256"
    )
    if not hmac.compare_digest(expected, tag):
        raise OfficeError("transfer_rejected", REJECTED)
    return _xor(ciphertext, encryption)
