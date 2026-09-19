import json

import httpx
import pytest

from fo.errors import OfficeError
from fo.init import initialize
from fo.providers.schwab import normalize_accounts
from fo.providers.simplefin import SimpleFIN


def test_simplefin_uses_get_and_keeps_credentials_out_of_url():
    seen = []

    def response(request):
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "accounts": [
                    {
                        "id": "bridge-a",
                        "balance": "15.20",
                        "balance-date": 1789200000,
                        "transactions": [],
                    }
                ],
                "errors": [],
            },
        )

    client = SimpleFIN(
        "https://user:SECRET@bridge.example/accounts-base", transport=httpx.MockTransport(response)
    )
    rows = client.accounts([{"id": "a", "provider_ref": "bridge-a", "last4": "1234"}])
    assert rows[0]["account_id"] == "a"
    assert rows[0]["balance"]["net_value"] == "15.20"
    assert seen[0].method == "GET"
    assert "SECRET" not in str(seen[0].url)
    assert seen[0].headers["authorization"].startswith("Basic ")


def test_simplefin_error_never_contains_payload_or_credentials():
    client = SimpleFIN(
        "https://user:SECRET@bridge.example/base",
        transport=httpx.MockTransport(lambda req: httpx.Response(500, text="SECRET 123456789")),
    )
    with pytest.raises(OfficeError) as caught:
        client.accounts([])
    assert "SECRET" not in str(caught.value)
    assert "123456789" not in str(caught.value)


def test_schwab_normalization_short_money_market_and_unmapped():
    raw = [
        {
            "securitiesAccount": {
                "accountNumber": "123456789",
                "currentBalances": {"liquidationValue": 90, "cashBalance": 100},
                "positions": [
                    {
                        "instrument": {"symbol": "ACME", "assetType": "EQUITY"},
                        "shortQuantity": 1,
                        "marketValue": -10,
                        "averageShortPrice": 12,
                    }
                ],
            }
        }
    ]
    registry = [{"id": "a", "last4": "6789", "provider": "schwab"}]
    result = normalize_accounts(raw, registry)
    assert result[0]["positions"][0]["qty"] == "-1"
    assert "123456789" not in json.dumps(result)
    with pytest.raises(OfficeError, match="unmapped"):
        normalize_accounts(raw, [])


def test_readonly_surface():
    from fo.providers.schwab import Schwab

    assert not any(
        hasattr(Schwab, name) or hasattr(SimpleFIN, name)
        for name in (
            "place_order",
            "replace_order",
            "cancel_order",
            "transfer",
            "withdraw",
            "deposit",
        )
    )


def test_sync_wrong_writer_and_offline_failure(tmp_path):
    from tests.test_foundation import fo

    root = tmp_path / "office"
    initialize(root)
    settings = root / "office.toml"
    import platform

    settings.write_text(settings.read_text().replace(platform.node(), "not-this-machine"))
    result = fo("sync", "--office", root, "--json")
    assert result.returncode != 0
    assert json.loads(result.stdout)["reason"] == "not_writer"
    assert (root / "data/sync_log.jsonl").read_text() == ""


def test_simplefin_institution_error_keeps_healthy_accounts():
    body = {
        "accounts": [
            {"id": "bridge-a", "balance": "15.20", "balance-date": 1789200000, "transactions": []}
        ],
        "errors": ["Connection to Example Bank needs attention SECRET"],
    }
    client = SimpleFIN(
        "https://user:SECRET@bridge.example/base",
        transport=httpx.MockTransport(lambda req: httpx.Response(200, json=body)),
    )
    rows = client.accounts([{"id": "a", "provider_ref": "bridge-a", "last4": ""}])
    assert [r["account_id"] for r in rows] == ["a"]
    assert client.error_count == 1
    empty = SimpleFIN(
        "https://user:SECRET@bridge.example/base",
        transport=httpx.MockTransport(
            lambda req: httpx.Response(200, json={"accounts": [], "errors": ["down"]})
        ),
    )
    with pytest.raises(OfficeError):
        empty.accounts([])


def test_schwab_transaction_keeps_trade_detail_in_office_time():
    from zoneinfo import ZoneInfo

    from fo.providers.schwab import normalize_transaction

    row = normalize_transaction(
        {
            "activityId": 42,
            "accountNumber": "123456789",
            "type": "TRADE",
            "status": "VALID",
            "tradeDate": "2026-09-02T01:30:00+0000",
            "settlementDate": "2026-09-03T04:00:00+0000",
            "netAmount": -1001.5,
            "transferItems": [
                {"instrument": {"assetType": "CURRENCY"}, "amount": -1001.5},
                {"feeType": "COMMISSION", "cost": -1.5, "instrument": {"assetType": "CURRENCY"}},
                {
                    "instrument": {"symbol": "ACME", "assetType": "EQUITY"},
                    "amount": 10,
                    "price": 100,
                },
            ],
        },
        ZoneInfo("America/New_York"),
    )
    assert row["transacted_at"] == "2026-09-01"
    assert (row["kind"], row["symbol"], row["qty"], row["price"], row["fees"]) == (
        "trade",
        "ACME",
        "10",
        "100",
        "1.5",
    )
    assert "123456789" not in json.dumps(row)


def test_schwab_option_price_is_per_share():
    raw = [
        {
            "securitiesAccount": {
                "accountNumber": "123456789",
                "currentBalances": {"liquidationValue": 500, "cashBalance": 0},
                "positions": [
                    {
                        "instrument": {"symbol": "ACME 270115C00100000", "assetType": "OPTION"},
                        "longQuantity": 2,
                        "marketValue": 500,
                    }
                ],
            }
        }
    ]
    result = normalize_accounts(raw, [{"id": "a", "last4": "6789", "provider": "schwab"}])
    assert result[0]["positions"][0]["price"] == "2.5"


def test_simplefin_dates_use_office_timezone():
    from zoneinfo import ZoneInfo

    body = {
        "accounts": [
            {
                "id": "bridge-a",
                "balance": "1",
                "balance-date": 1789200000,
                "transactions": [
                    {"id": "t", "amount": "-5", "posted": 1788222600, "description": "Cafe"}
                ],
            }
        ]
    }
    client = SimpleFIN(
        "https://user:SECRET@bridge.example/base",
        transport=httpx.MockTransport(lambda req: httpx.Response(200, json=body)),
        timezone=ZoneInfo("America/New_York"),
    )
    tx = client.accounts([{"id": "a", "provider_ref": "bridge-a", "last4": ""}])[0]["transactions"]
    # 2026-09-01T00:30Z is still 31 August in New York.
    assert tx[0]["posted_date"] == "2026-08-31"
