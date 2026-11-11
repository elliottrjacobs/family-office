"""Device tokens and phone pairing, with synthetic offices and an injected clock."""

import json
import threading

import pytest

from fo import __version__
from fo.config import credentials_dir
from fo.serve import announce, prepare
from fo.serve.auth import Access
from fo.serve.devices import CODE_ATTEMPTS, Devices
from tests.offices import synthetic
from tests.serving import Client, serving

TAILNET = "machine.your-tailnet.ts.net"
OWNER = {"Tailscale-User-Login": "owner@example.com", "Tailscale-User-Name": "Owner"}
GUEST = {"Tailscale-User-Login": "guest@example.com"}


class Clock:
    def __init__(self, now=1_800_000_000.0):
        self.now = now

    def __call__(self):
        return self.now


@pytest.fixture
def office(tmp_path):
    return synthetic(tmp_path / "office")


@pytest.fixture
def clock():
    return Clock()


def remote(**options):
    return Access(
        remote=True, tailnet_name=TAILNET, allowed_logins=["owner@example.com"], **options
    )


def harness(office, tmp_path, clock, access=None):
    return serving(
        office,
        tmp_path,
        access=access or remote(),
        devices=Devices(lambda: office, clock=clock),
    )


def bearer(token, identity=OWNER):
    return {"Authorization": f"Bearer {token}", **identity}


def code(client):
    # With an allowlist, loopback requests carry the login rule too (see test_serve_auth).
    status, data = client.post("/api/devices/pairing", headers=OWNER)
    assert status == 200, data
    return data["code"]


def pair(client, value, name="Test phone", identity=OWNER):
    return client.post(
        "/api/devices/pair",
        {"code": value, "name": name},
        host=TAILNET,
        cookie=False,
        headers={**identity, "Origin": None},
    )


def paired(client):
    status, data = pair(client, code(client))
    assert status == 200, data
    return data


def test_a_bearer_token_on_loopback_is_ignored(office, tmp_path, clock):
    with harness(office, tmp_path, clock) as (_, client):
        token = paired(client)["token"]
        for host in (None, f"localhost:{client.port}"):
            status, data = client.get("/api/status", host=host, cookie=False, headers=bearer(token))
            assert (status, data["reason"]) == (401, "unauthorized"), host
        # The cookie rules apply unchanged there: a valid cookie passes, bearer or not.
        assert client.get("/api/status", headers=bearer("nonsense"))[0] == 200


def test_a_bearer_token_over_the_tailnet_needs_an_allowed_identity(office, tmp_path, clock):
    with harness(office, tmp_path, clock) as (_, client):
        token = paired(client)["token"]
        status, data = client.get("/api/status", host=TAILNET, cookie=False, headers=bearer(token))
        assert status == 200 and data["server_version"] == data["version"]
        assert client.get("/api/networth", host=TAILNET, cookie=False, headers=bearer(token))[
            0
        ] == (200)
        status, data = client.get(
            "/api/status", host=TAILNET, cookie=False, headers=bearer(token, GUEST)
        )
        assert (status, data["reason"]) == (403, "forbidden_login")
        status, data = client.get(
            "/api/status", host=TAILNET, cookie=False, headers=bearer(token, {})
        )
        assert (status, data["reason"]) == (403, "forbidden_login")
        status, data = client.get(
            "/api/status", host=TAILNET, cookie=False, headers=bearer("not-a-token")
        )
        assert (status, data["reason"]) == (401, "unknown_device")


def test_without_an_allowlist_a_device_still_needs_a_tailnet_login(office, tmp_path, clock):
    access = Access(remote=True, tailnet_name=TAILNET)
    with harness(office, tmp_path, clock, access) as (_, client):
        token = paired(client)["token"]
        assert client.get("/api/status", host=TAILNET, cookie=False, headers=bearer(token))[0] == (
            200
        )
        status, data = client.get(
            "/api/status", host=TAILNET, cookie=False, headers=bearer(token, {})
        )
        assert (status, data["reason"]) == (403, "forbidden_login")


def test_a_revoked_token_fails_on_its_next_request(office, tmp_path, clock):
    with harness(office, tmp_path, clock) as (_, client):
        device = paired(client)
        other = paired(client)
        status, headers, _ = client.request(
            "POST",
            "/api/devices/login",
            body={},
            host=TAILNET,
            cookie=False,
            headers={**bearer(device["token"]), "Origin": None},
        )
        session = headers["set-cookie"].split(";")[0].split("=", 1)[1]
        sessioned = {**OWNER, "Cookie": f"fo_session={session}"}
        assert client.get("/api/status", host=TAILNET, cookie=False, headers=sessioned)[0] == 200
        status, data = client.request("DELETE", f"/api/devices/{device['id']}", headers=OWNER)[::2]
        assert status == 200 and json.loads(data) == {"id": device["id"], "revoked": True}
        status, data = client.get(
            "/api/status", host=TAILNET, cookie=False, headers=bearer(device["token"])
        )
        assert (status, data["reason"]) == (401, "unknown_device")
        # Its login session ends with it.
        status, data = client.get("/api/status", host=TAILNET, cookie=False, headers=sessioned)
        assert (status, data["reason"]) == (401, "unauthorized")
        assert (
            client.get("/api/status", host=TAILNET, cookie=False, headers=bearer(other["token"]))[0]
            == 200
        )
        assert client.request("DELETE", f"/api/devices/{device['id']}", headers=OWNER)[0] == 404
        assert client.request("DELETE", "/api/devices/../secrets", headers=OWNER)[0] in (404, 400)


def test_revoking_needs_a_same_origin_request(office, tmp_path, clock):
    with harness(office, tmp_path, clock) as (_, client):
        device = paired(client)
        status, _, data = client.request(
            "DELETE", f"/api/devices/{device['id']}", headers={"Origin": "http://evil.example"}
        )
        assert (status, json.loads(data)["reason"]) == (403, "forbidden_origin")
        assert len(client.get("/api/devices", headers=OWNER)[1]["devices"]) == 1


def test_a_pairing_code_is_single_use(office, tmp_path, clock):
    with harness(office, tmp_path, clock) as (_, client):
        value = code(client)
        assert len(value) == 8 and not set(value) & set("01OIL")
        assert pair(client, value.lower())[0] == 200
        status, data = pair(client, value)
        assert (status, data["reason"]) == (403, "invalid_pairing_code")
        status, data = pair(client, "")
        assert (status, data["reason"]) == (403, "invalid_pairing_code")
        # A new code replaces the outstanding one.
        first, second = code(client), code(client)
        assert pair(client, first)[0] == 403
        assert pair(client, second)[0] == 200


def test_a_pairing_code_expires_after_five_minutes(office, tmp_path, clock):
    with harness(office, tmp_path, clock) as (_, client):
        status, data = client.post("/api/devices/pairing", headers=OWNER)
        assert data["expires_at"].endswith("+00:00")
        clock.now += 299
        value = code(client)
        clock.now += 300
        status, data = pair(client, value)
        assert (status, data["reason"]) == (403, "invalid_pairing_code")


def test_repeated_wrong_codes_discard_the_outstanding_code(office, tmp_path, clock):
    with harness(office, tmp_path, clock) as (_, client):
        value = code(client)
        for _ in range(CODE_ATTEMPTS):
            assert pair(client, "WRONGWRO")[0] == 403
        assert pair(client, value)[0] == 403


def test_pairing_needs_the_tailnet_and_an_identity(office, tmp_path, clock):
    with harness(office, tmp_path, clock) as (_, client):
        value = code(client)
        status, data = pair(client, value, identity={})
        assert (status, data["reason"]) == (403, "forbidden_login")
        status, data = pair(client, value, identity=GUEST)
        assert (status, data["reason"]) == (403, "forbidden_login")
        status, data = client.post(
            "/api/devices/pair", {"code": value, "name": "x"}, cookie=False, headers=OWNER
        )
        assert (status, data["reason"]) == (403, "tailnet_only")
        status, data = client.post(
            "/api/devices/pair",
            {"code": value, "name": "x"},
            host=TAILNET,
            cookie=False,
            headers={**OWNER, "Origin": "https://evil.example"},
        )
        assert (status, data["reason"]) == (403, "forbidden_origin")
        status, data = pair(client, value, name="\x00")
        assert (status, data["reason"]) == (400, "invalid_request")
        # The refusals did not spend the code.
        assert pair(client, value)[0] == 200
    # Without --remote there is no tailnet to pair over.
    with harness(office, tmp_path, clock, Access()) as (_, client):
        value = code(client)
        status, data = pair(client, value)
        assert (status, data["reason"]) == (421, "misdirected_request")
        status, data = client.post(
            "/api/devices/pair", {"code": value, "name": "x"}, cookie=False, headers=OWNER
        )
        assert (status, data["reason"]) == (403, "tailnet_only")


def test_codes_come_only_from_loopback_with_the_launch_cookie(office, tmp_path, clock):
    with harness(office, tmp_path, clock) as (_, client):
        status, data = client.post("/api/devices/pairing", cookie=False, headers=OWNER)
        assert (status, data["reason"]) == (401, "unauthorized")
        status, data = client.post(
            "/api/devices/pairing",
            host=TAILNET,
            headers={**OWNER, "Origin": f"https://{TAILNET}"},
        )
        assert (status, data["reason"]) == (403, "loopback_only")
        token = paired(client)["token"]
        for method, path in (("POST", "/api/devices/pairing"), ("GET", "/api/devices")):
            status, _, data = client.request(
                method, path, host=TAILNET, cookie=False, headers=bearer(token)
            )
            assert (status, json.loads(data)["reason"]) == (403, "launch_cookie_required")


def test_login_sets_a_secure_session_cookie(office, tmp_path, clock):
    with harness(office, tmp_path, clock) as (app, client):
        device = paired(client)
        status, headers, data = client.request(
            "POST",
            "/api/devices/login",
            body={},
            host=TAILNET,
            cookie=False,
            headers={**bearer(device["token"]), "Origin": None},
        )
        assert status == 200
        body = json.loads(data)
        assert body == {
            "id": device["id"],
            "name": "Test phone",
            "server_version": client.get("/api/status", headers=OWNER)[1]["version"],
        }
        cookie = headers["set-cookie"]
        attributes = {part.strip() for part in cookie.split(";")[1:]}
        assert {"HttpOnly", "SameSite=Strict", "Secure", "Path=/"} <= attributes
        session = cookie.split(";")[0].split("=", 1)[1]
        assert session not in (device["token"], app.access.token)
        sessioned = {**OWNER, "Cookie": f"fo_session={session}"}
        assert client.get("/api/status", host=TAILNET, cookie=False, headers=sessioned)[0] == 200
        assert client.get("/", host=TAILNET, cookie=False, headers=sessioned)[0] == 200
        # The session is a device credential: tailnet only, never device management.
        assert client.get("/api/status", cookie=False, headers=sessioned)[0] == 401
        assert client.get("/api/devices", host=TAILNET, cookie=False, headers=sessioned)[0] == 403
        status, data = client.get(
            "/api/status", host=TAILNET, cookie=False, headers={**sessioned, **GUEST}
        )
        assert status == 403
        # Login needs the bearer token itself.
        status, data = client.post(
            "/api/devices/login",
            host=TAILNET,
            cookie=False,
            headers={**sessioned, "Origin": f"https://{TAILNET}"},
        )
        assert (status, data["reason"]) == (401, "bearer_required")
        status, data = client.post("/api/devices/login", headers=OWNER)
        assert (status, data["reason"]) == (401, "bearer_required")


def test_devices_file_is_private_and_holds_no_token(office, tmp_path, clock):
    with harness(office, tmp_path, clock) as (app, client):
        device = paired(client)
        path = credentials_dir(office) / "devices.json"
        assert not (office / "secrets").exists()
        assert not path.is_relative_to(office)
        assert path.stat().st_mode & 0o777 == 0o600
        assert path.parent.stat().st_mode & 0o777 == 0o700
        text = path.read_text()
        assert device["token"] not in text
        (record,) = json.loads(text)["devices"]
        assert set(record) == {"id", "name", "token_sha256", "created", "last_seen"}
        status, data = client.get("/api/devices", headers=OWNER)
        assert status == 200
        assert data["devices"] == [{k: record[k] for k in ("id", "name", "created", "last_seen")}]
        assert not any(device["token"] in line for line in app.log_lines)
        assert not any(app.access.token in line for line in app.log_lines)


def test_last_seen_moves_at_most_once_a_minute(office, tmp_path, clock):
    with harness(office, tmp_path, clock) as (_, client):
        token = paired(client)["token"]
        path = credentials_dir(office) / "devices.json"
        before = path.stat().st_mtime_ns, path.read_text()
        clock.now += 30
        assert client.get("/api/status", host=TAILNET, cookie=False, headers=bearer(token))[0] == (
            200
        )
        assert (path.stat().st_mtime_ns, path.read_text()) == before
        clock.now += 31
        client.get("/api/status", host=TAILNET, cookie=False, headers=bearer(token))
        (record,) = json.loads(path.read_text())["devices"]
        assert record["last_seen"] > record["created"]
        assert (
            client.get("/api/devices", headers=OWNER)[1]["devices"][0]["last_seen"]
            == record["last_seen"]
        )


def test_a_restart_keeps_devices_paired_and_rotates_the_browser_token(office, tmp_path, clock):
    with harness(office, tmp_path, clock) as (_, first):
        token = paired(first)["token"]
        old = first.token
    with harness(office, tmp_path, clock) as (_, client):
        assert client.token != old
        status, data = client.get("/api/status", host=TAILNET, cookie=False, headers=bearer(token))
        assert status == 200
        client.cookie = old
        assert client.get("/api/status")[0] == 401


def test_pairing_without_an_office_explains_itself(tmp_path, clock):
    empty = tmp_path / "empty"
    with serving(empty, tmp_path, access=remote()) as (_, client):
        status, data = client.post("/api/devices/pairing", headers=OWNER)
        assert status == 200
        status, data = pair(client, data["code"])
        assert (status, data["reason"]) == (404, "office_not_found")
        status, data = client.get("/api/devices", headers=OWNER)
        assert (status, data["reason"]) == (404, "office_not_found")


def test_the_app_handshake_is_one_json_line_and_the_token_stays_out_of_the_log(
    office, tmp_path, capsys
):
    server, lines = prepare(office, port=0, app_mode=True)
    server.app.log_lines = []
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        assert announce(server, lines, app_mode=True) is False
        first, *rest = capsys.readouterr().out.splitlines()
        shake = json.loads(first)
        assert shake == {
            "port": server.server_address[1],
            "token": server.app.access.token,
            "office": str(office.resolve()),
            "state": shake["state"],
            "version": __version__,
        }
        assert shake["state"] in ("ready", "stale", "never_synced", "unconnected", "offline")
        assert rest == lines and not any("Press Enter" in line for line in lines)
        client = Client(server)
        status, headers, _ = client.request("GET", "/?t=" + client.token, cookie=False)
        assert status == 200 and "set-cookie" in headers
        assert client.get("/api/status")[0] == 200
    finally:
        server.shutdown()
        server.server_close()
    log = server.app.log_lines
    assert "GET / 200" in log and not any(shake["token"] in line for line in log)


def test_the_handshake_reports_onboarding_without_an_office(tmp_path, capsys):
    server, lines = prepare(tmp_path / "empty", port=0, app_mode=True)
    try:
        announce(server, lines, app_mode=True)
        shake = json.loads(capsys.readouterr().out.splitlines()[0])
        assert shake["office"] is None and shake["state"] == "uninitialized_path"
    finally:
        server.server_close()
    # Without --app only the human-readable lines are printed.
    server, lines = prepare(tmp_path / "empty", port=0)
    try:
        announce(server, lines)
        out = capsys.readouterr().out.splitlines()
        assert out == lines and not out[0].startswith("{")
    finally:
        server.server_close()
