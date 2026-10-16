import pytest

from fo.serve.auth import Access
from tests.offices import synthetic
from tests.serving import serving

TAILNET = "box.example.ts.net"


@pytest.fixture
def office(tmp_path):
    return synthetic(tmp_path / "office")


def test_every_route_requires_the_cookie(office, tmp_path):
    with serving(office, tmp_path) as (_, client):
        status, data = client.get("/api/networth", cookie=False)
        assert (status, data["reason"]) == (401, "unauthorized")
        status, body = client.get("/", cookie=False)
        assert status == 401 and b"Open the URL fo serve printed" in body
        assert client.get("/assets/app.js", cookie=False)[0] == 401
        assert client.get("/api/skills", cookie=False)[0] == 401
        assert client.get("/api/status", headers={"Cookie": "fo_session=wrong"}, cookie=False)[
            0
        ] == (401)
        assert client.get("/api/status", headers={"Cookie": "bad;;=\x7f"}, cookie=False)[0] == 401
        assert client.get("/api/networth")[0] == 200


def test_the_favicon_needs_no_cookie_and_reveals_nothing(office, tmp_path):
    with serving(office, tmp_path) as (_, client):
        status, _, body = client.request("GET", "/favicon.ico", cookie=False)
        assert (status, body) == (204, b"")
        assert client.get("/favicon.ico", host="evil.example")[0] == 421


def test_foreign_host_is_misdirected(office, tmp_path):
    with serving(office, tmp_path) as (_, client):
        for host in ("evil.example:80", f"evil.example:{client.port}", TAILNET, ""):
            status, data = client.get("/api/networth", host=host)
            assert (status, data["reason"]) == (421, "misdirected_request"), host
        assert client.get("/?t=" + client.token, host="evil.example")[0] == 421
        assert client.get("/api/networth", host=f"localhost:{client.port}")[0] == 200


def test_writes_require_a_same_origin_request(office, tmp_path):
    with serving(office, tmp_path) as (_, client):
        for origin in ("http://evil.example", f"https://127.0.0.1:{client.port}", None, "null"):
            status, data = client.post("/api/anything", headers={"Origin": origin})
            assert (status, data["reason"]) == (403, "forbidden_origin"), origin
        # Past every gate, the router answers.
        status, data = client.post("/api/anything")
        assert (status, data["reason"]) == (404, "unknown_route")
        status, data = client.post(
            "/api/anything", headers={"Origin": f"http://localhost:{client.port}"}
        )
        assert status == 404


def test_landing_sets_the_cookie_and_never_logs_the_token(office, tmp_path):
    with serving(office, tmp_path) as (app, client):
        status, headers, body = client.request("GET", "/?t=" + client.token, cookie=False)
        assert status == 200
        cookie = headers["set-cookie"]
        assert cookie.startswith(f"fo_session={client.token};")
        assert "HttpOnly" in cookie and "SameSite=Strict" in cookie and "Secure" not in cookie
        assert b"url=/" in body
        assert client.get("/?t=wrong", cookie=False)[0] == 401
        status, data = client.get("/api/networth?t=" + client.token, cookie=False)
        assert (status, data["reason"]) == (401, "unauthorized")
        assert b"400" in client.raw(f"GET /?t={client.token} extra HTTP/1.1\r\n\r\n".encode())
        assert b"400" in client.raw(f"GET /?t={client.token} HTTP/9\r\n\r\n".encode())
    assert app.log_lines and not any(client.token in line for line in app.log_lines)
    assert "GET / 200" in app.log_lines


def test_a_restart_rotates_the_token(office, tmp_path):
    with serving(office, tmp_path) as (_, first):
        old = first.token
    with serving(office, tmp_path) as (_, client):
        assert client.token != old
        client.cookie = old
        status, data = client.get("/api/networth")
        assert (status, data["reason"]) == (401, "unauthorized")
        assert "printed" in data["message"]


def remote(**options):
    return Access(remote=True, tailnet_name=TAILNET, **options)


def test_remote_mode_enforces_allowed_logins(office, tmp_path):
    access = remote(allowed_logins=["owner@example.com"])
    with serving(office, tmp_path, access=access) as (_, client):
        status, data = client.get("/api/status", host=TAILNET)
        assert (status, data["reason"]) == (403, "forbidden_login")
        listed = {"Tailscale-User-Login": "owner@example.com", "Tailscale-User-Name": "Owner"}
        status, data = client.get("/api/status", host=TAILNET, headers=listed)
        assert status == 200 and data["identity"] == {"login": "owner@example.com", "name": "Owner"}
        other = {"Tailscale-User-Login": "guest@example.com"}
        assert client.get("/api/status", host=TAILNET, headers=other)[0] == 403
        # Loopback names keep working, under the same login rule.
        assert client.get("/api/status", headers=listed)[0] == 200
        status, headers, _ = client.request("GET", "/?t=" + client.token, cookie=False)
        assert "Secure" in headers["set-cookie"]
        status, data = client.post(
            "/api/anything", host=TAILNET, headers={**listed, "Origin": f"https://{TAILNET}"}
        )
        assert status == 404


def test_remote_mode_without_allowlist_shows_identity_only(office, tmp_path):
    with serving(office, tmp_path, access=remote()) as (_, client):
        status, data = client.get("/api/status", host=f"{TAILNET}:443")
        assert status == 200 and data["identity"] is None and data["remote"] is True
    with serving(office, tmp_path) as (_, client):
        headers = {"Tailscale-User-Login": "owner@example.com"}
        assert client.get("/api/status", headers=headers)[1]["identity"] is None


def test_explicit_bind_address_is_an_accepted_host():
    access = Access(port=4790, bound="192.0.2.10")
    assert "192.0.2.10:4790" in access.hosts()
    assert "0.0.0.0:4790" not in Access(port=4790, bound="0.0.0.0").hosts()
