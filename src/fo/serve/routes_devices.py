"""Phone pairing: codes from the Mac, tokens for the phone, and the device list.

The Mac asks for a pairing code over loopback with the launch cookie; the phone redeems
it over the tailnet with its Tailscale identity and receives a device token once; the
phone then trades the token for a session cookie so the web app needs no token handling.
Listing and revoking need the launch cookie, never a device credential.
"""

from fo import __version__
from fo.envelope import encode
from fo.serve.auth import Denial

LOOPBACK_ONLY = Denial(403, "loopback_only", "Ask for a pairing code on this Mac.")
TAILNET_ONLY = Denial(
    403, "tailnet_only", "Pair over the tailnet; start fo serve with --remote first."
)
LAUNCH_COOKIE = Denial(403, "launch_cookie_required", "Manage devices from the Mac.")
BEARER = Denial(401, "bearer_required", "Send the device token as a bearer token.")


def owner(handler):
    """Device management needs the launch cookie; a device credential is refused."""
    if handler.auth != "cookie":
        handler.deny(LAUNCH_COOKIE, True)
        return False
    return True


def pairing(handler, params, query):
    if not owner(handler):
        return None
    if not handler.app.access.on_loopback(handler.headers):
        return handler.deny(LOOPBACK_ONLY, True)
    return handler.app.devices.issue_code()


def pair(handler):
    access = handler.app.access
    if not access.on_tailnet(handler.headers):
        return handler.deny(TAILNET_ONLY, True)
    origin = handler.headers.get("Origin")
    denial = (access.check_origin("POST", handler.headers) if origin else None) or (
        access.check_device_identity(handler.headers)
    )
    if denial:
        return handler.deny(denial, True)
    body = handler.body()
    return handler.app.devices.pair(body.get("code"), body.get("name"))


def login(handler, params, query):
    if handler.auth != "device" or not handler.app.access.bearer(handler.headers):
        return handler.deny(BEARER, True)
    device = handler.device
    session = handler.app.devices.start_session(device["id"])
    value = {"id": device["id"], "name": device.get("name"), "server_version": __version__}
    handler.send(
        200,
        encode(value),
        "application/json; charset=utf-8",
        {"Set-Cookie": handler.app.access.device_cookie_header(session)},
    )
    return None


def listing(handler, params, query):
    if not owner(handler):
        return None
    return {"devices": handler.app.devices.list()}


def revoke(handler, params, query):
    if not owner(handler):
        return None
    return handler.app.devices.revoke(params["id"])


# Routes reached before any credential check; each applies its own gates.
OPEN = {("POST", "/api/devices/pair"): pair}

ROUTES = [
    ("POST", r"/api/devices/pairing", pairing),
    ("POST", r"/api/devices/login", login),
    ("GET", r"/api/devices", listing),
    ("DELETE", r"/api/devices/(?P<id>[A-Za-z0-9_-]{1,64})", revoke),
]
