"""Plaid, connected with the user's own developer credentials. Read-only.

Every user brings their own Plaid client id and secret. They live in keys.toml in the
per-machine credentials folder, beside plaid-items.json, which holds one access token and
one transactions cursor per linked institution (a Plaid Item). Nothing here reaches a
server other than Plaid's API for the chosen environment, and no provider text, token or
error message is printed or stored.

Sync reads /item/get, /accounts/get (cached balances; the per-call Balance product is
not used), /investments/holdings/get and /investments/transactions/get, and
/transactions/sync. A sync's cursors are kept in memory until the run's rows are
appended, then committed, so an interrupted or failed run re-reads the same changes.
"""

import hashlib
import json
import re
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx

from fo.config import credentials_dir, read_config, read_secrets
from fo.errors import OfficeError
from fo.providers.text import local_date, untrusted_text

ENVIRONMENTS = {
    "sandbox": "https://sandbox.plaid.com",
    "production": "https://production.plaid.com",
}
API_VERSION = "2020-09-14"
ITEMS = "plaid-items.json"
# Tests set TRANSPORT to an httpx.MockTransport so no call leaves the process.
TRANSPORT = None
PAGE = 500
HISTORY_DAYS = 730
INVALID_KEYS = {"INVALID_API_KEYS", "UNAUTHORIZED_ENVIRONMENT", "INVALID_CLIENT_ID"}
ROLES = {"depository": "cash", "credit": "credit", "loan": "loan", "investment": "investment"}
DIVIDENDS = {
    "dividend",
    "qualified dividend",
    "non-qualified dividend",
    "interest",
    "long-term capital gain",
    "short-term capital gain",
}
CORPORATE = {"merger", "split", "spin off", "stock distribution"}


class PlaidError(OfficeError):
    """A Plaid API refusal. code and kind are Plaid's enums; the provider message is dropped."""

    def __init__(self, reason, message, code=None, kind=None):
        super().__init__(reason, message)
        self.code = code
        self.kind = kind

    @property
    def per_item(self):
        """An institution problem that leaves the other linked institutions usable."""
        return self.kind in {"ITEM_ERROR", "INSTITUTION_ERROR"} or self.reason == "item_error"


def failure(status, body):
    code = body.get("error_code") if isinstance(body, dict) else None
    kind = body.get("error_type") if isinstance(body, dict) else None
    code = code if isinstance(code, str) else None
    kind = kind if isinstance(kind, str) else None
    if code in INVALID_KEYS or status in (401, 403):
        return PlaidError(
            "invalid_credentials",
            "Plaid rejected the client id or secret for this environment.",
            code,
            kind,
        )
    if kind == "RATE_LIMIT_EXCEEDED" or status == 429:
        return PlaidError("rate_limited", "Plaid is rate limiting requests.", code, kind)
    if code == "PRODUCT_NOT_READY":
        return PlaidError("product_not_ready", "Plaid is still preparing this data.", code, kind)
    if kind in {"ITEM_ERROR", "INSTITUTION_ERROR"}:
        return PlaidError(
            "item_error", "A linked institution needs attention; run fo auth plaid.", code, kind
        )
    return PlaidError(
        "provider_error",
        "Plaid request failed; credentials and response details are hidden.",
        code,
        kind,
    )


def clean_credential(raw, label):
    value = (raw or "").strip()
    if not value or len(value) > 128 or not value.isprintable() or any(c.isspace() for c in value):
        raise OfficeError("invalid_credentials", f"Enter the Plaid {label} from your dashboard.")
    return value


class PlaidAPI:
    """POSTs to one Plaid environment with the credentials in headers, never in a body."""

    def __init__(self, client_id, secret, environment, transport=None):
        if environment not in ENVIRONMENTS:
            raise OfficeError("invalid_credentials", "Plaid environment is sandbox or production.")
        self.environment = environment
        self._base = ENVIRONMENTS[environment]
        self._headers = {
            "PLAID-CLIENT-ID": clean_credential(client_id, "client ID"),
            "PLAID-SECRET": clean_credential(secret, "secret"),
            "Plaid-Version": API_VERSION,
        }
        self._transport = transport

    def post(self, path, body):
        try:
            with httpx.Client(
                timeout=60,
                follow_redirects=False,
                trust_env=False,
                transport=self._transport or TRANSPORT,
            ) as client:
                response = client.post(self._base + path, json=body, headers=self._headers)
        except httpx.HTTPError as exc:
            raise OfficeError("provider_unreachable", "Plaid could not be reached.") from exc
        try:
            # Decimal keeps amounts exact from the wire to the canonical rows.
            data = json.loads(response.content, parse_float=Decimal)
        except ValueError:
            data = None
        if response.status_code >= 400 or not isinstance(data, dict):
            raise failure(response.status_code, data)
        return data


def api_for(root):
    settings = read_secrets(root).get("plaid", {})
    if not settings.get("client_id") or not settings.get("secret"):
        raise OfficeError("missing_credentials", "Run fo auth plaid locally.")
    return PlaidAPI(
        settings["client_id"], settings["secret"], settings.get("environment", "sandbox")
    )


def load_items(root):
    path = credentials_dir(root) / ITEMS
    if not path.exists():
        return []
    try:
        items = json.loads(path.read_text()).get("items")
        if not isinstance(items, list) or not all(
            isinstance(i, dict)
            and isinstance(i.get("item_id"), str)
            and isinstance(i.get("access_token"), str)
            for i in items
        ):
            raise ValueError("malformed")
        return items
    except (OSError, ValueError, AttributeError) as exc:
        raise OfficeError(
            "invalid_secrets", "The Plaid items file is unreadable or malformed."
        ) from exc


def save_items(root, items):
    from fo.auth import save_secret_json

    save_secret_json(root, ITEMS.removesuffix(".json"), {"items": items})


def negate(value):
    """Plaid amounts are positive when money leaves the account; the office's are negative."""
    return str(0 - Decimal(str(value)))


def number(value):
    return None if value is None else str(Decimal(str(value)))


def currency(record):
    """ISO code, XXX for Plaid's unofficial codes (crypto and the like), or None."""
    code = record.get("iso_currency_code")
    if isinstance(code, str) and re.fullmatch(r"[A-Z]{3}", code.strip().upper()):
        return code.strip().upper()
    return "XXX" if code or record.get("unofficial_currency_code") else None


def discovered(accounts):
    """Registry identities: Plaid's opaque account id, the mask, and the account kind."""
    result = []
    for account in accounts:
        mask = account.get("mask") or ""
        result.append(
            {
                "provider_ref": str(account["account_id"]),
                "last4": mask if re.fullmatch(r"\d{0,4}", mask) else "",
                "type": str(account.get("subtype") or account.get("type") or ""),
                "role": ROLES.get(account.get("type")),
            }
        )
    return result


def balance(account, cash=None):
    values = account.get("balances") or {}
    current = values.get("current")
    result = {"currency": currency(values)}
    if account.get("type") in {"credit", "loan"}:
        # Plaid reports what is owed as a positive balance.
        result["net_value"] = negate(current) if current is not None else None
        result["debt"] = number(current)
    else:
        result["net_value"] = number(current)
    if cash is not None:
        result["cash"] = str(cash)
    return result


def normalize_transaction(tx):
    pending = bool(tx.get("pending"))
    row = {
        "provider_id": str(tx["transaction_id"]),
        "amount": negate(tx["amount"]),
        "transacted_at": local_date(tx.get("authorized_date") or tx.get("date")),
        "posted_date": None if pending else local_date(tx.get("date")),
        "description": untrusted_text(tx.get("name") or tx.get("original_description") or ""),
        "payee": untrusted_text(tx.get("merchant_name")),
        "memo": None,
        "pending": pending,
    }
    if tx.get("pending_transaction_id"):
        # The posted transaction that replaces a pending one keeps its office identity.
        row["replaces"] = str(tx["pending_transaction_id"])
    return row


def symbol_for(security, security_id):
    for key in ("ticker_symbol", "cusip", "isin"):
        if security.get(key):
            return str(security[key])
    return "plaid:" + str(security_id)


def is_cash(security):
    return bool(security.get("is_cash_equivalent")) or security.get("type") == "cash"


def holdings_by_account(body):
    """Positions per account, with cash-equivalent holdings folded into a cash total."""
    securities = {s["security_id"]: s for s in body.get("securities") or []}
    result = {}
    for holding in body.get("holdings") or []:
        positions, cash = result.setdefault(holding["account_id"], ([], [Decimal(0)]))
        security = securities.get(holding["security_id"], {})
        if is_cash(security):
            cash[0] += Decimal(str(holding.get("institution_value") or 0))
            continue
        positions.append(
            {
                "symbol": symbol_for(security, holding["security_id"]),
                "qty": number(holding.get("quantity")),
                "price": number(holding.get("institution_price")),
                "value": number(holding.get("institution_value")),
                "cost_basis": number(holding.get("cost_basis")),
            }
        )
    return {key: (positions, cash[0]) for key, (positions, cash) in result.items()}


def investment_kind(tx):
    kind, subtype = tx.get("type"), (tx.get("subtype") or "").lower()
    if kind in {"buy", "sell"}:
        return "trade"
    if kind == "cash":
        return "dividend" if subtype in DIVIDENDS else "transfer"
    if kind == "fee":
        return "fee"
    if kind == "transfer":
        return "corporate_action" if subtype in CORPORATE else "transfer"
    return "other"


def normalize_investment_transaction(tx, securities):
    security = securities.get(tx.get("security_id")) or {}
    row = {
        "provider_id": str(tx["investment_transaction_id"]),
        # Position-only activity, such as a transfer in kind, has no cash amount.
        "amount": negate(tx["amount"]) if tx.get("amount") is not None else "0",
        "transacted_at": local_date(tx.get("date")),
        "posted_date": local_date(tx.get("date")),
        "description": untrusted_text(tx.get("name") or ""),
        "kind": investment_kind(tx),
        "pending": False,
    }
    if tx.get("security_id") and not is_cash(security):
        row["symbol"] = symbol_for(security, tx["security_id"])
        row["asset_type"] = security.get("type") or None
    for key, source in (("qty", "quantity"), ("price", "price"), ("fees", "fees")):
        if tx.get(source) is not None:
            row[key] = number(abs(Decimal(str(tx[source]))) if key == "fees" else tx[source])
    return row


def client_user_id(root):
    """A stable, non-identifying id for the office's one Plaid end user."""
    office = str(read_config(root).get("office", {}).get("id", ""))
    return hashlib.sha256(("family-office:" + office).encode()).hexdigest()[:32]


def create_link_token(api, root, brokerage=False, access_token=None):
    body = {
        "client_name": "Family Office",
        "language": "en",
        "country_codes": ["US"],
        "user": {"client_user_id": client_user_id(root)},
    }
    if access_token:
        # Update mode repairs an Item's login; it takes no products.
        body["access_token"] = access_token
    else:
        first, second = (
            ("investments", "transactions") if brokerage else ("transactions", "investments")
        )
        body["products"] = [first]
        body["optional_products"] = [second]
        body["transactions"] = {"days_requested": HISTORY_DAYS}
    token = api.post("/link/token/create", body).get("link_token")
    if not isinstance(token, str) or not token.startswith("link-"):
        raise OfficeError("provider_error", "Plaid did not return a Link token.")
    return token


class Plaid:
    def __init__(self, root, api=None, timezone=UTC):
        self._root = root
        self._api = api or api_for(root)
        self._timezone = timezone
        self._items = load_items(root)
        if not self._items:
            raise OfficeError(
                "missing_credentials", "No Plaid institutions are linked; run fo auth plaid."
            )
        self.error_count = 0
        self.unmapped_accounts = 0
        self.cursors = {}

    def accounts(self, registry, full=False):
        self.error_count = 0
        self.unmapped_accounts = 0
        self.cursors = {}
        end = datetime.now(UTC).astimezone(self._timezone).date()
        start = end - timedelta(days=90 if full else 30)
        result = []
        for item in self._items:
            try:
                rows, cursor = self._item(item, registry, start, end)
            except PlaidError as exc:
                if not exc.per_item:
                    raise
                # One broken institution must not block the rest; its accounts surface as stale.
                self.error_count += 1
                continue
            result.extend(rows)
            if cursor is not None:
                self.cursors[item["item_id"]] = cursor
        return result

    def commit(self):
        """Persist the cursors of a run whose rows were appended."""
        if not self.cursors:
            return
        items = load_items(self._root)
        for item in items:
            if item["item_id"] in self.cursors:
                item["cursor"] = self.cursors[item["item_id"]]
        save_items(self._root, items)

    def _item(self, item, registry, start, end):
        token = item["access_token"]
        details = self._api.post("/item/get", {"access_token": token}).get("item") or {}
        if details.get("error"):
            raise PlaidError("item_error", "A linked institution needs attention.")
        products = set(details.get("products") or [])
        mapped = {}
        for account in self._api.post("/accounts/get", {"access_token": token})["accounts"]:
            matches = [r for r in registry if r.get("provider_ref") == account["account_id"]]
            if not matches:
                self.unmapped_accounts += 1
                continue
            if len(matches) > 1:
                raise OfficeError(
                    "ambiguous_account",
                    "Plaid returned an ambiguously mapped account; update the account registry.",
                )
            mapped[account["account_id"]] = (matches[0]["id"], account)
        if not mapped:
            return [], None
        holdings, ready, trades = {}, True, {}
        if "investments" in products and any(
            a.get("type") == "investment" for _, a in mapped.values()
        ):
            try:
                holdings = holdings_by_account(
                    self._api.post("/investments/holdings/get", {"access_token": token})
                )
            except PlaidError as exc:
                if exc.reason != "product_not_ready":
                    raise
                ready = False
            trades = self._investment_transactions(token, start, end)
        changes, removed, cursor = {}, {}, None
        if "transactions" in products:
            changes, removed, cursor = self._sync(token, item.get("cursor") or "")
        rows = []
        for plaid_id, (account_id, account) in mapped.items():
            investment = account.get("type") == "investment"
            positions, cash = holdings.get(plaid_id, ([], None if not holdings else Decimal(0)))
            row = {
                "account_id": account_id,
                "positions": positions,
                "balance": balance(account, cash if investment else None),
                "transactions": [
                    normalize_transaction(tx)
                    for tx in changes.values()
                    if tx["account_id"] == plaid_id
                ]
                + trades.get(plaid_id, []),
                "removed_provider_ids": sorted(removed.get(plaid_id, set())),
            }
            if investment and not ready:
                # Holdings are still being prepared: keep the last snapshot, take only activity.
                row["snapshot"] = False
            rows.append(row)
        return rows, cursor

    def _investment_transactions(self, token, start, end):
        result, offset = {}, 0
        while True:
            try:
                body = self._api.post(
                    "/investments/transactions/get",
                    {
                        "access_token": token,
                        "start_date": start.isoformat(),
                        "end_date": end.isoformat(),
                        "options": {"count": PAGE, "offset": offset},
                    },
                )
            except PlaidError as exc:
                if exc.reason == "product_not_ready":
                    return result
                raise
            securities = {s["security_id"]: s for s in body.get("securities") or []}
            page = body.get("investment_transactions") or []
            for tx in page:
                result.setdefault(tx["account_id"], []).append(
                    normalize_investment_transaction(tx, securities)
                )
            offset += len(page)
            if not page or offset >= int(body.get("total_investment_transactions") or 0):
                return result

    def _sync(self, token, cursor):
        """Every change since cursor; restarts when Plaid's data moves mid-pagination."""
        for _ in range(3):
            changes, removed, position = {}, {}, cursor
            while True:
                request = {"access_token": token, "count": PAGE}
                if position:
                    request["cursor"] = position
                try:
                    page = self._api.post("/transactions/sync", request)
                except PlaidError as exc:
                    if exc.code == "TRANSACTIONS_SYNC_MUTATION_DURING_PAGINATION":
                        break
                    raise
                for tx in [*(page.get("added") or []), *(page.get("modified") or [])]:
                    changes[str(tx["transaction_id"])] = tx
                for gone in page.get("removed") or []:
                    tx_id = str(gone["transaction_id"])
                    changes.pop(tx_id, None)
                    if gone.get("account_id"):
                        removed.setdefault(gone["account_id"], set()).add(tx_id)
                position = page.get("next_cursor") or position
                if not page.get("has_more"):
                    return changes, removed, position
        raise OfficeError(
            "provider_error", "Plaid transactions kept changing during sync; try again."
        )


def discover(root, api=None):
    """Register the accounts of every linked Item; False when none is linked yet."""
    from fo.accounts import register

    items = load_items(root)
    if not items:
        return False
    api = api or api_for(root)
    found = []
    for item in items:
        found += discovered(
            api.post("/accounts/get", {"access_token": item["access_token"]}).get("accounts") or []
        )
    register(root, "plaid", found)
    return True


def connect(root, keys, prompt, confirm, link, announce=None):
    """fo auth plaid: the user's own credentials, then repair or link institutions.

    Credentials are asked for once and saved only after Plaid accepts them for a Link
    token. Items that report an error are offered Link's update mode first, which repairs
    the login without using another Item. The access token is saved before accounts are
    registered, so a registry problem never strands a linked institution.
    """
    from fo.accounts import register
    from fo.auth import save_keys

    settings = dict(keys.get("plaid") or {})
    fresh = not (settings.get("client_id") and settings.get("secret"))
    if fresh:
        settings["client_id"] = clean_credential(
            prompt("Plaid client ID", hide_input=True), "client ID"
        )
        settings["secret"] = clean_credential(prompt("Plaid secret", hide_input=True), "secret")
        settings["environment"] = (
            str(prompt("Plaid environment (sandbox or production)", default="sandbox"))
            .strip()
            .lower()
        )
    api = PlaidAPI(settings["client_id"], settings["secret"], settings.get("environment"))
    items = load_items(root)
    repaired = 0
    for item in items:
        try:
            broken = bool(
                (
                    api.post("/item/get", {"access_token": item["access_token"]}).get("item") or {}
                ).get("error")
            )
        except PlaidError as exc:
            if not exc.per_item:
                raise
            broken = True
        name = item.get("institution") or "A linked institution"
        if broken and confirm(f"{name} needs attention. Reconnect it now?", default=True):
            token = create_link_token(api, root, access_token=item["access_token"])
            link(token, api.environment, announce=announce)
            repaired += 1
    if items and not confirm("Link another institution?", default=not repaired):
        return {"provider": "plaid", "authenticated": True, "repaired": repaired, "linked": 0}
    kind = str(prompt("Institution kind (bank or brokerage)", default="bank")).strip().lower()
    if kind not in {"bank", "brokerage"}:
        raise OfficeError("invalid_request", "Answer bank or brokerage.")
    token = create_link_token(api, root, brokerage=kind == "brokerage")
    if fresh:
        keys["plaid"] = settings
        save_keys(root, keys)
    session = link(token, api.environment, announce=announce)
    exchange = api.post("/item/public_token/exchange", {"public_token": session["public_token"]})
    access, item_id = exchange.get("access_token"), exchange.get("item_id")
    if not isinstance(access, str) or not isinstance(item_id, str):
        raise OfficeError("provider_error", "Plaid did not return an access token.")
    duplicate = bool(session["institution_id"]) and any(
        i.get("institution_id") == session["institution_id"] for i in items
    )
    items = [i for i in load_items(root) if i["item_id"] != item_id]
    items.append(
        {
            "item_id": item_id,
            "access_token": access,
            "institution": session["institution"],
            "institution_id": session["institution_id"],
            "cursor": "",
        }
    )
    save_items(root, items)
    accounts = api.post("/accounts/get", {"access_token": access}).get("accounts") or []
    assigned = register(root, "plaid", discovered(accounts))
    return {
        "provider": "plaid",
        "authenticated": True,
        "repaired": repaired,
        "linked": 1,
        "accounts": len(assigned),
        "duplicate_institution": duplicate,
    }
