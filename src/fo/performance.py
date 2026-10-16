"""Money-weighted account returns from canonical snapshots. Unknown evidence stays unknown."""

from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from fo.compute import account_role, context, envelope, number, total
from fo.config import read_config
from fo.errors import OfficeError
from fo.store.authored import load
from fo.store.index import project
from fo.store.jsonl import read_rows


def modified_dietz(begin, end, flows, start, finish):
    """Return over [start, finish]; flows are (date, signed amount) with deposits positive."""
    days = (finish - start).days
    if begin is None or end is None or days <= 0:
        return None
    net = sum((amount for _, amount in flows), Decimal(0))
    weighted = sum(
        (amount * Decimal((finish - day).days) / Decimal(days) for day, amount in flows),
        Decimal(0),
    )
    base = begin + weighted
    return (end - begin - net) / base if base > 0 else None


def annualized(value, days):
    if value is None or days < 365 or value <= -1:
        return None
    return (1 + value) ** (Decimal(365) / Decimal(days)) - 1


def performance(root, since, account=None, benchmark=None, read_only=False):
    try:
        date.fromisoformat(since)
    except ValueError as exc:
        raise OfficeError("invalid_date", "Use --since YYYY-MM-DD.") from exc
    zone = ZoneInfo(read_config(root).get("office", {}).get("timezone", "UTC"))

    def local_day(stamp):
        return datetime.fromisoformat(stamp.replace("Z", "+00:00")).astimezone(zone).date()

    state = context(root, read_only)
    opening = {r["account_id"]: r for r in project(root, as_of=since)["balances"]}
    closing = {r["account_id"]: r for r in state["balances"]}
    registry = {a["id"]: a for a in load(root, "accounts")["accounts"]}
    if account and account not in registry:
        raise OfficeError("unknown_account", "Account is not in the registry.")
    chosen = (
        [account]
        if account
        else [i for i, a in registry.items() if account_role(a) == "investment"]
    )
    history = read_rows(root, "data/balances.jsonl")
    rows = []
    for account_id in sorted(chosen):
        first, last = opening.get(account_id), closing.get(account_id)
        begin = number(first.get("net_value")) if first else None
        end = number(last.get("net_value")) if last else None
        start = local_day(first["as_of"]) if first else None
        finish = local_day(last["as_of"]) if last else None
        activity = [
            t
            for t in state["transactions"]
            if t["account_id"] == account_id
            and not t.get("pending")
            and t.get("status") != "expired"
            and start
            and finish
            and start < date.fromisoformat(t.get("transacted_at") or t["posted_date"]) <= finish
        ]
        flows = [
            (date.fromisoformat(t.get("transacted_at") or t["posted_date"]), number(t["amount"]))
            for t in activity
            if t.get("kind") == "transfer"
        ]
        classified = any(
            t.get("kind") for t in state["transactions"] if t["account_id"] == account_id
        )
        value = modified_dietz(begin, end, flows, start, finish) if start and finish else None
        days = (finish - start).days if start and finish else None
        rows.append(
            {
                "account_id": account_id,
                "start": start,
                "end": finish,
                "begin_value": begin,
                "end_value": end,
                "net_flows": sum((a for _, a in flows), Decimal(0)) if start and finish else None,
                "gain": end - begin - sum((a for _, a in flows), Decimal(0))
                if begin is not None and end is not None
                else None,
                "return": value,
                "annualized": annualized(value, days) if days else None,
                "dividends": sum(
                    (number(t["amount"]) for t in activity if t.get("kind") == "dividend"),
                    Decimal(0),
                ),
                "fees": sum((number(t["fees"]) for t in activity if t.get("fees")), Decimal(0)),
                # Without typed transactions, deposits cannot be told apart from gains.
                "flow_evidence": "transactions" if classified else "none_assumed",
                "reason": None
                if value is not None
                else "no_snapshot_at_start"
                if first is None
                else "insufficient_history",
                "earliest_snapshot": min(
                    (r["as_of"] for r in history if r["account_id"] == account_id), default=None
                ),
            }
        )
    complete = rows and all(r["return"] is not None for r in rows)
    combined = None
    if complete:
        start, finish = min(r["start"] for r in rows), max(r["end"] for r in rows)
        all_flows = [
            (date.fromisoformat(t.get("transacted_at") or t["posted_date"]), number(t["amount"]))
            for t in state["transactions"]
            if t["account_id"] in chosen
            and t.get("kind") == "transfer"
            and not t.get("pending")
            and t.get("status") != "expired"
            and start < date.fromisoformat(t.get("transacted_at") or t["posted_date"]) <= finish
        ]
        combined = modified_dietz(
            total(r["begin_value"] for r in rows),
            total(r["end_value"] for r in rows),
            all_flows,
            start,
            finish,
        )
    result = envelope(
        state,
        since=since,
        method="modified_dietz",
        accounts=rows,
        total_return=combined,
        realized_gains=None,
        realized_gains_reason="missing_lot_evidence",
    )
    if benchmark:
        from fo.market import benchmark_return

        result["benchmark"] = benchmark_return(root, benchmark, since, read_only)
        if combined is not None and result["benchmark"]["return"] is not None:
            result["excess_return"] = combined - Decimal(result["benchmark"]["return"])
    return result
