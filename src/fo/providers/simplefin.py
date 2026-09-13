import time
from datetime import UTC, datetime
from urllib.parse import unquote, urlsplit, urlunsplit

import httpx

from fo.errors import OfficeError
from fo.providers.text import untrusted_text


class SimpleFIN:
    def __init__(self, access_url, transport=None):
        parts = urlsplit(access_url)
        if (
            parts.scheme != "https"
            or not parts.hostname
            or not parts.username
            or not parts.password
        ):
            raise OfficeError(
                "invalid_credentials", "SimpleFIN requires an HTTPS access URL with credentials."
            )
        self._auth = (unquote(parts.username), unquote(parts.password))
        host = parts.hostname + (f":{parts.port}" if parts.port else "")
        self._base = urlunsplit(("https", host, parts.path.rstrip("/"), "", ""))
        self._transport = transport

    def accounts(self, registry, full=False):
        params = {"start-date": int(time.time()) - (90 if full else 30) * 86400, "pending": 1}
        try:
            body = self._fetch(params)
            result = []
            for item in body.get("accounts", []):
                matches = [a for a in registry if a.get("provider_ref") == item["id"]]
                if len(matches) != 1:
                    raise OfficeError(
                        "unmapped_account",
                        "SimpleFIN returned an unmapped account; update the account registry.",
                    )
                transactions = []
                for tx in item.get("transactions", []):
                    stamp = tx.get("transacted_at") or tx.get("posted")
                    transactions.append(
                        {
                            "provider_id": str(tx["id"]),
                            "amount": tx["amount"],
                            "transacted_at": datetime.fromtimestamp(stamp, UTC).date().isoformat()
                            if stamp
                            else None,
                            "posted_date": datetime.fromtimestamp(tx["posted"], UTC)
                            .date()
                            .isoformat()
                            if tx.get("posted")
                            else None,
                            "description": untrusted_text(tx.get("description", "")),
                            "payee": untrusted_text(tx.get("payee")),
                            "memo": untrusted_text(tx.get("memo")),
                            "pending": bool(tx.get("pending")),
                        }
                    )
                result.append(
                    {
                        "account_id": matches[0]["id"],
                        "as_of": datetime.fromtimestamp(item["balance-date"], UTC)
                        .isoformat()
                        .replace("+00:00", "Z"),
                        "positions": [],
                        "balance": {"net_value": item["balance"]},
                        "transactions": transactions,
                        "transaction_window": {
                            "start": datetime.fromtimestamp(params["start-date"], UTC)
                            .date()
                            .isoformat(),
                            "end": datetime.now(UTC).date().isoformat(),
                        },
                    }
                )
            return result
        except OfficeError:
            raise
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            raise OfficeError(
                "provider_error",
                "SimpleFIN request failed; credentials and response details are hidden.",
            ) from exc

    def _fetch(self, params):
        try:
            with httpx.Client(
                timeout=60, follow_redirects=False, trust_env=False, transport=self._transport
            ) as client:
                response = client.get(self._base + "/accounts", auth=self._auth, params=params)
                response.raise_for_status()
                body = response.json()
            if (
                not isinstance(body, dict)
                or body.get("errors")
                or not isinstance(body.get("accounts"), list)
            ):
                raise ValueError("incomplete response")
            return body
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            raise OfficeError(
                "provider_error", "SimpleFIN could not return complete account data."
            ) from exc

    def discover(self):
        body = self._fetch({"balances-only": 1})
        try:
            return [{"provider_ref": str(item["id"]), "last4": ""} for item in body["accounts"]]
        except (KeyError, TypeError) as exc:
            raise OfficeError("provider_error", "SimpleFIN account discovery failed.") from exc
