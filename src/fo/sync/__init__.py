import hashlib
import json
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from fo.errors import OfficeError
from fo.lock import office_lock
from fo.store.index import project
from fo.store.jsonl import append, check_safe, identifier, now, read_rows
from fo.store.records import validate


def decimal_text(value):
    try:
        result = Decimal(str(value))
        if not result.is_finite():
            raise InvalidOperation()
        return str(result)
    except (ValueError, InvalidOperation) as exc:
        raise OfficeError(
            "invalid_amount", "A provider returned an invalid numeric amount."
        ) from exc


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def synchronize(root, provider=None, dry_run=False, full=False, commit=False, before=None):
    import platform

    from fo.config import read_config, read_secrets
    from fo.providers.schwab import Schwab
    from fo.providers.simplefin import SimpleFIN
    from fo.store.authored import load
    from fo.store.index import reindex

    config = read_config(root)
    if platform.node() != config.get("hosts", {}).get("writer"):
        raise OfficeError("not_writer", "Only the configured writer host may sync account data.")
    if provider and provider not in {"schwab", "simplefin", "csv"}:
        raise OfficeError("unknown_provider", "Use schwab, simplefin, or csv.")
    registry = load(root, "accounts")["accounts"]
    providers = (
        [provider]
        if provider
        else sorted(
            {a["provider"] for a in registry if a["provider"] in {"schwab", "simplefin", "csv"}}
        )
    )
    if not providers:
        raise OfficeError(
            "no_accounts", "Configure provider accounts in profile/accounts.json before sync."
        )
    results = []
    with office_lock(root):
        for name in providers:
            try:
                accounts = [a for a in registry if a["provider"] == name]
                if name == "csv":
                    from fo.providers.imports import accounts as import_accounts

                    response, hashes = import_accounts(root, before)
                    results.append(
                        ingest(
                            root, name, response, dry_run=dry_run, locked=True, import_hashes=hashes
                        )
                    )
                    continue
                if name == "schwab":
                    adapter = Schwab(root)
                else:
                    access = read_secrets(root).get("simplefin", {}).get("access_url")
                    if not access:
                        raise OfficeError("missing_credentials", "Run fo auth simplefin locally.")
                    adapter = SimpleFIN(access)
                response = adapter.accounts(accounts, full=full)
                results.append(ingest(root, name, response, dry_run=dry_run, locked=True))
            except (OfficeError, ValueError, TypeError, KeyError, OSError) as exc:
                failure = {
                    "run_id": identifier(),
                    "as_of": now(),
                    "provider": name,
                    "status": "failed",
                    "reason": exc.reason
                    if isinstance(exc, OfficeError)
                    else "invalid_provider_state",
                }
                if not dry_run:
                    append(root, "data/sync_log.jsonl", failure)
                results.append(failure)
        if not dry_run:
            reindex(root, locked=True)
            if commit:
                from fo.commits import commit_office

                commit_office(root, include_data=True)
    return results


def ingest(root, provider, accounts, dry_run=False, locked=False, import_hashes=None):
    if not locked:
        with office_lock(root):
            return ingest(root, provider, accounts, dry_run, True, import_hashes)
    state = project(root)
    from fo.config import read_config

    timezone = ZoneInfo(read_config(root).get("office", {}).get("timezone", "UTC"))

    def local_day(stamp):
        return datetime.fromisoformat(stamp.replace("Z", "+00:00")).astimezone(timezone).date()

    log = {
        "run_id": identifier(),
        "as_of": now(),
        "sequence": len(read_rows(root, "data/sync_log.jsonl")),
        "provider": provider,
        "status": "complete",
        "account_ids": [],
        "snapshot_account_ids": [],
        "unchanged_since": {},
        "content_hashes": {},
        "position_rows": 0,
        "transaction_rows": 0,
        "ambiguous_transactions": [],
        "pending_missing_counts": {},
        "import_hashes": import_hashes or [],
    }
    pending = []
    latest = state["providers"].get(provider, {})
    previous_tx = list(state["transactions"])
    discoveries = read_rows(root, "data/accounts.jsonl")
    for account in accounts:
        account_id = account["account_id"]
        if account_id in log["account_ids"]:
            raise OfficeError("duplicate_account", "Provider returned a duplicate account.")
        log["account_ids"].append(account_id)
        if account.get("snapshot", True):
            log["snapshot_account_ids"].append(account_id)
        timestamp = account.get("as_of", log["as_of"])
        base = {
            "account_id": account_id,
            "as_of": timestamp,
            "run_id": log["run_id"],
            "source": provider,
        }
        first_seen = next(
            (
                r["first_seen"]
                for r in discoveries
                if r["provider"] == provider and r["account_id"] == account_id
            ),
            log["as_of"],
        )
        pending.append(
            (
                "data/accounts.jsonl",
                {**base, "provider": provider, "first_seen": first_seen, "last_seen": log["as_of"]},
            )
        )
        positions = []
        for item in account.get("positions", []):
            position = {
                "symbol": item["symbol"],
                **{
                    key: decimal_text(item[key]) if item.get(key) is not None else None
                    for key in ("qty", "price", "value", "cost_basis")
                },
                "lot_id": item.get("lot_id"),
                "acquired_at": item.get("acquired_at"),
            }
            positions.append(position)
        balances = {
            k: decimal_text(v)
            for k, v in account.get("balance", {}).items()
            if k in ("net_value", "cash", "debt", "buying_power") and v is not None
        }
        digest = hashlib.sha256(
            canonical(
                [sorted(positions, key=lambda p: (p["symbol"], p.get("lot_id") or "")), balances]
            ).encode()
        ).hexdigest()
        log["content_hashes"][account_id] = digest
        if not account.get("snapshot", True):
            pass
        elif (
            latest.get("content_hashes", {}).get(account_id) == digest
            and account_id in state["snapshots"]
            and local_day(latest["as_of"]) == local_day(log["as_of"])
        ):
            log["unchanged_since"][account_id] = state["snapshots"][account_id]
        else:
            for row in positions:
                pending.append(("data/positions.jsonl", {**base, **row, "row_id": identifier()}))
                log["position_rows"] += 1
            pending.append(("data/balances.jsonl", {**base, **balances, "row_id": identifier()}))
        incoming_ids = {str(t["provider_id"]) for t in account.get("transactions", [])}
        seen_transactions = set()
        for incoming in account.get("transactions", []):
            row = {
                key: incoming.get(key)
                for key in (
                    "provider_id",
                    "transacted_at",
                    "posted_date",
                    "description",
                    "payee",
                    "memo",
                    "symbol",
                )
            }
            if not row["provider_id"]:
                raise OfficeError("invalid_transaction", "Transaction is missing its provider id.")
            row["amount"] = decimal_text(incoming["amount"])
            row["pending"] = bool(incoming.get("pending"))
            row["untrusted_fields"] = ["description", "payee", "memo"]
            candidates = [
                t
                for t in previous_tx
                if t["account_id"] == account_id and row["provider_id"] in t["provider_ids"]
            ]
            if not candidates:
                candidates = [
                    t
                    for t in previous_tx
                    if t["account_id"] == account_id
                    and Decimal(t["amount"]) == Decimal(row["amount"])
                    and t.get("transacted_at")
                    and row["transacted_at"]
                    and abs(
                        (
                            date.fromisoformat(t["transacted_at"])
                            - date.fromisoformat(row["transacted_at"])
                        ).days
                    )
                    <= 3
                    and (t.get("description") or "").strip().lower()
                    == (row["description"] or "").strip().lower()
                    and not set(t["provider_ids"]) & incoming_ids
                    and not row["pending"]
                ]
            if len(candidates) > 1:
                log["ambiguous_transactions"].append(
                    {
                        "account_id": account_id,
                        "candidate_ids": [t["transaction_id"] for t in candidates],
                    }
                )
            prior = candidates[0] if len(candidates) == 1 else None
            if prior and all(prior.get(k) == v for k, v in row.items()):
                seen_transactions.add(prior["transaction_id"])
                continue
            row.update(base)
            row.update(
                transaction_id=prior["transaction_id"] if prior else identifier(),
                revision=prior["revision"] + 1 if prior else 1,
                provider_ids=sorted(
                    set((prior["provider_ids"] if prior else []) + [row["provider_id"]])
                ),
                row_id=identifier(),
            )
            pending.append(("data/transactions.jsonl", row))
            if prior:
                previous_tx.remove(prior)
            previous_tx.append(row)
            seen_transactions.add(row["transaction_id"])
            log["transaction_rows"] += 1
        window = account.get("transaction_window")
        if window:
            for prior in list(previous_tx):
                tx_id = prior["transaction_id"]
                if (
                    prior["account_id"] != account_id
                    or not prior.get("pending")
                    or tx_id in seen_transactions
                ):
                    continue
                if (
                    not prior.get("transacted_at")
                    or not window["start"] <= prior["transacted_at"] <= window["end"]
                ):
                    continue
                count = latest.get("pending_missing_counts", {}).get(tx_id, 0) + 1
                log["pending_missing_counts"][tx_id] = count
                if count >= 3:
                    expired = {
                        **prior,
                        **base,
                        "row_id": identifier(),
                        "revision": prior["revision"] + 1,
                        "pending": False,
                        "status": "expired",
                    }
                    pending.append(("data/transactions.jsonl", expired))
                    previous_tx.remove(prior)
                    previous_tx.append(expired)
                    log["transaction_rows"] += 1
    for table, row in [*pending, ("data/sync_log.jsonl", log)]:
        check_safe(row)
        validate(table, row)
    if not dry_run:
        for table, row in pending:
            append(root, table, row)
        append(root, "data/sync_log.jsonl", log)
    return {**log, "dry_run": dry_run}
