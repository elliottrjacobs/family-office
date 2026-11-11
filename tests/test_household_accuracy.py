import json
from datetime import date
from decimal import Decimal

import pytest

from fo import compute, market
from fo.doctor import diagnose
from fo.init import initialize
from fo.market import metric_observations
from fo.sync import ingest


@pytest.fixture
def office(tmp_path):
    root = tmp_path / "office"
    initialize(root)
    (root / "profile/accounts.json").write_text(
        json.dumps(
            {
                "accounts": [
                    {"id": "brokerage", "provider": "schwab", "last4": "1111"},
                    {"id": "checking", "provider": "simplefin", "last4": "", "type": "checking"},
                    {"id": "home-loan", "provider": "simplefin", "last4": "", "role": "loan"},
                ]
            }
        )
    )
    (root / "profile/ips.json").write_text(
        json.dumps(
            {
                "bands": [
                    {"name": "cash", "min": 0.05, "max": 0.2},
                    {"name": "equity", "min": 0.5, "max": 0.9},
                ],
                "classifications": {"ACME": "equity"},
            }
        )
    )
    ingest(
        root,
        "schwab",
        [
            {
                "account_id": "brokerage",
                "positions": [{"symbol": "ACME", "qty": "10", "price": "9000", "value": "90000"}],
                "balance": {"net_value": "100000", "cash": "10000"},
                "transactions": [
                    {
                        "provider_id": "t1",
                        "amount": "-10000",
                        "transacted_at": "2026-08-02",
                        "description": "TRADE",
                        "kind": "trade",
                    }
                ],
            }
        ],
    )
    ingest(
        root,
        "simplefin",
        [
            {
                "account_id": "checking",
                "positions": [],
                "balance": {"net_value": "20000"},
                "transactions": [
                    {
                        "provider_id": "c1",
                        "amount": "-300",
                        "transacted_at": "2026-08-03",
                        "description": "Hardware Store",
                    },
                    {
                        "provider_id": "c2",
                        "amount": "100",
                        "transacted_at": "2026-08-05",
                        "description": "Hardware Store refund",
                    },
                    {
                        "provider_id": "c3",
                        "amount": "5000",
                        "transacted_at": "2026-08-15",
                        "description": "Payroll",
                    },
                ],
            },
            {
                "account_id": "home-loan",
                "positions": [],
                "balance": {"net_value": "-80000"},
                "transactions": [],
            },
        ],
    )
    (root / "profile/categories.yaml").write_text(
        "rules:\n"
        "  - pattern: Hardware\n    category: home\n"
        "  - pattern: Payroll\n    category: salary\n    income: true\n"
    )
    return root


def test_allocation_uses_investable_assets_and_counts_bank_cash(office):
    result = compute.allocation(office)
    assert compute.networth(office)["total"] == Decimal(40000)
    assert result["total"] == Decimal(120000)
    assert result["excluded_accounts"] == ["home-loan"]
    bands = {b["name"]: b for b in result["bands"]}
    assert bands["cash"]["weight"] == Decimal(30000) / Decimal(120000)
    assert bands["equity"]["weight"] == Decimal("0.75")
    assert bands["equity"]["outside_band"] is False


def test_spend_ignores_portfolio_activity_and_nets_refunds(office):
    result = compute.spend(office, "2026-08")
    assert result["spend"] == Decimal(200)
    assert result["categories"] == {"home": Decimal(200)}
    assert result["income"] == Decimal(5000)
    assert result["excluded_investment_transactions"] == 1


@pytest.mark.parametrize(
    ("start", "as_of", "expected"),
    [
        ("2026-07-01", "2026-10-20T12:00:00Z", "10"),
        ("2026-08-01", "2026-10-20T00:00:00Z", None),
        ("2026-10-20", "2026-10-20T12:00:00Z", None),
        ("2026-07-01", "2026-10-31T23:00:00Z", "6"),
    ],
)
def test_cash_months_requires_three_covered_months(tmp_path, monkeypatch, start, as_of, expected):
    office = tmp_path / "office"
    initialize(office)
    (office / "profile/accounts.json").write_text(
        json.dumps(
            {
                "accounts": [
                    {"id": "checking", "provider": "simplefin", "type": "checking", "last4": ""}
                ]
            }
        )
    )

    class Today(date):
        @classmethod
        def today(cls):
            return cls(2026, 11, 2)

    monkeypatch.setattr(market, "date", Today)
    ingest(
        office,
        "simplefin",
        [
            {
                "account_id": "checking",
                "as_of": as_of,
                "balance": {"net_value": "30000"},
                "transactions": [
                    {
                        "provider_id": f"c{i}",
                        "amount": amount,
                        "transacted_at": day,
                        "posted_date": max(day, start),
                        "description": "Hardware Store",
                    }
                    for i, (day, amount) in enumerate(
                        [
                            ("2026-07-01", "-3000"),
                            ("2026-08-01", "-3000"),
                            ("2026-09-01", "-3000"),
                            ("2026-10-01", "-9000"),
                        ],
                        1,
                    )
                ],
            }
        ],
    )
    result = metric_observations(office, "", "cash_months")
    assert (result[0]["value"] if result else None) == expected


@pytest.mark.parametrize(
    ("older_row", "expected"),
    [
        ({}, "300"),
        ({"account_id": "brokerage"}, None),
        ({"kind": "trade"}, None),
        ({"kind": "dividend"}, None),
        ({"kind": "transfer"}, None),
        ({"kind": "corporate_action"}, None),
        ({"pending": True}, None),
        ({"status": "expired"}, None),
        ({"description": "Transfer"}, None),
        ({"description": "Unknown deposit", "amount": "5000"}, None),
        ({"posted_date": "2026-07-01"}, None),
        ({"transacted_at": None}, None),
    ],
)
def test_cash_months_checks_counted_history_per_account(office, monkeypatch, older_row, expected):
    class Today(date):
        @classmethod
        def today(cls):
            return cls(2026, 9, 2)

    monkeypatch.setattr(market, "date", Today)
    state = compute.context(office, True)
    state["as_of"] = "2026-09-01T00:00:00Z"
    state["transactions"] = [
        {
            "account_id": "checking",
            "amount": "-100",
            "transacted_at": "2026-06-01",
            "description": "Hardware Store",
            **older_row,
        },
        *[
            {
                "account_id": "checking",
                "amount": "-100",
                "posted_date": day,
                "description": "Hardware Store",
            }
            for day in ("2026-07-01", "2026-08-01")
        ],
        {
            "account_id": "brokerage",
            "amount": "-10000",
            "posted_date": "2020-01-01",
            "kind": "trade",
        },
    ]
    with (office / "profile/categories.yaml").open("a") as f:
        f.write("  - pattern: Transfer\n    category: transfer\n")
    monkeypatch.setattr(compute, "context", lambda root, read_only=False: state)
    result = metric_observations(office, "", "cash_months")
    assert (result[0]["value"] if result else None) == expected


@pytest.mark.parametrize(("refund", "expected"), [("97", "30000"), ("100", None), ("101", None)])
def test_cash_months_requires_positive_outflow(office, monkeypatch, refund, expected):
    class Today(date):
        @classmethod
        def today(cls):
            return cls(2026, 9, 2)

    monkeypatch.setattr(market, "date", Today)
    state = compute.context(office, True)
    state["as_of"] = "2026-09-01T00:00:00Z"
    state["transactions"] = [
        {
            "account_id": "checking",
            "amount": amount,
            "posted_date": day,
            "description": "Hardware Store",
        }
        for day, amount in [("2026-06-01", "-100"), ("2026-07-01", refund)]
    ]
    monkeypatch.setattr(compute, "context", lambda root, read_only=False: state)
    result = metric_observations(office, "", "cash_months")
    assert (result[0]["value"] if result else None) == expected


def test_doctor_flags_accounts_without_a_role(office):
    path = office / "profile/accounts.json"
    data = json.loads(path.read_text())
    data["accounts"].append({"id": "mystery", "provider": "csv", "last4": ""})
    path.write_text(json.dumps(data))
    check = next(c for c in diagnose(office) if c["name"] == "accounts.roles")
    assert check["status"] == "warn" and "mystery" in check["reason"]


def test_holding_period_uses_the_anniversary():
    from datetime import date

    assert not compute.held_long(date(2023, 3, 1), date(2024, 3, 1))  # 366 days, leap year
    assert compute.held_long(date(2023, 3, 1), date(2024, 3, 2))
    assert not compute.held_long(date(2024, 2, 29), date(2025, 2, 28))
    assert compute.held_long(date(2024, 2, 29), date(2025, 3, 1))


def test_uncategorized_inflows_are_reported_without_netting_spend(office):
    (office / "profile/categories.yaml").write_text("rules: []\n")
    result = compute.spend(office, "2026-08")
    assert result["income"] == 0
    assert result["spend"] == Decimal(300)
    assert result["categories"] == {"needs-review": Decimal(300)}
    assert result["uncategorized_count"] == 3
    assert result["uncategorized_inflow"] == Decimal(5100)

    (office / "profile/categories.yaml").write_text(
        "rules:\n  - pattern: Payroll\n    category: income-salary\n"
    )
    result = compute.spend(office, "2026-08")
    assert result["income"] == Decimal(5000)
    assert result["spend"] == Decimal(300)
    assert result["uncategorized_count"] == 2
    assert result["uncategorized_inflow"] == Decimal(100)


def test_cashflow_marks_partial_month_and_runway_uses_complete_months(office, monkeypatch):
    class Today(date):
        @classmethod
        def today(cls):
            return cls(2026, 9, 2)

    monkeypatch.setattr(compute, "date", Today)
    monkeypatch.setattr(market, "date", Today)
    ingest(
        office,
        "simplefin",
        [
            {
                "account_id": "checking",
                "as_of": "2026-09-01T00:00:00Z",
                "balance": {"net_value": "20000"},
                "transactions": [
                    {
                        "provider_id": "history",
                        "amount": "0",
                        "transacted_at": "2026-06-01",
                    }
                ],
            }
        ],
    )
    (office / "profile/categories.yaml").write_text("rules: []\n")
    rows = compute.cashflow(office, 4, True)["months"]
    assert [row["month"] for row in rows] == ["2026-06", "2026-07", "2026-08", "2026-09"]
    assert [row["partial"] for row in rows] == [False, False, False, True]
    assert [row["uncategorized_count"] for row in rows] == [1, 0, 3, 0]
    assert [row["uncategorized_inflow"] for row in rows] == [0, 0, Decimal(5100), 0]
    assert [row["net"] for row in rows] == [0, 0, None, 0]
    assert rows[2]["income"] == 0
    assert rows[2]["spend"] == Decimal(300)

    (office / "profile/categories.yaml").write_text(
        "rules:\n  - pattern: Payroll\n    category: income-salary\n"
    )
    august = compute.cashflow(office, 4, True)["months"][2]
    assert august["uncategorized_inflow"] == Decimal(100)
    assert august["net"] is None

    (office / "profile/categories.yaml").write_text(
        "rules:\n"
        "  - pattern: Hardware\n    category: home\n"
        "  - pattern: Payroll\n    category: salary\n    income: true\n"
    )
    august = compute.cashflow(office, 4, True)["months"][2]
    assert august["uncategorized_inflow"] == 0
    assert august["net"] == Decimal(4800)

    (office / "profile/categories.yaml").write_text("rules: []\n")
    assert metric_observations(office, "", "cash_months")[0]["value"] == "300"

    # Moving back to August requires May history, which this office lacks.
    monkeypatch.setattr(Today, "today", classmethod(lambda cls: cls(2026, 8, 2)))
    assert metric_observations(office, "", "cash_months") == []


def test_cashflow_reuses_state_and_categories(office, monkeypatch):
    from unittest.mock import Mock

    class Today(date):
        @classmethod
        def today(cls):
            return cls(2026, 9, 2)

    monkeypatch.setattr(compute, "date", Today)
    expected = [compute.spend(office, f"2026-{month:02}", read_only=True) for month in range(4, 10)]
    for name in ("context", "read_state", "categorized", "load"):
        monkeypatch.setattr(compute, name, Mock(wraps=getattr(compute, name)))
    result = compute.cashflow(office, 6, read_only=True)
    compute.context.assert_called_once_with(office, True)
    compute.read_state.assert_called_once_with(office, True)
    compute.categorized.assert_called_once()
    compute.load.assert_called_once_with(office, "categories")
    for actual, monthly in zip(result["months"], expected, strict=True):
        for key in ("month", "income", "spend", "uncategorized_count"):
            assert actual[key] == monthly[key]
        assert actual["net"] == monthly["income"] - monthly["spend"]


@pytest.mark.parametrize("currency", ["EUR", "XXX", "USD", None])
def test_balance_currency_controls_totals(office, currency):
    from fo.store.index import read_state

    ingest(
        office,
        "simplefin",
        [
            {
                "account_id": "checking",
                "positions": [],
                "balance": {"net_value": "20000", "currency": currency},
            },
            {
                "account_id": "home-loan",
                "positions": [],
                "balance": {"net_value": "-80000"},
            },
        ],
    )
    non_usd = currency not in (None, "USD")
    worth = compute.networth(office)
    assert worth["non_usd_accounts"] == (["checking"] if non_usd else [])
    assert worth["total"] == (None if non_usd else Decimal(40000))
    assert compute.allocation(office)["total"] == (None if non_usd else Decimal(120000))
    registry = {"checking": {"role": "cash"}, "brokerage": {"role": "investment"}}
    assert compute.cash_holdings(read_state(office), registry) == (
        None if non_usd else Decimal(30000)
    )


@pytest.mark.parametrize("currency", ["EUR", "USD", None, "eur", "EU", "https://example.invalid"])
def test_balance_currency_validation(currency):
    from fo.errors import OfficeError
    from fo.store.records import validate

    row = {"as_of": "2026-09-12T00:00:00Z", "run_id": "r", "account_id": "a"}
    validate("balances", row)
    row["currency"] = currency
    if currency in ("EUR", "USD", None):
        validate("balances", row)
    else:
        with pytest.raises(OfficeError):
            validate("balances", row)
