from datetime import UTC, datetime, timedelta
from decimal import Decimal

from fo.config import load_json, read_secrets
from fo.errors import OfficeError
from fo.office import contained, write_json


def normalize_accounts(body, registry):
    result = []
    for item in body:
        account = item["securitiesAccount"]
        suffix = str(account["accountNumber"])[-4:]
        matches = [a for a in registry if a.get("last4") == suffix]
        if len(matches) != 1:
            raise OfficeError(
                "unmapped_account",
                "Schwab returned an unmapped account; update the account registry.",
            )
        positions, money_market = [], Decimal(0)
        for p in account.get("positions", []):
            instrument = p["instrument"]
            symbol = instrument.get("symbol", "")
            if symbol in {"SWVXX", "SNVXX", "SNOXX", "SNSXX", "SWGXX"}:
                money_market += Decimal(str(p["marketValue"]))
                continue
            qty = Decimal(str(p.get("longQuantity", 0))) - Decimal(str(p.get("shortQuantity", 0)))
            value = Decimal(str(p["marketValue"])) if p.get("marketValue") is not None else None
            basis = next(
                (
                    p[k]
                    for k in ("averagePrice", "averageLongPrice", "averageShortPrice")
                    if p.get(k) is not None
                ),
                None,
            )
            positions.append(
                {
                    "symbol": symbol,
                    "qty": str(qty),
                    "price": str(value / qty) if qty and value is not None else None,
                    "value": str(value) if value is not None else None,
                    "cost_basis": str(Decimal(str(basis)) * qty) if basis is not None else None,
                }
            )
        balances = account.get("currentBalances", {})
        result.append(
            {
                "account_id": matches[0]["id"],
                "positions": positions,
                "balance": {
                    "net_value": balances.get("liquidationValue", balances.get("accountValue")),
                    "cash": str(Decimal(str(balances["cashBalance"])) + money_market)
                    if balances.get("cashBalance") is not None
                    else None,
                },
                "transactions": [],
            }
        )
    return result


class Schwab:
    def __init__(self, root, client=None):
        self._root = root
        if client is not None:
            self._client = client
            return
        settings = read_secrets(root).get("schwab", {})
        path = contained(root, "secrets/schwab-token.json")
        if not settings.get("app_key") or not settings.get("app_secret") or not path.is_file():
            raise OfficeError("missing_credentials", "Run fo auth schwab locally.")
        saved = load_json(path)
        expiry = saved.get("refresh_token_expires_at")
        if not expiry or datetime.fromisoformat(expiry.replace("Z", "+00:00")) <= datetime.now(UTC):
            raise OfficeError("token_expired", "Schwab refresh token expired; run fo auth schwab.")
        import schwab.auth

        def persist(token, *args, **kwargs):
            write_json(path, {**token, "refresh_token_expires_at": expiry}, 0o600)

        self._client = schwab.auth.client_from_access_functions(
            settings["app_key"], settings["app_secret"], lambda: saved, persist, enforce_enums=False
        )

    def discover(self):
        from fo.auth import register_schwab

        try:
            response = self._client.get_account_numbers()
            response.raise_for_status()
            register_schwab(self._root, response.json(), read_secrets(self._root))
        except OfficeError:
            raise
        except Exception as exc:
            raise OfficeError("provider_error", "Schwab account discovery failed.") from exc

    def accounts(self, registry, full=False):
        try:
            response = self._client.get_accounts(fields="positions")
            response.raise_for_status()
            normalized = normalize_accounts(response.json(), registry)
            hashes = read_secrets(self._root).get("schwab", {}).get("account_hashes", {})
            for account in normalized:
                account_hash = hashes.get(account["account_id"])
                if not account_hash:
                    raise OfficeError(
                        "missing_account_mapping",
                        "Schwab account hash mapping is missing; run fo auth schwab.",
                    )
                end = datetime.now(UTC)
                account["transaction_window"] = {
                    "start": (end - timedelta(days=90 if full else 30)).date().isoformat(),
                    "end": end.date().isoformat(),
                }
                response = self._client.get_transactions(
                    account_hash, start_date=end - timedelta(days=90 if full else 30), end_date=end
                )
                response.raise_for_status()
                for tx in response.json():
                    account["transactions"].append(
                        {
                            "provider_id": str(tx["activityId"]),
                            "amount": tx.get("netAmount", 0),
                            "transacted_at": tx.get("tradeDate", tx.get("transactionDate", ""))[
                                :10
                            ],
                            "posted_date": tx.get("settlementDate", "")[:10],
                            "description": str(tx.get("type", "")),
                            "pending": tx.get("status") == "PENDING",
                        }
                    )
            return normalized
        except OfficeError:
            raise
        except Exception as exc:
            raise OfficeError(
                "provider_error",
                "Schwab request failed; credentials and response details are hidden.",
            ) from exc

    def quote(self, symbols):
        try:
            response = self._client.get_quotes(symbols)
            response.raise_for_status()
            return response.json()
        except Exception as exc:
            raise OfficeError("provider_error", "Schwab quote request failed.") from exc
