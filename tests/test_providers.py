import json

import httpx
import pytest

from fo.errors import OfficeError
from fo.init import initialize
from fo.providers.simplefin import SimpleFIN


@pytest.fixture(autouse=True)
def placeholder_hostname(monkeypatch):
    monkeypatch.setattr("platform.node", lambda: "example-host")


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


def test_readonly_surface():
    from fo.providers.plaid import Plaid, PlaidAPI

    assert not any(
        hasattr(adapter, name)
        for adapter in (Plaid, PlaidAPI, SimpleFIN)
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


@pytest.mark.parametrize("currency", ["EUR", "USD", None, "https://example.invalid/currency"])
def test_simplefin_currency_is_stored(tmp_path, currency):
    from fo.store.jsonl import read_rows
    from fo.sync import ingest

    root = tmp_path / "office"
    initialize(root)
    registry = [{"id": "a", "provider": "simplefin", "provider_ref": "bridge-a", "last4": ""}]
    (root / "profile/accounts.json").write_text(json.dumps({"accounts": registry}))
    client = SimpleFIN(
        "https://u:p@bridge.example/base",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={
                    "accounts": [
                        {
                            "id": "bridge-a",
                            "balance": "15.20",
                            "balance-date": 1789200000,
                            "currency": currency,
                        }
                    ]
                },
            )
        ),
    )
    ingest(root, "simplefin", client.accounts(registry))
    row = list(read_rows(root, "data/balances.jsonl"))[0]
    assert row["currency"] == ("XXX" if currency and currency.startswith("https:") else currency)


@pytest.mark.parametrize(
    ("raw", "code"),
    [(None, None), ("USD", "USD"), (" usd", "USD"), ("eur\n", "EUR"), ("", "XXX"), ("EU", "XXX")],
)
def test_simplefin_currency_code_normalizes_iso_codes(raw, code):
    from fo.providers.simplefin import currency_code

    assert currency_code(raw) == code
