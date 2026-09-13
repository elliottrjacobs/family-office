"""Offline household computations. Decimal strings are the numeric API contract."""

import re
from collections import defaultdict
from datetime import UTC, date, datetime
from decimal import Decimal

from fo.config import read_config
from fo.errors import OfficeError
from fo.store.authored import load
from fo.store.index import project, read_state


def number(value):
    return Decimal(str(value)) if value is not None else None


def total(values):
    items = list(values)
    return None if any(v is None for v in items) else sum(items, Decimal(0))


def context(root, read_only=False, as_of=None):
    if as_of:
        date.fromisoformat(as_of)
    state = project(root, as_of=as_of) if as_of else read_state(root, read_only)
    cadence = read_config(root).get("schedule", {}).get("sync_hours", 24)
    state["stale_providers"] = [
        name
        for name, run in state["providers"].items()
        if (
            datetime.now(UTC) - datetime.fromisoformat(run["as_of"].replace("Z", "+00:00"))
        ).total_seconds()
        > cadence * 3600
    ]
    return state


def envelope(state, **result):
    return {
        "as_of": state["as_of"],
        "stale_accounts": state["stale_accounts"],
        "stale_providers": state["stale_providers"],
        **result,
    }


def networth(root, by="account", as_of=None, read_only=False):
    if by not in {"account", "type", "owner"}:
        raise OfficeError("invalid_group", "Group by account, type, or owner.")
    state = context(root, read_only, as_of)
    registry = {a["id"]: a for a in load(root, "accounts")["accounts"]}
    rows = []
    for row in state["balances"]:
        account = registry.get(row["account_id"], {})
        value = number(row.get("net_value"))
        # Provider net_value is signed and already includes account liabilities.
        rows.append(
            {
                "account_id": row["account_id"],
                "type": account.get("type", "unknown"),
                "owner": account.get("owner", "unknown"),
                "value": value,
            }
        )
    represented = {r["account_id"] for r in rows}
    missing = sorted(set(registry) - represented)
    for account_id in missing:
        a = registry[account_id]
        rows.append(
            {
                "account_id": account_id,
                "type": a.get("type", "unknown"),
                "owner": a.get("owner", "unknown"),
                "value": None,
            }
        )
    groups = defaultdict(list)
    for row in rows:
        groups[row["account_id"] if by == "account" else row[by]].append(row["value"])
    return envelope(
        state,
        total=total(r["value"] for r in rows) if rows else None,
        groups=[{"name": key, "value": total(values)} for key, values in sorted(groups.items())],
        missing_accounts=missing,
    )


def allocation(root, read_only=False):
    state = context(root, read_only)
    worth = networth(root, read_only=read_only)["total"]
    policy = load(root, "ips")
    symbols = defaultdict(lambda: Decimal(0))
    unknown = set()
    for row in state["positions"]:
        symbols[row["symbol"]] += Decimal(0)
        if row.get("value") is None:
            unknown.add(row["symbol"])
        else:
            symbols[row["symbol"]] += number(row["value"])
    weights = {
        s: value / worth if worth and s not in unknown else None for s, value in symbols.items()
    }
    bands = []
    classes = policy.get("classifications", {})
    for band in policy["bands"]:
        members = [s for s in symbols if classes.get(s, s) == band["name"]]
        weight = total(weights[s] for s in members) if worth else None
        if band["name"].lower() == "cash":
            cash = total(number(r.get("cash")) for r in state["balances"])
            weight = cash / worth if cash is not None and worth else None
        low, high = number(band["min"]), number(band["max"])
        drift = (
            None
            if weight is None
            else weight - low
            if weight < low
            else weight - high
            if weight > high
            else Decimal(0)
        )
        bands.append(
            {
                "name": band["name"],
                "weight": weight,
                "min": low,
                "max": high,
                "drift_points": drift * 100 if drift is not None else None,
                "outside_band": bool(drift) if drift is not None else None,
            }
        )
    return envelope(
        state,
        weights=weights,
        bands=bands,
        unclassified=sorted(s for s in symbols if s not in classes),
        total=worth,
    )


def categorized(root, state=None):
    state = state or context(root, True)
    rules = load(root, "categories")["rules"]
    result = []
    ordered = sorted(
        enumerate(rules),
        key=lambda pair: (
            0 if pair[1].get("payee") else 1 if pair[1].get("pattern") else 2,
            pair[0],
        ),
    )
    for tx in state["transactions"]:
        category, transfer = "needs-review", False
        for _, rule in ordered:
            if rule.get("account") and rule["account"] != tx["account_id"]:
                continue
            if rule.get("payee") and rule["payee"].casefold() != (tx.get("payee") or "").casefold():
                continue
            try:
                if rule.get("pattern") and not re.search(
                    rule["pattern"], tx.get("description") or "", re.I
                ):
                    continue
            except re.error as exc:
                raise OfficeError(
                    "invalid_rule", "A category rule contains an invalid pattern."
                ) from exc
            category = rule["category"]
            transfer = rule.get("transfer", False) or category.casefold() == "transfer"
            break
        result.append({**tx, "category": category, "transfer": transfer})
    return result


def spend(root, month, category=None, read_only=False):
    try:
        date.fromisoformat(month + "-01")
    except ValueError as exc:
        raise OfficeError("invalid_month", "Use YYYY-MM.") from exc
    state = context(root, read_only)
    rows = [
        t
        for t in categorized(root, state)
        if (t.get("posted_date") or t.get("transacted_at") or "").startswith(month)
        and not t.get("pending")
        and t.get("status") != "expired"
        and not t["transfer"]
        and (not category or t["category"] == category)
    ]
    expense = [t for t in rows if number(t["amount"]) < 0]
    groups = defaultdict(lambda: Decimal(0))
    for tx in expense:
        groups[tx["category"]] -= number(tx["amount"])
    return envelope(
        state,
        month=month,
        spend=sum(groups.values(), Decimal(0)),
        income=sum((number(t["amount"]) for t in rows if number(t["amount"]) > 0), Decimal(0)),
        categories=dict(groups),
        transaction_count=len(rows),
    )


def cashflow(root, months=3, read_only=False):
    if not 1 <= months <= 120:
        raise OfficeError("invalid_months", "Months must be between 1 and 120.")
    today = date.today()
    index = today.year * 12 + today.month - 1
    rows = []
    for offset in reversed(range(months)):
        year, month = divmod(index - offset, 12)
        row = spend(root, f"{year:04}-{month + 1:02}", read_only=read_only)
        rows.append(
            {
                "month": row["month"],
                "income": row["income"],
                "spend": row["spend"],
                "net": row["income"] - row["spend"],
            }
        )
    return envelope(context(root, read_only), months=rows)


def goals(root, read_only=False):
    state = context(root, read_only)
    balances = {r["account_id"]: number(r.get("net_value")) for r in state["balances"]}
    rows = []
    for goal in load(root, "goals")["goals"]:
        current = (
            total(balances.get(a) for a in goal.get("accounts", []))
            if goal.get("accounts")
            else None
        )
        target = number(goal["target"])
        due = date.fromisoformat(goal["date"]) if goal.get("date") else None
        months = (
            max(1, (due.year - date.today().year) * 12 + due.month - date.today().month)
            if due
            else None
        )
        required = (
            max(Decimal(0), target - current) / months if current is not None and months else None
        )
        planned = number(goal.get("monthly_contribution"))
        rows.append(
            {
                "name": goal["name"],
                "target": target,
                "current": current,
                "progress": current / target if current is not None and target else None,
                "required_monthly": required,
                "behind_monthly": max(Decimal(0), required - planned)
                if required is not None and planned is not None
                else None,
                "status": "unknown"
                if required is None or planned is None
                else "on_track"
                if planned >= required
                else "behind",
            }
        )
    return envelope(state, goals=rows)


def lots(root, symbol, read_only=False):
    state = context(root, read_only)
    rows = []
    for p in state["positions"]:
        if p["symbol"] != symbol:
            continue
        acquired = date.fromisoformat(p["acquired_at"][:10]) if p.get("acquired_at") else None
        sourced = bool(p.get("lot_id") and acquired)
        basis = number(p.get("cost_basis")) if sourced else None
        rows.append(
            {
                "account_id": p["account_id"],
                "lot_id": p.get("lot_id"),
                "qty": p.get("qty"),
                "acquired_at": p.get("acquired_at"),
                "basis": basis,
                "gain": number(p["value"]) - basis
                if basis is not None and p.get("value") is not None
                else None,
                "holding_period": ("long" if (date.today() - acquired).days > 365 else "short")
                if sourced
                else None,
                "reason": None if sourced and basis is not None else "missing_lot_evidence",
            }
        )
    return envelope(state, symbol=symbol, lots=rows)
