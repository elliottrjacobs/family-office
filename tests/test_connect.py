import json
import stat
import tomllib

import httpx
import pytest
from typer.testing import CliRunner

from fo.auth import save_keys
from fo.cli import app
from fo.config import provider_key
from fo.init import initialize
from fo.providers import http

KEY = "fixture-key-0001"


def invoke(*args, input=None):
    response = CliRunner().invoke(app, [*args, "--json"], input=input)
    return response.exit_code, json.loads(response.output)


@pytest.fixture
def office(tmp_path):
    root = tmp_path / "office"
    initialize(root)
    return root


@pytest.fixture
def provider(monkeypatch):
    """A recorded provider: answers each request with the queued response."""
    seen, queue = [], []

    def respond(request):
        seen.append(request)
        return queue.pop(0) if queue else httpx.Response(200, json={})

    monkeypatch.setattr(http, "TRANSPORT", httpx.MockTransport(respond))
    return seen, queue


@pytest.mark.parametrize(
    ("name", "host", "header"),
    [
        ("exa", "api.exa.ai", "x-api-key"),
        ("firecrawl", "api.firecrawl.dev", "authorization"),
        ("gemini", "generativelanguage.googleapis.com", "x-goog-api-key"),
        ("fred", "api.stlouisfed.org", None),
        ("alphavantage", "www.alphavantage.co", None),
    ],
)
def test_connect_validates_once_and_writes_a_private_key_file(office, provider, name, host, header):
    seen, queue = provider
    queue.append(httpx.Response(200, json={"Global Quote": {}, "results": [], "success": True}))
    code, data = invoke("connect", name, "--office", str(office), input=f"  {KEY}\n")
    assert (code, data) == (0, {"provider": name, "connected": True})
    assert len(seen) == 1 and seen[0].url.host == host
    if header:
        assert KEY in seen[0].headers[header]
    path = office / f"secrets/{name}.json"
    assert json.loads(path.read_text()) == {"api_key": KEY}
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    assert provider_key(office, name) == KEY
    assert KEY not in json.dumps(data)


@pytest.mark.parametrize(
    ("response", "reason"),
    [
        (httpx.Response(401, text="bad key fixture-key-0001 trace"), "invalid_key"),
        (httpx.Response(403, json={"error": "fixture-key-0001"}), "invalid_key"),
        (httpx.Response(500, text="internal fixture-key-0001"), "provider_error"),
    ],
)
def test_a_rejected_key_leaves_no_file_and_a_safe_reason(office, provider, response, reason):
    provider[1].append(response)
    code, data = invoke("connect", "exa", "--office", str(office), input=KEY)
    assert (code, data["reason"]) == (1, reason)
    assert KEY not in json.dumps(data) and "trace" not in json.dumps(data)
    assert not (office / "secrets/exa.json").exists()


def test_an_unreachable_provider_leaves_no_file(office, monkeypatch):
    def fail(request):
        raise httpx.ConnectError("synthetic failure carrying fixture-key-0001")

    monkeypatch.setattr(http, "TRANSPORT", httpx.MockTransport(fail))
    code, data = invoke("connect", "firecrawl", "--office", str(office), input=KEY)
    assert (code, data["reason"]) == (1, "provider_unreachable")
    assert "fixture-key" not in json.dumps(data)
    assert not (office / "secrets/firecrawl.json").exists()


def test_empty_or_multiline_keys_are_refused_without_a_call(office, provider):
    for value in ("", "   \n", "one two"):
        code, data = invoke("connect", "gemini", "--office", str(office), input=value)
        assert (code, data["reason"]) == (1, "invalid_key")
    assert provider[0] == []


def test_alphavantage_notice_is_an_invalid_key(office, provider):
    provider[1].append(httpx.Response(200, json={"Error Message": "Invalid API call."}))
    code, data = invoke("connect", "alphavantage", "--office", str(office), input=KEY)
    assert (code, data["reason"]) == (1, "invalid_key")
    assert not (office / "secrets/alphavantage.json").exists()


def test_remove_deletes_the_key_and_any_auth_entry(office, provider):
    invoke("connect", "fred", "--office", str(office), input=KEY)
    save_keys(office, {"fred": {"api_key": "older"}, "schwab": {"app_key": "kept"}})
    code, data = invoke("connect", "fred", "--remove", "--office", str(office))
    assert (code, data) == (0, {"provider": "fred", "connected": False})
    assert not (office / "secrets/fred.json").exists()
    keys = tomllib.loads((office / "secrets/keys.toml").read_text())
    assert keys == {"schwab": {"app_key": "kept"}}
    assert provider_key(office, "fred") is None
    assert invoke("connect", "fred", "--remove", "--office", str(office))[0] == 0


def test_unknown_provider_is_refused(office):
    code, data = invoke("connect", "schwab", "--office", str(office), input=KEY)
    assert (code, data["reason"]) == (1, "unknown_provider")


def test_edgar_contact_goes_to_office_toml_and_back_out(office, provider):
    before = tomllib.loads((office / "office.toml").read_text())
    code, data = invoke(
        "connect",
        "edgar",
        "--user-agent",
        "Fixture Household ops@example.com",
        "--office",
        str(office),
    )
    assert (code, data) == (0, {"provider": "edgar", "connected": True})
    after = tomllib.loads((office / "office.toml").read_text())
    assert after["providers"]["edgar"] == {"user_agent": "Fixture Household ops@example.com"}
    assert {k: v for k, v in after.items() if k != "providers"} == {
        k: v for k, v in before.items() if k != "providers"
    }
    assert after["providers"]["alphavantage"] == before["providers"]["alphavantage"]
    invoke(
        "connect", "edgar", "--user-agent", "Other Name ops@example.com", "--office", str(office)
    )
    text = (office / "office.toml").read_text()
    assert text.count("user_agent") == 1 and "Other Name" in text
    code, data = invoke("connect", "edgar", "--remove", "--office", str(office))
    assert (code, data["connected"]) == (0, False)
    assert "user_agent" not in tomllib.loads((office / "office.toml").read_text())["providers"].get(
        "edgar", {}
    )
    assert provider[0] == []


def test_edgar_needs_a_name_and_email(office):
    for value in (None, "nobody", 'Name "quoted" x@y.z\n[x]'):
        args = ["connect", "edgar", "--office", str(office)]
        if value is not None:
            args[2:2] = ["--user-agent", value]
        code, data = invoke(*args)
        assert (code, data["reason"]) == (1, "invalid_user_agent")


@pytest.mark.parametrize(
    "args", [["connect", "exa"], ["connect", "exa", "--remove"], ["--json", "connect"]]
)
def test_connect_is_refused_under_the_run_marker(office, provider, monkeypatch, args):
    monkeypatch.setenv("FO_SERVE_RUN", str(office))
    monkeypatch.setenv("FO_OFFICE", str(office))
    code, data = invoke(*args, input=KEY)
    assert (code, data["reason"]) == (1, "serve_run_restricted")
    assert provider[0] == []
    assert not (office / "secrets/exa.json").exists()


def test_read_only_mode_refuses_connect(office, provider):
    code, data = invoke("connect", "exa", "--read-only", "--office", str(office), input=KEY)
    assert (code, data["reason"]) == (1, "read_only")
