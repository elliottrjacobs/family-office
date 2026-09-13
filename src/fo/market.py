from datetime import UTC, datetime
from decimal import Decimal

from fo.errors import OfficeError
from fo.providers.market import Market, fetch_json
from fo.store.authored import load


def stamped(result):
    return {
        **result,
        "as_of": datetime.fromtimestamp(result["fetched_at"], UTC)
        .isoformat()
        .replace("+00:00", "Z"),
        "untrusted_fields": ["data"],
    }


def quote(root, symbol, read_only=False):
    result = stamped(Market(root, read_only).quote(symbol))
    body = result["data"]
    price = body.get(symbol, {}).get("quote", {}).get("lastPrice")
    if price is None:
        price = body.get("Global Quote", {}).get("05. price")
    if price is None:
        raise OfficeError("missing_price", "Provider response does not contain a price.")
    return {**result, "symbol": symbol, "price": str(Decimal(str(price)))}


def cik(client, symbol):
    agent = client.config.get("providers", {}).get("edgar", {}).get("user_agent")
    result = client.cache.get(
        "edgar:tickers",
        86400,
        (
            lambda: fetch_json(
                "https://www.sec.gov/files/company_tickers.json", headers={"User-Agent": agent}
            )
        )
        if agent
        else None,
    )
    matches = [r["cik_str"] for r in result["data"].values() if r["ticker"] == symbol]
    if len(matches) != 1:
        raise OfficeError("unknown_symbol", "No unique SEC issuer mapping exists for this symbol.")
    return matches[0]


def fundamentals(root, symbol, read_only=False):
    from fo.fundamentals import edgar_reports, normalize

    client = Market(root, read_only)
    try:
        result = client.alpha("OVERVIEW", symbol)
        if not result["data"].get("Symbol"):
            raise OfficeError("missing_fundamentals", "Overview is unavailable.")
        statements, missing = [], []
        for function in ("INCOME_STATEMENT", "BALANCE_SHEET", "CASH_FLOW"):
            try:
                statements.append(client.alpha(function, symbol)["data"])
            except OfficeError:
                statements.append({})
                missing.append(function)
        result = {**result, "data": normalize(result["data"], *statements)}
        if missing:
            try:
                fallback = client.edgar(
                    f"api/xbrl/companyfacts/CIK{int(cik(client, symbol)):010d}.json"
                )
                result = {
                    **fallback,
                    "data": {**edgar_reports(fallback["data"]), "Symbol": symbol},
                    "fallback": "sec_edgar",
                }
            except OfficeError:
                result["data_gaps"] = missing
    except OfficeError:
        result = client.edgar(f"api/xbrl/companyfacts/CIK{int(cik(client, symbol)):010d}.json")
        result = {**result, "data": edgar_reports(result["data"])}
    return stamped(result)


def filings(root, symbol, form=None, read_only=False):
    client = Market(root, read_only)
    result = stamped(client.edgar(f"submissions/CIK{int(cik(client, symbol)):010d}.json"))
    recent = result["data"].get("filings", {}).get("recent", {})
    rows = [
        {
            key: values[i]
            for key, values in recent.items()
            if isinstance(values, list) and i < len(values)
        }
        for i in range(len(recent.get("form", [])))
        if not form or recent["form"][i] == form
    ]
    return {**result, "data": rows}


def screen(
    root, concept, period, minimum=None, maximum=None, universe=None, limit=20, read_only=False
):
    if not 1 <= limit <= 1000:
        raise OfficeError("invalid_limit", "Limit must be between 1 and 1000.")
    result = stamped(Market(root, read_only).frames(concept, period))
    allowed = None
    if universe:
        universes = load(root, "universes")["universes"]
        if universe not in universes:
            raise OfficeError("unknown_universe", "Universe is not configured.")
        client = Market(root, read_only)
        allowed = {int(cik(client, symbol)) for symbol in universes[universe]}
    rows = [
        r
        for r in result["data"].get("data", [])
        if (allowed is None or r["cik"] in allowed)
        and (minimum is None or Decimal(str(r["val"])) >= Decimal(minimum))
        and (maximum is None or Decimal(str(r["val"])) <= Decimal(maximum))
    ]
    rows.sort(key=lambda r: Decimal(str(r["val"])), reverse=True)
    return {**result, "data": rows[:limit], "concept": concept, "period": period}


def metric_observations(root, symbol, metric, decision=None):
    decision = decision or {}
    try:
        if metric == "cash_months":
            from fo.compute import cashflow, context, number, total

            state = context(root, True)
            cash = total(number(b.get("cash")) for b in state["balances"])
            outflow = total(m["spend"] for m in cashflow(root, 3, True)["months"]) / 3
            if cash is None or not outflow:
                return []
            return [
                {
                    "value": str(cash / outflow),
                    "as_of": state["as_of"],
                    "source": "balances.cash/cashflow.average_spend_3m",
                }
            ]
        if metric in {"price", "drawdown_from_entry"}:
            result = quote(root, symbol, True)
            value = Decimal(result["price"])
            if metric == "drawdown_from_entry":
                if not decision.get("price_at"):
                    return []
                value = max(Decimal(0), 1 - value / Decimal(str(decision["price_at"])))
            return [{"value": str(value), "as_of": result["as_of"], "source": "cached_quote"}]
        result = fundamentals(root, symbol, True)
        # Explicit period observations are a normalized fixture/import contract.
        history = result["data"].get("metrics", {}).get(metric, [])
        return [r for r in history if r.get("period", "") > decision.get("date", "")]
    except OfficeError:
        return []
