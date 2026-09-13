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
