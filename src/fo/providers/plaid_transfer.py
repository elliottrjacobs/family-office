"""Move linked Plaid Items to another machine without linking them again.

Linking an institution again creates a new Plaid Item, which uses one of the Trial's
Items for good and gives every account a new id. An Item's access token works from any
machine that holds the same client ID and secret, so moving the token is enough.

`fo auth plaid --export PATH` seals the chosen Items with a one-time passphrase (see
fo.sealed) into a new 0600 file outside the office. `fo auth plaid --import PATH` on the
other machine opens it, checks that it belongs to this office and to this machine's Plaid
client and environment, merges the Items into this machine's plaid-items credential,
reads the result back, and only then deletes the file. The exporting machine keeps its
Items. The file never holds the Plaid secret, and no token is printed.

Import makes no Plaid call and changes no account registry entry: the registry maps
Plaid account ids (provider_ref), which an Item keeps wherever its token lives. The one
exception is a machine with no Plaid keys yet, which asks for them and saves them only
after Plaid accepts them for a transferred Item.
"""

import hashlib
import json
import os
import stat
from pathlib import Path

from fo.config import read_config, read_secrets
from fo.errors import OfficeError
from fo.providers.plaid import PlaidAPI, PlaidError, clean_credential, load_items, save_items
from fo.providers.text import untrusted_text
from fo.sealed import MAX_SEALED, check_passphrase, seal, unseal

CONTEXT = "plaid-items"
PAYLOAD_VERSION = 1
PASSPHRASE = "Passphrase for the transfer file"
# Folders under ~/Library that macOS syncs to iCloud Drive or a File Provider cloud service.
SYNCED = {"Mobile Documents", "CloudStorage"}
MISMATCH = (
    "The transfer file's Items belong to a different Plaid client ID than this Mac's keys. "
    "Use the keys the Items were linked with; nothing was imported."
)


def fingerprint(client_id):
    """A stand-in for the client ID that the transfer file carries instead of the ID."""
    return hashlib.sha256(b"family-office plaid client\0" + client_id.encode()).hexdigest()


def office_id(root):
    value = read_config(root).get("office", {}).get("id")
    if not isinstance(value, str) or not value:
        raise OfficeError(
            "credentials_not_migrated",
            "Run fo doctor --fix (or a credential-writing command) once to migrate credentials.",
        )
    return value


def name_of(item):
    return untrusted_text(str(item.get("institution") or "A linked institution"))


def summary(item, status=None):
    result = {"institution": name_of(item), "item_id": item["item_id"]}
    if status:
        result["status"] = status
    return result


def select(items, wanted):
    """Every Item, or those whose item_id or institution name matches a --item value."""
    if not wanted:
        return list(items)
    chosen, unmatched = [], []
    for value in wanted:
        text = str(value).strip()
        matches = [
            item
            for item in items
            if item["item_id"] == text
            or str(item.get("institution") or "").strip().casefold() == text.casefold()
        ]
        if not matches:
            unmatched.append(text)
        chosen.extend(item for item in matches if item not in chosen)
    if unmatched:
        names = sorted({name_of(item) for item in items})
        raise OfficeError(
            "unknown_item",
            "No linked Plaid Item has that institution name or item id. Linked here: "
            + ", ".join(names)
            + ".",
        )
    return chosen


def destination(root, path):
    """A new file path outside the office, which syncs and is tracked by Git."""
    target = Path(path).expanduser().absolute()
    try:
        folder = target.parent.resolve(strict=True)
    except OSError as exc:
        raise OfficeError("invalid_path", "The transfer file's folder does not exist.") from exc
    if folder.is_relative_to(root.resolve()):
        raise OfficeError(
            "unsafe_path",
            "Write the transfer file outside the office folder, which syncs and is tracked by "
            "Git; for example in ~/Downloads.",
        )
    if target.exists() or target.is_symlink():
        raise OfficeError("file_exists", "A file already exists there; choose a new name.")
    return folder / target.name


def write_new(path, data):
    """Create path at 0600, refusing one that exists; a failed write leaves no file."""
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    except FileExistsError as exc:
        raise OfficeError("file_exists", "A file already exists there; choose a new name.") from exc
    except OSError as exc:
        raise OfficeError("transfer_failed", "The transfer file could not be written.") from exc
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    except OSError as exc:
        path.unlink(missing_ok=True)
        raise OfficeError("transfer_failed", "The transfer file could not be written.") from exc


def export_items(root, path, prompt, wanted=None):
    """fo auth plaid --export: seal this machine's chosen Items into a new file."""
    settings = read_secrets(root).get("plaid") or {}
    if not settings.get("client_id"):
        raise OfficeError(
            "missing_credentials",
            "This Mac has no Plaid keys. Export from the Mac that linked the institutions.",
        )
    items = load_items(root)
    if not items:
        raise OfficeError("missing_credentials", "No Plaid institutions are linked on this Mac.")
    chosen = select(items, wanted)
    target = destination(root, path)
    passphrase = prompt(PASSPHRASE, hide_input=True, confirmation_prompt=True)
    check_passphrase(passphrase)
    payload = {
        "version": PAYLOAD_VERSION,
        "office": office_id(root),
        "environment": settings.get("environment") or "sandbox",
        "client": fingerprint(str(settings["client_id"])),
        "items": chosen,
    }
    write_new(target, seal(json.dumps(payload).encode(), passphrase, CONTEXT))
    note = (
        "Move the file to the other Mac and run `fo auth plaid --import` with it there; "
        "the import deletes it. Then delete this copy. This Mac keeps its Items."
    )
    if SYNCED.intersection(target.parts):
        note += (
            " This folder syncs to a cloud service, which may keep a copy after you delete it "
            "(iCloud Drive's Recently Deleted keeps files for 30 days); remove it there too."
        )
    return {
        "provider": "plaid",
        "exported": len(chosen),
        "items": [summary(item) for item in chosen],
        "note": note,
    }


def _text(value, limit=256):
    return (
        isinstance(value, str)
        and 0 < len(value) <= limit
        and value.isprintable()
        and not any(c.isspace() for c in value)
    )


def parse(plaintext):
    """The payload of an opened transfer file, with every Item's shape checked."""
    try:
        payload = json.loads(plaintext)
        items = payload["items"]
        valid = (
            payload["version"] == PAYLOAD_VERSION
            and isinstance(payload["office"], str)
            and payload["environment"] in {"sandbox", "production"}
            and _text(payload["client"])
            and isinstance(items, list)
            and items
            and all(
                isinstance(item, dict)
                and _text(item.get("item_id"))
                and _text(item.get("access_token"))
                and (item.get("institution_id") is None or _text(item["institution_id"]))
                and (item.get("cursor") is None or isinstance(item["cursor"], str))
                for item in items
            )
        )
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        raise OfficeError(
            "invalid_transfer", "The transfer file's contents are malformed."
        ) from exc
    if not valid:
        raise OfficeError("invalid_transfer", "The transfer file's contents are malformed.")
    return payload


def read_transfer(path):
    source = Path(path).expanduser().absolute()
    try:
        info = os.lstat(source)
        if not stat.S_ISREG(info.st_mode):
            raise OfficeError(
                "invalid_path", "Give the transfer file itself, not a link or a folder."
            )
        if info.st_size > MAX_SEALED:
            raise OfficeError("invalid_transfer", "That is not a family-office transfer file.")
        return source, source.read_bytes()
    except FileNotFoundError as exc:
        raise OfficeError("invalid_path", "No transfer file is at that path.") from exc
    except OSError as exc:
        raise OfficeError("invalid_path", "The transfer file could not be read.") from exc


def adopt_keys(root, keys, payload, prompt, first):
    """Ask a keyless machine for the Plaid keys; save them once Plaid accepts them."""
    from fo.auth import save_keys

    client_id = clean_credential(prompt("Plaid client ID", hide_input=True), "client ID")
    secret = clean_credential(prompt("Plaid secret", hide_input=True), "secret")
    if fingerprint(client_id) != payload["client"]:
        raise OfficeError(
            "plaid_client_mismatch",
            "That client ID is not the one the transfer file's Items were linked with; "
            "nothing was saved.",
        )
    api = PlaidAPI(client_id, secret, payload["environment"])
    try:
        api.post("/item/get", {"access_token": first["access_token"]})
    except PlaidError as exc:
        # An Item that needs its login repaired still proves the keys; fo auth plaid fixes it.
        if not exc.per_item:
            raise
    keys["plaid"] = {
        "client_id": client_id,
        "secret": secret,
        "environment": payload["environment"],
    }
    save_keys(root, keys)


def import_items(root, path, prompt, confirm):
    """fo auth plaid --import: merge a transfer file's Items into this machine's store."""
    source, data = read_transfer(path)
    payload = parse(unseal(data, prompt(PASSPHRASE, hide_input=True), CONTEXT))
    if payload["office"] != office_id(root):
        raise OfficeError(
            "office_mismatch",
            "The transfer file comes from a different office. Import it into the office it "
            "was exported from (check --office); nothing was imported.",
        )
    keys = read_secrets(root)
    settings = keys.get("plaid") or {}
    keyless = not (settings.get("client_id") and settings.get("secret"))
    if not keyless:
        environment = settings.get("environment") or "sandbox"
        if environment != payload["environment"]:
            raise OfficeError(
                "plaid_client_mismatch",
                f"The transfer file's Items are from Plaid's {payload['environment']} "
                f"environment and this Mac's keys are for {environment}; nothing was imported.",
            )
        if fingerprint(str(settings["client_id"])) != payload["client"]:
            raise OfficeError("plaid_client_mismatch", MISMATCH)
    existing = load_items(root)
    linked = {item["item_id"] for item in existing}
    institutions = {item.get("institution_id") for item in existing} - {None, ""}
    added, report = [], []
    for item in payload["items"]:
        if item["item_id"] in linked:
            # This Mac's own copy of the Item wins; its token and cursor stay as they are.
            report.append(summary(item, "already_linked"))
            continue
        if item.get("institution_id") in institutions and not confirm(
            f"{name_of(item)} is already linked on this Mac under another Plaid Item, "
            "perhaps linked again here. Importing both can count its accounts twice. "
            "Import this one too?",
            default=False,
        ):
            report.append(summary(item, "skipped_same_institution"))
            continue
        added.append(item)
        linked.add(item["item_id"])
        report.append(summary(item, "imported"))
    if added:
        if keyless:
            adopt_keys(root, keys, payload, prompt, added[0])
        save_items(root, existing + added)
    after = {item["item_id"]: item for item in load_items(root)}
    if any(after.get(item["item_id"]) != item for item in existing + added):
        raise OfficeError(
            "credentials_unavailable",
            "The merged Plaid Items did not read back as written. The transfer file was "
            "kept; run the import again.",
        )
    try:
        source.unlink()
        removed = True
    except OSError:
        removed = False
    counts = {status: 0 for status in ("imported", "already_linked", "skipped_same_institution")}
    for entry in report:
        counts[entry["status"]] += 1
    cleanup = (
        "Delete the transfer file on the other Mac too."
        if removed
        else "The transfer file could not be deleted: delete it now, and the copy on the other Mac."
    )
    return {
        "provider": "plaid",
        **counts,
        "keys_saved": bool(added) and keyless,
        "items": report,
        "file_removed": removed,
        "note": "The next fo sync updates their accounts under their existing ids. " + cleanup,
    }
