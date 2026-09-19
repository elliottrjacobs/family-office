import json
from decimal import Decimal

import pytest

from fo import compute
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


def test_cash_months_counts_bank_cash(office, monkeypatch):
    monkeypatch.setattr(
        compute,
        "cashflow",
        lambda *a, **k: {"months": [{"spend": Decimal(3000)}] * 3},
    )
    assert metric_observations(office, "", "cash_months")[0]["value"] == "10"


def test_doctor_flags_accounts_without_a_role(office):
    path = office / "profile/accounts.json"
    data = json.loads(path.read_text())
    data["accounts"].append({"id": "mystery", "provider": "csv", "last4": ""})
    path.write_text(json.dumps(data))
    check = next(c for c in diagnose(office) if c["name"] == "accounts.roles")
    assert check["status"] == "warn" and "mystery" in check["reason"]
