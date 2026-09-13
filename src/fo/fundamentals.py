"""Normalize reported fundamentals without filling missing facts with zero."""

from datetime import date
from decimal import Decimal, InvalidOperation


def num(value):
    try:
        result = Decimal(str(value))
        return result if result.is_finite() else None
    except InvalidOperation:
        return None


def ratio(a, b):
    return a / b if a is not None and b not in (None, 0) else None


def difference(a, b):
    return a - b if a is not None and b is not None else None


def normalize(overview, income=None, balance=None, cash=None):
    if "normalized" in overview:
        return overview
    income, balance, cash = income or {}, balance or {}, cash or {}
    annual = sorted(
        income.get("annualReports", []), key=lambda r: r.get("fiscalDateEnding", ""), reverse=True
    )
    assets = balance.get("annualReports", [])
    flows = cash.get("annualReports", [])
    current, previous = (annual + [{}, {}])[:2]

    def aligned(rows, report):
        return next(
            (
                r
                for r in rows
                if r.get("fiscalDateEnding")
                and r.get("fiscalDateEnding") == report.get("fiscalDateEnding")
            ),
            {},
        )

    b0, b1 = aligned(assets, current), aligned(assets, previous)
    cf = aligned(flows, current)
    revenue = num(overview.get("RevenueTTM"))
    if revenue is None:
        revenue = num(current.get("totalRevenue"))
    gross = num(overview.get("GrossProfitTTM"))
    margin = ratio(gross, num(overview.get("RevenueTTM")))
    if margin is None:
        margin = ratio(num(current.get("grossProfit")), num(current.get("totalRevenue")))
    metrics = {
        "revenue": revenue,
        "revenue_growth": num(overview.get("QuarterlyRevenueGrowthYOY")),
        "gross_margin": margin,
        "operating_income": num(current.get("operatingIncome")),
        "fcf": difference(num(cf.get("operatingCashflow")), num(cf.get("capitalExpenditures"))),
        "cash_flow": num(cf.get("operatingCashflow")),
        "roa": ratio(num(current.get("netIncome")), num(b0.get("totalAssets"))),
        "accrual_quality": difference(
            num(cf.get("operatingCashflow")), num(current.get("netIncome"))
        ),
        "shares_change": difference(
            num(b0.get("commonStockSharesOutstanding")), num(b1.get("commonStockSharesOutstanding"))
        ),
        "liquidity_change": difference(
            ratio(num(b0.get("totalCurrentAssets")), num(b0.get("totalCurrentLiabilities"))),
            ratio(num(b1.get("totalCurrentAssets")), num(b1.get("totalCurrentLiabilities"))),
        ),
        "leverage_change": difference(
            ratio(num(b0.get("longTermDebt")), num(b0.get("totalAssets"))),
            ratio(num(b1.get("longTermDebt")), num(b1.get("totalAssets"))),
        ),
        "margin_change": difference(
            ratio(num(current.get("grossProfit")), num(current.get("totalRevenue"))),
            ratio(num(previous.get("grossProfit")), num(previous.get("totalRevenue"))),
        ),
        "turnover_change": difference(
            ratio(num(current.get("totalRevenue")), num(b0.get("totalAssets"))),
            ratio(num(previous.get("totalRevenue")), num(b1.get("totalAssets"))),
        ),
    }
    metrics["roa_change"] = difference(
        metrics["roa"], ratio(num(previous.get("netIncome")), num(b1.get("totalAssets")))
    )
    if metrics["revenue_growth"] is None:
        growth = ratio(num(current.get("totalRevenue")), num(previous.get("totalRevenue")))
        metrics["revenue_growth"] = growth - 1 if growth is not None else None
    ev = num(overview.get("EnterpriseValue"))
    metrics["earnings_yield"] = ratio(metrics["operating_income"], ev)
    capital = difference(num(b0.get("totalCurrentAssets")), num(b0.get("totalCurrentLiabilities")))
    fixed = num(b0.get("propertyPlantEquipment"))
    metrics["roic"] = ratio(
        metrics["operating_income"],
        capital + fixed if capital is not None and fixed is not None else None,
    )
    observations = {"rev_growth_yoy": [], "gross_margin": [], "fcf_ttm": []}
    quarters = sorted(income.get("quarterlyReports", []), key=lambda r: r["fiscalDateEnding"])
    for index, row in enumerate(quarters):
        period = row["fiscalDateEnding"]
        margin = ratio(num(row.get("grossProfit")), num(row.get("totalRevenue")))
        if margin is not None:
            observations["gross_margin"].append(
                {
                    "value": str(margin),
                    "period": period,
                    "as_of": period,
                    "source": "income.quarterlyReports",
                }
            )
        if (
            index >= 4
            and 350
            <= (
                date.fromisoformat(period)
                - date.fromisoformat(quarters[index - 4]["fiscalDateEnding"])
            ).days
            <= 380
        ):
            growth = ratio(
                num(row.get("totalRevenue")), num(quarters[index - 4].get("totalRevenue"))
            )
            if growth is not None:
                observations["rev_growth_yoy"].append(
                    {
                        "value": str(growth - 1),
                        "period": period,
                        "as_of": period,
                        "source": "income.quarterlyReports",
                    }
                )
    flow_quarters = sorted(cash.get("quarterlyReports", []), key=lambda r: r["fiscalDateEnding"])
    for index in range(3, len(flow_quarters)):
        window = flow_quarters[index - 3 : index + 1]
        dates = [date.fromisoformat(r["fiscalDateEnding"]) for r in window]
        if not all(70 <= (b - a).days <= 110 for a, b in zip(dates, dates[1:], strict=False)):
            continue
        values = [
            difference(num(r.get("operatingCashflow")), num(r.get("capitalExpenditures")))
            for r in window
        ]
        if all(v is not None for v in values):
            observations["fcf_ttm"].append(
                {
                    "value": str(sum(values)),
                    "period": dates[-1].isoformat(),
                    "as_of": dates[-1].isoformat(),
                    "source": "cash.quarterlyReports",
                }
            )
    return {
        **overview,
        "normalized": {k: str(v) if v is not None else None for k, v in metrics.items()},
        "metrics": observations,
        "source_period": current.get("fiscalDateEnding", overview.get("LatestQuarter")),
    }


def edgar_reports(body):
    facts = body.get("facts", {}).get("us-gaap", {})
    tags = {
        "totalRevenue": (
            "RevenueFromContractWithCustomerExcludingAssessedTax",
            "Revenues",
            "SalesRevenueNet",
        ),
        "grossProfit": ("GrossProfit",),
        "netIncome": ("NetIncomeLoss",),
        "operatingIncome": ("OperatingIncomeLoss",),
        "totalAssets": ("Assets",),
        "totalCurrentAssets": ("AssetsCurrent",),
        "totalCurrentLiabilities": ("LiabilitiesCurrent",),
        "longTermDebt": ("LongTermDebtNoncurrent",),
        "commonStockSharesOutstanding": ("CommonStockSharesOutstanding",),
        "operatingCashflow": ("NetCashProvidedByUsedInOperatingActivities",),
        "capitalExpenditures": ("PaymentsToAcquirePropertyPlantAndEquipment",),
        "propertyPlantEquipment": ("PropertyPlantAndEquipmentNet",),
    }
    annual, quarterly = {}, {}
    for field, choices in tags.items():
        tag = next((facts[t] for t in choices if t in facts), {})
        units = tag.get("units", {})
        values = units.get("USD", units.get("shares", []))
        for value in sorted(values, key=lambda r: r.get("filed", "")):
            frame = value.get("frame", "")
            if not frame.startswith("CY"):
                continue
            target = quarterly if "Q" in frame else annual
            if frame.endswith("I") and "Q" in frame:
                # Instant facts can populate annual year-end balance sheets too.
                if frame[6:8] == "Q4":
                    annual.setdefault(value["end"], {"fiscalDateEnding": value["end"]})[field] = (
                        str(value["val"])
                    )
            target.setdefault(value["end"], {"fiscalDateEnding": value["end"]})[field] = str(
                value["val"]
            )
    reports = {
        "annualReports": sorted(annual.values(), key=lambda r: r["fiscalDateEnding"], reverse=True),
        "quarterlyReports": sorted(
            quarterly.values(), key=lambda r: r["fiscalDateEnding"], reverse=True
        ),
    }
    return normalize(body, reports, reports, reports)
