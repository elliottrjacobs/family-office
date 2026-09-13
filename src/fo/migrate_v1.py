"""Read-only legacy import planning followed by an explicit append-only apply."""

import hashlib
import json
import re
from datetime import UTC, date, datetime
from decimal import Decimal
from importlib.resources import files
from pathlib import Path

import jsonschema
import yaml

from fo.errors import OfficeError
from fo.lock import office_lock
from fo.office import atomic_write, contained, write_json
from fo.providers.text import untrusted_text
from fo.reports import CLOSING, component
from fo.store.jsonl import append, check_safe, identifier, now, read_rows
from fo.store.records import validate
from fo.sync import ingest


def read(source, relative, default=None):
    path = contained(source, relative)
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise OfficeError(
            "invalid_legacy_file", "A legacy JSON file is malformed: " + relative
        ) from exc


def clean(value):
    if isinstance(value, dict):
        return {
            k: clean(v)
            for k, v in value.items()
            if not re.search(
                r"token|secret|api.?key|account.?number|hash.?value|access.?url", k, re.I
            )
        }
    if isinstance(value, list):
        return [clean(v) for v in value]
    return untrusted_text(value) if isinstance(value, str) else value


def decision_event(entry, key):
    return {
        **entry,
        "id": key,
        "event": "created",
        "as_of": now(),
        "when": [],
        "source": "v1-migration",
        "report": None,
        "price_at": None,
        "context_level": "none",
    }


def plan(source):
    if not contained(source, "profile").is_dir():
        raise OfficeError(
            "missing_legacy_profile", "Source must contain a legacy profile directory."
        )
    holdings = read(source, "profile/portfolio/holdings.json", {})
    stamp = holdings.get("data_as_of")
    if holdings and not stamp:
        raise OfficeError(
            "missing_legacy_date",
            "Legacy holdings require data_as_of; acquisition dates cannot be inferred.",
        )
    if stamp:
        parsed = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise OfficeError(
                "missing_legacy_timezone", "Legacy data_as_of needs an explicit timezone."
            )
        stamp = parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")
    registry, snapshots, aliases, issues = [], {}, {}, []
    for slot, account in holdings.get("accounts", {}).items():
        component(slot)
        registry.append(
            {
                "id": slot,
                "provider": "schwab",
                "last4": str(account.get("account_number_last4", "")),
                "type": account.get("account_type", "brokerage"),
            }
        )
        aliases[slot] = slot
        positions, cash = [], Decimal(str(account.get("cash_balance", 0)))
        for p in account.get("holdings", []):
            if p.get("type") == "cash":
                continue
            if p.get("type") == "money_market":
                cash += Decimal(str(p["market_value"]))
                continue
            positions.append(
                {
                    "symbol": p["symbol"],
                    "qty": p.get("shares"),
                    "price": p.get("price"),
                    "value": p.get("market_value"),
                    "cost_basis": p.get("cost_basis_total"),
                    "lot_id": p.get("lot_id"),
                    "acquired_at": p.get("acquired_at"),
                }
            )
        snapshots[slot] = {
            "account_id": slot,
            "as_of": stamp,
            "positions": positions,
            "balance": {"net_value": account.get("market_value"), "cash": str(cash)},
            "transactions": [],
        }
    if holdings.get("total_portfolio_value") is not None:
        values = [a["balance"]["net_value"] for a in snapshots.values()]
        if any(v is None for v in values) or sum(
            (Decimal(str(v)) for v in values), Decimal(0)
        ) != Decimal(str(holdings["total_portfolio_value"])):
            issues.append("Brokerage account values do not reconcile to total_portfolio_value.")
    for folder in ("accounts", "debts"):
        for path in sorted(contained(source, f"profile/{folder}").glob("*.json")):
            relative = path.relative_to(source).as_posix()
            value = read(source, relative)
            if isinstance(value, dict) and "accounts" in value:
                value = value["accounts"]
            if isinstance(value, dict) and "debts" in value:
                value = value["debts"]
            if isinstance(value, dict) and any(
                k in value for k in ("balance", "current_balance", "market_value")
            ):
                value = [value]
            elif isinstance(value, dict):
                value = [{"id": key, **v} for key, v in value.items() if isinstance(v, dict)]
            if not isinstance(value, list) or not value:
                issues.append(f"Unrecognized account layout: {relative}")
                continue
            for account in value:
                old_id = str(account.get("id", account.get("account_id", path.stem)))
                last4 = str(account.get("last4", account.get("account_number_last4", "")))
                matches = [
                    a for a in registry if a["id"] == old_id or last4 and a["last4"] == last4
                ]
                balance = account.get(
                    "balance", account.get("current_balance", account.get("market_value"))
                )
                if balance is None or len(matches) > 1:
                    issues.append(f"Ambiguous account or missing balance: {relative}")
                    continue
                if matches:
                    found = matches[0]["id"]
                    aliases[old_id] = found
                    if Decimal(str(balance)) != Decimal(
                        str(snapshots[found]["balance"]["net_value"])
                    ):
                        issues.append(f"Conflicting balance copies: {relative}")
                    continue
                component(old_id)
                provider_ref = account.get("simplefin_id", account.get("provider_ref"))
                entry = {
                    "id": old_id,
                    "provider": "simplefin" if provider_ref else "csv",
                    "last4": last4,
                    "type": "debt" if folder == "debts" else account.get("type", "unknown"),
                }
                if provider_ref:
                    entry["provider_ref"] = str(provider_ref)
                    aliases[str(provider_ref)] = old_id
                registry.append(entry)
                aliases[old_id] = old_id
                timestamp = account.get("as_of", account.get("data_as_of", stamp))
                if not timestamp:
                    issues.append(f"Missing balance observation date: {relative}")
                    continue
                signed = -abs(Decimal(str(balance))) if folder == "debts" else Decimal(str(balance))
                snapshots[old_id] = {
                    "account_id": old_id,
                    "as_of": timestamp,
                    "positions": [],
                    "balance": {"net_value": str(signed)},
                    "transactions": [],
                }
    for path in sorted(contained(source, "profile/transactions").rglob("*.json")):
        value = read(source, path.relative_to(source).as_posix())
        transactions = value.get("transactions", []) if isinstance(value, dict) else value
        for tx in transactions:
            old_id = str(
                tx.get("account_id", value.get("account_id", "") if isinstance(value, dict) else "")
            )
            account_id = aliases.get(old_id)
            if account_id not in snapshots or not tx.get("id", tx.get("provider_id")):
                issues.append("A transaction lacks an unambiguous account or provider ID.")
                continue
            snapshots[account_id]["transactions"].append(
                {
                    "provider_id": str(tx.get("id", tx.get("provider_id"))),
                    "amount": tx["amount"],
                    "transacted_at": tx.get("transacted_at", tx.get("date")),
                    "posted_date": tx.get("posted_date", tx.get("date")),
                    "description": untrusted_text(tx.get("description", "")),
                    "payee": untrusted_text(tx.get("payee")),
                    "memo": untrusted_text(tx.get("memo")),
                    "pending": bool(tx.get("pending")),
                }
            )
    family = clean(read(source, "profile/family.json", {}))
    household = {
        "members": family.get("members", family.get("family_members", [])),
        "businesses": family.get("businesses", []),
    }
    if family and not household["members"]:
        issues.append("Legacy household member layout needs a mapping.")
    ips = clean(read(source, "profile/investment-policy.json", {}))
    risk = clean(read(source, "profile/risk-tolerance.json", {}))
    policy = {
        "bands": ips.get("bands", risk.get("bands", [])),
        "prohibitions": list(
            dict.fromkeys(ips.get("prohibitions", []) + risk.get("prohibitions", []))
        ),
        "classifications": ips.get("classifications", {}),
    }
    for name, original in (("investment-policy", ips), ("risk-tolerance", risk)):
        if set(original) - {
            "bands",
            "prohibitions",
            "classifications",
            "as_of",
            "updated_at",
            "notes",
            "description",
        }:
            issues.append(
                f"Legacy {name} contains unmapped policy fields; reconcile them before import."
            )
    notes = {"family": family, "investment-policy": ips}
    for name in ("risk-tolerance", "tax", "income", "business"):
        single = read(source, f"profile/{name}.json")
        if single is not None:
            notes[name] = clean(single)
        for path in sorted(contained(source, f"profile/{name}").rglob("*.json")):
            relative = path.relative_to(source).as_posix()
            # Never open credentials, even in an unexpected legacy subdirectory.
            if re.search(r"secret|token|api.?key|credential", relative, re.I):
                continue
            notes[relative] = clean(read(source, relative))
    goals = clean(read(source, "profile/goals.json", {"goals": []}))
    report_files = []
    for folder in ("reports", "briefings"):
        for path in sorted(contained(source, folder).rglob("*.md")):
            contained(source, path.relative_to(source).as_posix())
            match = re.search(r"\d{4}-\d{2}-\d{2}", path.name)
            if not match:
                issues.append("Report missing a date: " + path.relative_to(source).as_posix())
                continue
            kind = (
                path.relative_to(source).parts[1]
                if len(path.relative_to(source).parts) > 2
                else folder
            )
            report_files.append(
                {
                    "source": path.relative_to(source).as_posix(),
                    "path": f"reports/{component(kind)}/household/{match[0]}-{component(path.stem)}.md",
                    "date": match[0],
                    "kind": kind,
                    "body": untrusted_text(path.read_text()),
                }
            )
    entries = []
    for path in sorted(contained(source, "journal/entries").glob("*.md")):
        text = contained(source, path.relative_to(source).as_posix()).read_text()

        def field(name, text=text):
            match = re.search(rf"(?:\*\*)?{name}:\s*(?:\*\*)?([^\n]+)", text, re.I)
            return match[1].strip().strip("*") if match else None

        subject, action, thesis, invalidate, conviction = (
            field(n) for n in ("Subject", "Action", "Thesis", "Invalidation", "Conviction")
        )
        status = re.findall(r"Status:\s*(?:\*\*)?(OPEN|CLOSED)", text, re.I)
        day = re.search(r"\d{4}-\d{2}-\d{2}", path.name)
        if not all((subject, action, thesis, invalidate, conviction, day)) or len(status) > 1:
            issues.append("Journal entry needs explicit mapping: " + path.name)
            continue
        entries.append(
            {
                "subject": subject,
                "action": action,
                "thesis": clean(thesis),
                "invalidate": clean(invalidate),
                "conviction": conviction.upper(),
                "date": day[0],
                "closed": bool(status and status[-1].upper() == "CLOSED"),
                "migrated_from": path.relative_to(source).as_posix(),
            }
        )
    corrections = []
    for path in sorted(contained(source, "memory").glob("feedback_*.md")):
        corrections.extend(
            untrusted_text(line[2:])
            for line in contained(source, path.relative_to(source).as_posix())
            .read_text()
            .splitlines()
            if line.startswith("- ")
        )
    data = {
        "registry": registry,
        "snapshots": list(snapshots.values()),
        "household": household,
        "ips": policy,
        "goals": goals,
        "reports": report_files,
        "decisions": entries,
        "corrections": corrections,
        "notes": notes,
        "issues": issues,
    }
    for name, value in {
        "accounts": {"accounts": registry},
        "household": household,
        "ips": policy,
        "goals": goals,
    }.items():
        schema = json.loads(files("fo").joinpath(f"store/schemas/{name}.schema.json").read_text())
        if not jsonschema.Draft202012Validator(
            schema, format_checker=jsonschema.FormatChecker()
        ).is_valid(value):
            issues.append(f"Legacy {name} needs an explicit mapping to the new profile schema.")
    if len({a["id"] for a in registry}) != len(registry):
        issues.append("Duplicate account identities require a mapping.")
    if len({r["path"] for r in report_files}) != len(report_files):
        issues.append("Legacy report destinations collide; choose distinct report mappings.")
    for entry in entries:
        try:
            row = decision_event(entry, "preflight")
            date.fromisoformat(entry["date"])
            check_safe(row)
            validate("notebook/decisions.jsonl", row)
        except (OfficeError, ValueError):
            issues.append(
                "Journal entry has an invalid date or conviction: " + entry["migrated_from"]
            )
    for band in policy["bands"]:
        if (
            isinstance(band, dict)
            and isinstance(band.get("min"), (int, float))
            and isinstance(band.get("max"), (int, float))
            and band["min"] > band["max"]
        ):
            issues.append("A policy band minimum exceeds its maximum.")
    for snapshot in snapshots.values():
        try:
            parsed = datetime.fromisoformat(snapshot["as_of"].replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                raise ValueError("timezone")
            snapshot["as_of"] = parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")
            amounts = [snapshot["balance"]["net_value"]]
            amounts += [
                p.get(k)
                for p in snapshot["positions"]
                for k in ("qty", "price", "value", "cost_basis")
            ]
            amounts += [t["amount"] for t in snapshot["transactions"]]
            if any(v is not None and not Decimal(str(v)).is_finite() for v in amounts):
                raise ValueError("amount")
        except (ValueError, TypeError, ArithmeticError):
            issues.append("An account has an invalid amount or observation timestamp.")
    return data


def migrate(root, source, dry_run=False, force=False):
    from fo.clauses import parse as parse_clause
    from fo.operations import legacy_jobs

    source = Path(source).expanduser().resolve()
    if (
        source == root.resolve()
        or root.resolve().is_relative_to(source)
        or source.is_relative_to(root.resolve())
    ):
        raise OfficeError(
            "overlapping_migration", "Source and destination must be separate directories."
        )
    data = plan(source)
    if not data["issues"]:
        # Exercise the exact normalization and row contracts before changing any profile.
        ingest(root, "v1-migration", data["snapshots"], dry_run=True, locked=True)
    digest = hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()
    counts = {
        "accounts": len(data["registry"]),
        "positions": sum(len(a["positions"]) for a in data["snapshots"]),
        "transactions": sum(len(a["transactions"]) for a in data["snapshots"]),
        "reports": len(data["reports"]),
        "decisions": len(data["decisions"]),
        "corrections": len(data["corrections"]),
    }
    parsed_count, unparsed = 0, []
    for entry in data["decisions"]:
        try:
            parse_clause(entry["invalidate"])
            parsed_count += 1
        except OfficeError:
            unparsed.append(entry["invalidate"])
    summary = {
        "dry_run": dry_run,
        "counts": counts,
        "issues": data["issues"],
        "invalidation_clauses": {"parseable": parsed_count, "free_text": unparsed},
        "legacy_jobs": legacy_jobs(),
        "secrets": "Not read or migrated; reconnect Schwab and SimpleFIN through fo setup. Re-enter optional AlphaVantage and FRED keys through fo auth.",
        "history": "Schwab transaction history begins at the first new sync.",
        "rollback": "The source is untouched. Preserve any new work, then remove only the newly created destination office to roll back.",
    }
    if dry_run:
        return summary
    marker = contained(root, "notebook/migration.json")
    with office_lock(root):
        if marker.exists():
            if force and json.loads(marker.read_text())["digest"] == digest:
                return {**summary, "unchanged": True}
            raise OfficeError(
                "migration_exists", "Migration already applied; preserve subsequent office work."
            )
        populated = any(
            read_rows(root, f"data/{name}.jsonl")
            for name in ("positions", "balances", "transactions")
        ) or bool(read_rows(root, "notebook/decisions.jsonl"))
        if populated:
            raise OfficeError(
                "target_not_empty",
                "Migrate into a fresh initialized office; existing financial records are never overwritten.",
            )
        if data["issues"]:
            atomic_write(
                contained(root, "notebook/migration-report.md"),
                "# Migration requires mapping\n\n"
                + "\n".join("- " + issue for issue in data["issues"])
                + "\n",
            )
            raise OfficeError(
                "migration_ambiguous",
                "Migration mappings need resolution; see notebook/migration-report.md. Financial records were not written.",
            )
        write_json(contained(root, "profile/accounts.json"), {"accounts": data["registry"]})
        household = contained(root, "profile/household.md")
        if not force:
            atomic_write(
                household,
                "# Household\n\n```json\n" + json.dumps(data["household"], indent=2) + "\n```\n",
            )
        write_json(contained(root, "profile/ips.json"), data["ips"])
        write_json(contained(root, "profile/goals.json"), data["goals"])
        write_json(
            contained(root, "profile/tax.json"),
            {
                "legacy_sources": {k: v for k, v in data["notes"].items() if "tax" in k},
                "notes": [
                    "Reconcile legacy tax source periods before using them for a recommendation."
                ],
            },
        )
        atomic_write(
            contained(root, "notebook/legacy-context.md"),
            "# Legacy context\n\nHistorical source material; reconcile policy and tax mappings before cutover.\nThese dated source copies are not live balances or active allocation rules.\n\n```json\n"
            + json.dumps(data["notes"], indent=2)
            + "\n```\n",
        )
        ingest(root, "v1-migration", data["snapshots"], locked=True)
        for entry in data["decisions"]:
            key = identifier()
            append(
                root,
                "notebook/decisions.jsonl",
                decision_event(entry, key),
            )
            if entry["closed"]:
                append(
                    root,
                    "notebook/decisions.jsonl",
                    {
                        "id": key,
                        "event": "closed",
                        "as_of": now(),
                        "outcome": "unknown",
                        "note": "Migrated closed status.",
                    },
                )
        for report in data["reports"]:
            meta = {
                "kind": report["kind"],
                "subject": "household",
                "date": report["date"],
                "model": "legacy",
                "context_level": "full",
                "playbooks": [],
                "prior": None,
                "summary": "Migrated legacy report.",
                "decision_ids": [],
                "migrated_from": report["source"],
            }
            atomic_write(
                contained(root, report["path"]),
                "---\n"
                + yaml.safe_dump(meta)
                + "---\n\n"
                + report["body"]
                + "\n\n"
                + CLOSING
                + "\n",
            )
        correction_path = contained(root, "notebook/corrections.md")
        old = correction_path.read_text()
        first_id = old.count('"event": "added"') + 1
        for index, text in enumerate(data["corrections"], first_id):
            row = {
                "id": str(index),
                "event": "added",
                "date": now()[:10],
                "scope": "global",
                "text": text,
            }
            old += "\n<!-- fo-correction " + json.dumps(row) + " -->\n- " + text + "\n"
        atomic_write(correction_path, old)
        write_json(marker, {"digest": digest, "counts": counts})
        atomic_write(
            contained(root, "notebook/migration-report.md"),
            "# Migration report\n\n" + json.dumps(summary, indent=2) + "\n",
        )
        from fo.store.index import reindex

        reindex(root, locked=True)
    return summary
