"""Plaid with synthetic fixtures only: a fake Plaid API behind httpx.MockTransport."""

import json
import stat
import threading
from decimal import Decimal

import httpx
import pytest

from fo.auth import save_keys
from fo.config import credentials_dir, ensure_credentials, public_config
from fo.errors import OfficeError
from fo.init import initialize
from fo.office import git
from fo.providers import plaid
from fo.providers.plaid import Plaid, PlaidAPI, load_items, save_items
from fo.store.index import project
from fo.sync import synchronize

CLIENT = "CLIENT_SENTINEL"
SECRET = "SECRET_SENTINEL"
ACCESS = "access-sandbox-ACCESS_SENTINEL"
OTHER = "access-sandbox-OTHER_SENTINEL"
PUBLIC = "public-sandbox-PUBLIC_SENTINEL"


def bank_accounts():
    return [
        {
            "account_id": "acc-checking",
            "mask": "0000",
            "type": "depository",
            "subtype": "checking",
            "balances": {"current": 1250.5, "available": 1200, "iso_currency_code": "USD"},
        },
        {
            "account_id": "acc-card",
            "mask": "3333",
            "type": "credit",
            "subtype": "credit card",
            "balances": {"current": 410.25, "limit": 2000, "iso_currency_code": "USD"},
        },
    ]


def broker_accounts():
    return [
        {
            "account_id": "acc-ira",
            "mask": "5555",
            "type": "investment",
            "subtype": "ira",
            "balances": {"current": 23631.98, "iso_currency_code": "USD"},
        }
    ]


SECURITIES = [
    {"security_id": "sec-acme", "ticker_symbol": "ACME", "type": "equity"},
    {
        "security_id": "sec-mmf",
        "ticker_symbol": "MMFXX",
        "type": "cash",
        "is_cash_equivalent": True,
    },
    {
        "security_id": "sec-bond",
        "ticker_symbol": None,
        "cusip": "912828XX1",
        "type": "fixed income",
    },
]


class FakePlaid:
    """A synthetic Plaid sandbox. Pages of /transactions/sync are keyed by cursor."""

    def __init__(self):
        self.requests = []
        self.items = {
            ACCESS: {"products": ["transactions"], "accounts": bank_accounts()},
            OTHER: {"products": ["investments"], "accounts": broker_accounts()},
        }
        self.errors = {}
        self.pages = {
            "": {
                "added": [
                    tx("tx-coffee", "acc-checking", 4.5, "COFFEE SHOP", pending=True),
                    tx("tx-pay", "acc-checking", -2000, "PAYROLL"),
                    tx("tx-card", "acc-card", 60, "GROCER"),
                ],
                "modified": [],
                "removed": [],
                "next_cursor": "c1",
                "has_more": True,
            },
            "c1": {
                "added": [tx("tx-dropped", "acc-checking", 9, "HOLD", pending=True)],
                "modified": [],
                "removed": [],
                "next_cursor": "CURSOR_SENTINEL_2",
                "has_more": False,
            },
        }
        self.mutations = 0
        self.not_ready = False

    def __call__(self, request):
        body = json.loads(request.content)
        self.requests.append((request.url.path, dict(request.headers), body))
        path = request.url.path
        token = body.get("access_token")
        if (
            request.headers.get("plaid-client-id") != CLIENT
            or request.headers.get("plaid-secret") != SECRET
        ):
            return httpx.Response(
                400,
                json={
                    "error_type": "INVALID_INPUT",
                    "error_code": "INVALID_API_KEYS",
                    "error_message": "bad keys " + SECRET,
                },
            )
        if token in self.errors and path != "/link/token/create":
            return httpx.Response(400, json=self.errors[token])
        if path == "/link/token/create":
            return httpx.Response(200, json={"link_token": "link-sandbox-TOKEN"})
        if path == "/item/public_token/exchange":
            assert body["public_token"] == PUBLIC
            return httpx.Response(200, json={"access_token": ACCESS, "item_id": "item-bank"})
        if path == "/item/get":
            item = self.items[token]
            return httpx.Response(
                200, json={"item": {"products": item["products"], "error": item.get("error")}}
            )
        if path == "/accounts/get":
            return httpx.Response(200, json={"accounts": self.items[token]["accounts"]})
        if path == "/investments/holdings/get":
            if self.not_ready:
                return httpx.Response(
                    400, json={"error_type": "ITEM_ERROR", "error_code": "PRODUCT_NOT_READY"}
                )
            return httpx.Response(
                200,
                json={
                    "accounts": broker_accounts(),
                    "securities": SECURITIES,
                    "holdings": [
                        holding("sec-acme", 10, 101.25, 1012.5, 900),
                        holding("sec-mmf", 619.48, 1, 619.48, 619.48),
                        holding("sec-bond", 22000, 1, 22000, 21800),
                    ],
                },
            )
        if path == "/investments/transactions/get":
            return httpx.Response(
                200,
                json={
                    "securities": SECURITIES,
                    "investment_transactions": [
                        {
                            "investment_transaction_id": "inv-buy",
                            "account_id": "acc-ira",
                            "security_id": "sec-acme",
                            "date": "2026-11-02",
                            "name": "BUY ACME",
                            "quantity": 2,
                            "price": 100,
                            "amount": 200.95,
                            "fees": 0.95,
                            "type": "buy",
                            "subtype": "buy",
                        },
                        {
                            "investment_transaction_id": "inv-div",
                            "account_id": "acc-ira",
                            "security_id": "sec-acme",
                            "date": "2026-11-03",
                            "name": "ACME DIVIDEND",
                            "quantity": 0,
                            "amount": -3.1,
                            "type": "cash",
                            "subtype": "qualified dividend",
                        },
                    ],
                    "total_investment_transactions": 2,
                },
            )
        if path == "/transactions/sync":
            if self.mutations:
                self.mutations -= 1
                return httpx.Response(
                    400,
                    json={
                        "error_type": "TRANSACTIONS_ERROR",
                        "error_code": "TRANSACTIONS_SYNC_MUTATION_DURING_PAGINATION",
                    },
                )
            cursor = body.get("cursor", "")
            empty = {"added": [], "modified": [], "removed": [], "next_cursor": cursor}
            return httpx.Response(200, json=self.pages.get(cursor, {**empty, "has_more": False}))
        return httpx.Response(404, json={"error_type": "INVALID_REQUEST"})


def tx(tx_id, account, amount, name, pending=False, replaces=None, day="2026-11-10"):
    return {
        "transaction_id": tx_id,
        "account_id": account,
        "amount": amount,
        "date": day,
        "authorized_date": day,
        "name": name,
        "merchant_name": None,
        "pending": pending,
        "pending_transaction_id": replaces,
    }


def holding(security, quantity, price, value, basis):
    return {
        "account_id": "acc-ira",
        "security_id": security,
        "quantity": quantity,
        "institution_price": price,
        "institution_value": value,
        "cost_basis": basis,
    }


@pytest.fixture
def fake(monkeypatch):
    server = FakePlaid()
    monkeypatch.setattr(plaid, "TRANSPORT", httpx.MockTransport(server))
    return server


@pytest.fixture
def office(tmp_path, monkeypatch):
    monkeypatch.setattr("platform.node", lambda: "example-host")
    root = tmp_path / "office"
    initialize(root)
    ensure_credentials(root)
    return root


def linked(root, items=((ACCESS, "item-bank"), (OTHER, "item-broker"))):
    save_keys(root, {"plaid": {"client_id": CLIENT, "secret": SECRET, "environment": "sandbox"}})
    save_items(
        root,
        [
            {"item_id": item_id, "access_token": token, "institution": "Bank", "cursor": ""}
            for token, item_id in items
        ],
    )
    registry = [
        {"id": f"plaid-{n}", "provider": "plaid", "last4": "", "provider_ref": ref}
        for n, ref in enumerate(("acc-checking", "acc-card", "acc-ira"), 1)
    ]
    (root / "profile/accounts.json").write_text(json.dumps({"accounts": registry}))


def everything(root):
    return "".join(
        p.read_text(errors="ignore")
        for p in root.rglob("*")
        if p.is_file() and ".git/" not in str(p)
    )


def test_credentials_travel_in_headers_and_errors_hide_the_body(fake):
    api = PlaidAPI(CLIENT, SECRET, "sandbox")
    api.post("/link/token/create", {"products": ["transactions"]})
    path, headers, body = fake.requests[-1]
    assert headers["plaid-client-id"] == CLIENT and headers["plaid-secret"] == SECRET
    assert CLIENT not in json.dumps(body) and SECRET not in json.dumps(body)
    with pytest.raises(OfficeError) as caught:
        PlaidAPI(CLIENT, "WRONG_SECRET", "sandbox").post("/item/get", {})
    assert caught.value.reason == "invalid_credentials"
    assert SECRET not in caught.value.message and "bad keys" not in caught.value.message


def test_environment_and_credentials_are_validated():
    with pytest.raises(OfficeError, match="sandbox or production"):
        PlaidAPI(CLIENT, SECRET, "development")
    with pytest.raises(OfficeError) as caught:
        PlaidAPI("has space", SECRET, "sandbox")
    assert caught.value.reason == "invalid_credentials"


def test_readonly_surface():
    forbidden = ("transfer", "payment", "order", "trade", "withdraw", "deposit")
    names = [n for n in dir(Plaid) + dir(PlaidAPI) if not n.startswith("__")]
    assert not any(word in name.lower() for name in names for word in forbidden)
    source = open(plaid.__file__).read()
    for endpoint in ("/transfer/", "/payment_initiation/", "/processor/", "/item/remove"):
        assert endpoint not in source


def test_normalization_signs_balances_and_holdings():
    assert plaid.normalize_transaction(tx("t", "a", 12.34, "X"))["amount"] == "-12.34"
    assert plaid.normalize_transaction(tx("t", "a", -50, "X"))["amount"] == "50"
    card = plaid.balance(bank_accounts()[1])
    assert card == {"currency": "USD", "net_value": "-410.25", "debt": "410.25"}
    assert plaid.balance(bank_accounts()[0])["net_value"] == "1250.5"
    crypto = {"balances": {"current": 1, "unofficial_currency_code": "BTC"}}
    assert plaid.balance(crypto)["currency"] == "XXX"
    body = {
        "securities": SECURITIES,
        "holdings": [
            holding("sec-acme", 10, 101.25, 1012.5, 900),
            holding("sec-mmf", 619.48, 1, 619.48, 619.48),
            holding("sec-bond", 22000, 1, 22000, 21800),
            holding("sec-unknown", 1, 5, 5, None),
        ],
    }
    positions, cash = plaid.holdings_by_account(body)["acc-ira"]
    assert cash == Decimal("619.48")
    assert [p["symbol"] for p in positions] == ["ACME", "912828XX1", "plaid:sec-unknown"]
    assert positions[0] == {
        "symbol": "ACME",
        "qty": "10",
        "price": "101.25",
        "value": "1012.5",
        "cost_basis": "900",
    }


@pytest.mark.parametrize(
    ("kind", "subtype", "expected"),
    [
        ("buy", "buy", "trade"),
        ("sell", "sell", "trade"),
        ("cash", "qualified dividend", "dividend"),
        ("cash", "deposit", "transfer"),
        ("fee", "account fee", "fee"),
        ("transfer", "split", "corporate_action"),
        ("cancel", None, "other"),
    ],
)
def test_investment_kinds(kind, subtype, expected):
    assert plaid.investment_kind({"type": kind, "subtype": subtype}) == expected


def test_discovery_seeds_registry_kind_without_names():
    found = plaid.discovered(
        [*bank_accounts(), {"account_id": "x", "mask": "ab12", "type": "other"}]
    )
    assert found[0] == {
        "provider_ref": "acc-checking",
        "last4": "0000",
        "type": "checking",
        "role": "cash",
    }
    assert found[1]["role"] == "credit"
    assert found[2]["last4"] == "" and found[2]["role"] is None


def test_sync_writes_canonical_rows_and_commits_cursor(office, fake):
    linked(office)
    [result] = synchronize(office)
    assert result["status"] == "complete" and result["provider"] == "plaid"
    assert sorted(result["account_ids"]) == ["plaid-1", "plaid-2", "plaid-3"]
    state = project(office)
    balances = {r["account_id"]: r for r in state["balances"]}
    assert balances["plaid-1"]["net_value"] == "1250.5"
    assert balances["plaid-2"]["net_value"] == "-410.25" and balances["plaid-2"]["debt"] == "410.25"
    assert balances["plaid-3"]["cash"] == "619.48"
    assert {p["symbol"] for p in state["positions"]} == {"ACME", "912828XX1"}
    by_id = {t["provider_ids"][0]: t for t in state["transactions"]}
    assert by_id["tx-pay"]["amount"] == "2000"
    assert by_id["tx-coffee"]["pending"] and by_id["tx-coffee"]["amount"] == "-4.5"
    assert by_id["inv-buy"]["kind"] == "trade" and by_id["inv-buy"]["fees"] == "0.95"
    assert by_id["inv-div"]["kind"] == "dividend" and by_id["inv-div"]["amount"] == "3.1"
    items = {i["item_id"]: i for i in load_items(office)}
    assert items["item-bank"]["cursor"] == "CURSOR_SENTINEL_2"
    assert items["item-broker"]["cursor"] == ""
    # Secrets stay in the credentials folder; the office holds neither keys nor tokens.
    text = everything(office)
    for sentinel in (CLIENT, SECRET, ACCESS, OTHER, "CURSOR_SENTINEL_2"):
        assert sentinel not in text


def test_next_sync_continues_pending_and_expires_removed(office, fake):
    linked(office)
    synchronize(office)
    fake.pages["CURSOR_SENTINEL_2"] = {
        "added": [
            tx("tx-coffee-posted", "acc-checking", 4.75, "Coffee Shop", replaces="tx-coffee")
        ],
        "modified": [tx("tx-card", "acc-card", 61, "GROCER")],
        "removed": [
            {"transaction_id": "tx-coffee", "account_id": "acc-checking"},
            {"transaction_id": "tx-dropped", "account_id": "acc-checking"},
        ],
        "next_cursor": "c3",
        "has_more": False,
    }
    [result] = synchronize(office)
    assert result["status"] == "complete"
    rows = project(office)["transactions"]
    coffee = next(t for t in rows if "tx-coffee" in t["provider_ids"])
    assert coffee["provider_ids"] == ["tx-coffee", "tx-coffee-posted"]
    assert not coffee["pending"] and coffee["amount"] == "-4.75" and coffee.get("status") is None
    dropped = next(t for t in rows if "tx-dropped" in t["provider_ids"])
    assert dropped["status"] == "expired"
    card = next(t for t in rows if "tx-card" in t["provider_ids"])
    assert card["amount"] == "-61" and card["revision"] == 2
    assert {i["item_id"]: i["cursor"] for i in load_items(office)}["item-bank"] == "c3"


def test_dry_run_and_failed_ingest_keep_the_cursor(office, fake, monkeypatch):
    linked(office)
    synchronize(office, dry_run=True)
    assert all(i["cursor"] == "" for i in load_items(office))
    monkeypatch.setattr(
        "fo.sync.ingest",
        lambda *args, **kwargs: (_ for _ in ()).throw(OfficeError("invalid_record", "x")),
    )
    [result] = synchronize(office)
    assert result["status"] == "failed"
    assert all(i["cursor"] == "" for i in load_items(office))


def test_broken_institution_does_not_block_the_other(office, fake):
    linked(office)
    fake.errors[OTHER] = {"error_type": "ITEM_ERROR", "error_code": "ITEM_LOGIN_REQUIRED"}
    [result] = synchronize(office)
    assert result["status"] == "complete" and result["provider_errors"] == 1
    assert sorted(result["account_ids"]) == ["plaid-1", "plaid-2"]
    fake.errors[ACCESS] = fake.errors[OTHER]
    [result] = synchronize(office)
    assert result["status"] == "failed" and result["reason"] == "institution_errors"


def test_holdings_not_ready_keeps_last_snapshot(office, fake):
    linked(office)
    synchronize(office)
    fake.not_ready = True
    [result] = synchronize(office)
    assert result["status"] == "complete"
    assert "plaid-3" in result["account_ids"]
    assert "plaid-3" not in result["snapshot_account_ids"]
    assert {p["symbol"] for p in project(office)["positions"]} == {"ACME", "912828XX1"}


def test_sync_restarts_when_plaid_data_moves_mid_pagination(office, fake):
    linked(office, items=((ACCESS, "item-bank"),))
    fake.mutations = 1
    [result] = synchronize(office)
    assert result["status"] == "complete"
    calls = [p for p, _, _ in fake.requests if p == "/transactions/sync"]
    assert len(calls) == 3


def test_unmapped_accounts_point_to_fo_auth_plaid(office, fake):
    linked(office)
    (office / "profile/accounts.json").write_text(
        json.dumps(
            {
                "accounts": [
                    {
                        "id": "plaid-1",
                        "provider": "plaid",
                        "last4": "",
                        "provider_ref": "acc-checking",
                    }
                ]
            }
        )
    )
    [result] = synchronize(office)
    assert result["status"] == "complete" and result["unmapped_accounts"] == 2


def scripted(answers, confirms=()):
    answers, confirms = iter(answers), iter(confirms)
    return (
        lambda *args, **kwargs: next(answers),
        lambda *args, **kwargs: next(confirms),
    )


def fake_link(sessions):
    def link(token, environment, announce=None):
        sessions.append((token, environment))
        return {
            "public_token": PUBLIC,
            "institution": "First Platypus Bank",
            "institution_id": "ins_1",
        }

    return link


def test_connect_saves_own_credentials_privately_and_registers(office, fake):
    sessions = []
    prompt, confirm = scripted([CLIENT, SECRET, "sandbox", "bank"])
    result = plaid.connect(office, {}, prompt, confirm, fake_link(sessions))
    assert result == {
        "provider": "plaid",
        "authenticated": True,
        "repaired": 0,
        "linked": 1,
        "accounts": 2,
        "duplicate_institution": False,
    }
    assert sessions == [("link-sandbox-TOKEN", "sandbox")]
    create = next(b for p, _, b in fake.requests if p == "/link/token/create")
    assert create["products"] == ["transactions"] and create["optional_products"] == ["investments"]
    assert CLIENT not in json.dumps(create["user"])
    folder = credentials_dir(office)
    assert stat.S_IMODE(folder.stat().st_mode) == 0o700
    for name in ("keys.toml", "plaid-items.json"):
        assert stat.S_IMODE((folder / name).stat().st_mode) == 0o600
    assert load_items(office)[0]["access_token"] == ACCESS
    assert public_config(office)["secrets"]["plaid"] == {
        "client_id": "***",
        "secret": "***",
        "environment": "***",
    }
    registry = json.loads((office / "profile/accounts.json").read_text())["accounts"]
    assert [(a["id"], a["provider_ref"], a["role"]) for a in registry] == [
        ("plaid-1", "acc-checking", "cash"),
        ("plaid-2", "acc-card", "credit"),
    ]
    assert git(office, "status", "--porcelain").stdout == ""
    for sentinel in (CLIENT, SECRET, ACCESS, PUBLIC):
        assert sentinel not in everything(office)


def test_connect_brokerage_asks_for_investments_first(office, fake):
    sessions = []
    prompt, confirm = scripted([CLIENT, SECRET, "production", "brokerage"])
    plaid.connect(office, {}, prompt, confirm, fake_link(sessions))
    assert sessions[0][1] == "production"
    assert fake.requests[0][1]["host"] == "production.plaid.com"
    create = next(b for p, _, b in fake.requests if p == "/link/token/create")
    assert create["products"] == ["investments"] and create["optional_products"] == ["transactions"]


def test_rejected_credentials_save_nothing(office, fake):
    prompt, confirm = scripted([CLIENT, "WRONG", "sandbox", "bank"])
    with pytest.raises(OfficeError) as caught:
        plaid.connect(office, {}, prompt, confirm, fake_link([]))
    assert caught.value.reason == "invalid_credentials"
    assert not (credentials_dir(office) / "plaid-items.json").exists()
    assert "plaid" not in public_config(office)["secrets"]


def test_connect_repairs_broken_item_in_update_mode(office, fake):
    linked(office, items=((ACCESS, "item-bank"),))
    fake.items[ACCESS]["error"] = {"error_code": "ITEM_LOGIN_REQUIRED"}
    sessions = []
    prompt, confirm = scripted([], confirms=[True, False])
    keys = {"plaid": {"client_id": CLIENT, "secret": SECRET, "environment": "sandbox"}}
    result = plaid.connect(office, keys, prompt, confirm, fake_link(sessions))
    assert result["repaired"] == 1 and result["linked"] == 0
    create = next(b for p, _, b in fake.requests if p == "/link/token/create")
    assert create["access_token"] == ACCESS and "products" not in create
    assert not any(p == "/item/public_token/exchange" for p, _, _ in fake.requests)


def test_relinking_flags_a_duplicate_institution(office, fake):
    linked(office, items=((ACCESS, "item-old"),))
    items = load_items(office)
    items[0]["institution_id"] = "ins_1"
    save_items(office, items)
    prompt, confirm = scripted(["bank"], confirms=[True])
    keys = {"plaid": {"client_id": CLIENT, "secret": SECRET, "environment": "sandbox"}}
    result = plaid.connect(office, keys, prompt, confirm, fake_link([]))
    assert result["duplicate_institution"] is True
    assert {i["item_id"] for i in load_items(office)} == {"item-old", "item-bank"}


def test_cli_auth_plaid_prints_no_secrets(office, fake, monkeypatch):
    import typer
    from typer.testing import CliRunner

    from fo.cli import app

    answers = iter([CLIENT, SECRET, "sandbox", "bank"])
    monkeypatch.setattr(typer, "prompt", lambda *args, **kwargs: next(answers))
    monkeypatch.setattr("fo.providers.plaid_link.run_link", fake_link([]))
    result = CliRunner().invoke(app, ["--office", str(office), "--json", "auth", "plaid"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["accounts"] == 2
    for sentinel in (CLIENT, SECRET, ACCESS, PUBLIC):
        assert sentinel not in result.output


# The loopback Link page, driven by a client that plays the browser.


def browser(script):
    """An opener that runs script(url) on a thread, as a browser tab would."""

    tabs = []

    def opener(url):
        tab = threading.Thread(target=script, args=(url,), daemon=True)
        tabs.append(tab)
        tab.start()

    # run_link returns once the page posts its result, which can be before the tab has
    # read the response; join() waits for the tab to finish.
    opener.join = lambda: [tab.join(10) for tab in tabs]
    return opener


def post(url, body, origin=None, host=None):
    origin = origin or url.split("/", 3)[0] + "//" + url.split("/", 3)[2]
    headers = {"Origin": origin, "Content-Type": "application/json"}
    if host:
        headers["Host"] = host
    return httpx.post(url + "/finish", json=body, headers=headers, timeout=5)


def test_link_page_returns_public_token_once():
    from fo.providers.plaid_link import run_link

    seen = {}

    def tab(url):
        page = httpx.get(url, timeout=5)
        seen["page"] = page
        seen["foreign"] = post(
            url, {"status": "success", "public_token": "public-x"}, origin="https://evil.example"
        )
        seen["rebind"] = post(url, {"status": "exit"}, host="attacker.example")
        seen["ok"] = post(
            url,
            {
                "status": "success",
                "public_token": PUBLIC,
                "institution": {"name": "Bank", "institution_id": "ins_9"},
            },
        )

    opener = browser(tab)
    result = run_link("link-sandbox-TOKEN", "sandbox", opener=opener, timeout=10)
    opener.join()
    assert result == {"public_token": PUBLIC, "institution": "Bank", "institution_id": "ins_9"}
    page = seen["page"]
    assert page.status_code == 200 and "link-sandbox-TOKEN" in page.text
    policy = page.headers["content-security-policy"]
    assert "connect-src 'self' https://sandbox.plaid.com/" in policy
    # Scripts need the page's nonce; Link's injected style element must not be blocked.
    assert "script-src 'nonce-" in policy and "'unsafe-inline'" not in policy.split(";")[1]
    assert "style-src-elem 'unsafe-inline'" in policy
    assert "https://cdn.plaid.com/link/v2/stable/link-initialize.js" in page.text
    assert seen["foreign"].status_code == 404 and seen["rebind"].status_code == 404
    assert seen["ok"].status_code == 204


def test_link_page_hides_from_other_paths_and_reports_cancel():
    from fo.providers.plaid_link import run_link

    seen = {}

    def tab(url):
        base = url.rsplit("/", 1)[0]
        seen["guess"] = httpx.get(base + "/", timeout=5).status_code
        post(url, {"status": "exit"})

    with pytest.raises(OfficeError) as caught:
        run_link("link-sandbox-TOKEN", "sandbox", opener=browser(tab), timeout=10)
    assert caught.value.reason == "link_cancelled"
    assert seen["guess"] == 404


def test_link_page_times_out():
    from fo.providers.plaid_link import run_link

    with pytest.raises(OfficeError) as caught:
        run_link("link-sandbox-TOKEN", "sandbox", opener=lambda url: None, timeout=0.2)
    assert caught.value.reason == "link_timeout"


def test_setup_registers_linked_institutions_without_prompting(office, fake, monkeypatch):
    import typer

    from fo.setup import setup

    linked(office)
    (office / "profile/accounts.json").write_text(json.dumps({"accounts": []}))
    monkeypatch.setattr(typer, "prompt", lambda *a, **k: pytest.fail("prompted"))
    result = setup(office, ["plaid"])
    assert result["connections"] == [{"provider": "plaid", "status": "connected"}]
    assert result["sync"][0]["status"] == "complete"
    registry = json.loads((office / "profile/accounts.json").read_text())["accounts"]
    assert {a["provider_ref"] for a in registry} == {"acc-checking", "acc-card", "acc-ira"}


def test_onboarding_offers_plaid_repair():
    from fo.serve.onboarding import action, fix

    assert action("sync.errors.plaid") == "connect:plaid"
    assert fix("/office", "sync.errors.plaid")[0] == "fo auth plaid --office /office"
    assert action("sync.errors.simplefin") == "connect"
