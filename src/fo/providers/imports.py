"""Explicit, repeatable CSV imports; original files remain in ignored imports/."""

import csv
import hashlib
import io
from datetime import date

from fo.errors import OfficeError
from fo.office import contained
from fo.providers.text import untrusted_text
from fo.store.authored import load
from fo.store.jsonl import read_rows


def amount(row, key):
    return row[key].replace(",", "").replace("$", "").strip()


def accounts(root, before=None):
    if before:
        date.fromisoformat(before)
    registry = load(root, "accounts")["accounts"]
    consumed = {
        digest
        for log in read_rows(root, "data/sync_log.jsonl")
        if log.get("status") == "complete"
        for digest in log.get("import_hashes", [])
    }
    result, hashes = {}, []
    for path in sorted(contained(root, "imports").glob("*.csv")):
        if path.is_symlink():
            raise OfficeError("unsafe_path", "Import symlinks are not accepted.")
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        if digest in consumed:
            continue
        reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
        fields = set(reader.fieldnames or [])
        monarch = {"Date", "Merchant", "Account", "Amount"} <= fields
        schwab = {"Symbol", "Quantity", "Price", "Market Value"} <= fields
        if not monarch and not schwab:
            raise OfficeError(
                "unsupported_import",
                "CSV must be a Monarch transaction or Schwab position export with its header row first.",
            )
        for row in reader:
            label = row.get("Account")
            matches = [
                a
                for a in registry
                if (label and label in (a["id"], a.get("provider_ref")))
                or (not label and a["provider"] == "csv")
            ]
            if len(matches) != 1:
                raise OfficeError(
                    "unmapped_account", "CSV account must match one explicit registry entry."
                )
            account = matches[0]
            if account["provider"] != "csv" and (not before or not monarch):
                raise OfficeError(
                    "provider_conflict",
                    "Live-owned accounts accept only historical transactions with --before DATE.",
                )
            if monarch and before and row["Date"] >= before:
                continue
            target = result.setdefault(
                account["id"],
                {
                    "account_id": account["id"],
                    "snapshot": not monarch,
                    "positions": [],
                    "balance": {},
                    "transactions": [],
                },
            )
            if target["snapshot"] == monarch:
                raise OfficeError(
                    "mixed_import", "Import position snapshots separately from transactions."
                )
            if monarch:
                date.fromisoformat(row["Date"])
                identity = hashlib.sha256(repr(sorted(row.items())).encode()).hexdigest()
                # Preserve two identical purchases within the same file using their ordinal.
                occurrence = sum(
                    t["provider_id"].startswith(identity) for t in target["transactions"]
                )
                target["transactions"].append(
                    {
                        "provider_id": f"{identity}:{occurrence}",
                        "transacted_at": row["Date"],
                        "posted_date": row["Date"],
                        "description": untrusted_text(row["Merchant"]),
                        "memo": untrusted_text(row.get("Original Statement")),
                        "amount": amount(row, "Amount"),
                        "pending": False,
                    }
                )
            elif row["Symbol"] and row["Symbol"] != "Account Total":
                target["positions"].append(
                    {
                        "symbol": row["Symbol"],
                        "qty": amount(row, "Quantity"),
                        "price": amount(row, "Price"),
                        "value": amount(row, "Market Value"),
                    }
                )
        hashes.append(digest)
    return list(result.values()), hashes
