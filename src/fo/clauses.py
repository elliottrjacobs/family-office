import operator
import re
from datetime import date
from decimal import Decimal

from fo.errors import OfficeError

METRICS = {
    "price": (0, None, False, False),
    "weight": (0, 1, False, False),
    "days_open": (0, None, True, False),
    "drawdown_from_entry": (0, 1, False, False),
    "rev_growth_yoy": (-1, 10, False, True),
    "gross_margin": (-10, 1, False, True),
    "fcf_ttm": (None, None, False, True),
    "cash_months": (0, None, False, False),
}
OPS = {"<": operator.lt, "<=": operator.le, ">": operator.gt, ">=": operator.ge, "==": operator.eq}


def parse(text):
    match = re.fullmatch(
        r"([a-z_]+)\s*(<=|>=|==|<|>)\s*(-?\d+(?:\.\d+)?)(?:\s+for\s+([1-9]\d*)q)?", text.strip()
    )
    if not match or match[1] not in METRICS:
        raise OfficeError(
            "invalid_clause",
            "Use a known metric, comparison, and decimal fraction; percentages are not accepted.",
        )
    metric, op, threshold, quarters = match.groups()
    low, high, integer, quarterly = METRICS[metric]
    value = Decimal(threshold)
    if (
        (low is not None and value < low)
        or (high is not None and value > high)
        or (integer and value != int(value))
    ):
        raise OfficeError(
            "invalid_clause", "Threshold is outside the metric domain; ratios use fractions."
        )
    if op == "==" and not integer:
        raise OfficeError("invalid_clause", "Equality is supported only for integer metrics.")
    if quarters and not quarterly:
        raise OfficeError("invalid_clause", "The for Nq suffix requires a quarterly metric.")
    return {
        "metric": metric,
        "op": op,
        "threshold": threshold,
        "quarters": int(quarters) if quarters else None,
    }


def evaluate(clause, observations):
    if not observations:
        return None
    count = clause.get("quarters") or 1
    rows = sorted(observations, key=lambda r: r.get("period", r.get("as_of", "")))
    if len(rows) < count:
        return None
    rows = rows[-count:]
    if count > 1:
        periods = [date.fromisoformat(r["period"]) for r in rows]
        indices = [d.year * 4 + (d.month - 1) // 3 for d in periods]
        if any(b - a != 1 for a, b in zip(indices, indices[1:], strict=False)):
            return None
    if any(r.get("value") is None for r in rows):
        return None
    return all(
        OPS[clause["op"]](Decimal(str(r["value"])), Decimal(clause["threshold"])) for r in rows
    )
