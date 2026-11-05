"""Access control for fo serve: a per-launch token cookie plus Host and Origin checks.

Loopback is reachable by DNS-rebinding pages and by other OS users, so every route needs
the cookie in every mode. Tailscale identity headers only narrow access in remote mode;
any local process can send them, so they never grant access on their own.

Paired devices are a second authenticator, honoured only in remote mode on requests
addressed to the tailnet name: a bearer device token, or the session cookie that
POST /api/devices/login exchanges it for. On loopback Hosts a bearer token is ignored and
the cookie rules apply unchanged, so a rebinding page gains nothing from a stolen token.
"""

import hmac
import secrets
from dataclasses import dataclass, field
from http.cookies import CookieError, SimpleCookie

from fo.errors import OfficeError

COOKIE = "fo_session"
LOGIN_HEADER = "Tailscale-User-Login"
NAME_HEADER = "Tailscale-User-Name"
LOOPBACK_NAMES = ("127.0.0.1", "localhost")


@dataclass
class Denial:
    status: int
    reason: str
    message: str


@dataclass
class Access:
    port: int = 0
    bound: str = "127.0.0.1"
    remote: bool = False
    tailnet_name: str = ""
    allowed_logins: list[str] = field(default_factory=list)
    # Generated per process, so a restart rotates it and stale cookies stop working.
    token: str = field(default_factory=lambda: secrets.token_urlsafe(32))
    # The paired-device registry (fo.serve.devices.Devices); None means no devices.
    devices: object | None = None

    def hosts(self):
        names = {f"{name}:{self.port}" for name in LOOPBACK_NAMES}
        if self.bound not in ("127.0.0.1", "0.0.0.0", "::", "localhost"):
            names.add(f"{self.bound}:{self.port}")
        if self.remote and self.tailnet_name:
            names |= {self.tailnet_name, f"{self.tailnet_name}:443"}
        return names

    def origins(self):
        """The app's own origins; a browser omits the default port from Origin."""
        local = [h for h in self.hosts() if h.split(":")[0] != self.tailnet_name]
        result = {"http://" + h for h in local}
        if self.remote and self.tailnet_name:
            result.add("https://" + self.tailnet_name)
        return result

    def landing_url(self):
        return f"http://127.0.0.1:{self.port}/?t={self.token}"

    def valid_token(self, value):
        return bool(value) and hmac.compare_digest(value.encode(), self.token.encode())

    def cookie_header(self, headers=None):
        """Secure only when the request came over the tailnet (HTTPS through tailscale serve).

        A loopback request in --remote mode is plain HTTP, and WebKit drops a Secure cookie
        set over it, which left the Mac app's own web view without a session.
        """
        attributes = "HttpOnly; SameSite=Strict; Path=/"
        secure = self.on_tailnet(headers or {})
        return f"{COOKIE}={self.token}; {attributes}" + ("; Secure" if secure else "")

    def check_host(self, headers):
        if headers.get("Host", "") not in self.hosts():
            return Denial(421, "misdirected_request", "Open the address fo serve printed.")
        return None

    def on_tailnet(self, headers):
        """The request names the tailnet host, which only tailscale serve forwards."""
        if not self.remote or not self.tailnet_name:
            return False
        return headers.get("Host", "") in {self.tailnet_name, f"{self.tailnet_name}:443"}

    def on_loopback(self, headers):
        return headers.get("Host", "").rpartition(":")[0] in LOOPBACK_NAMES

    def session_cookie(self, headers):
        try:
            cookie = SimpleCookie(headers.get("Cookie", ""))
        except CookieError:
            cookie = SimpleCookie()
        morsel = cookie.get(COOKIE)
        return morsel.value if morsel else None

    def check_cookie(self, headers):
        if not self.valid_token(self.session_cookie(headers)):
            return Denial(
                401, "unauthorized", "Open the URL fo serve printed; a restart issues a new one."
            )
        return None

    @staticmethod
    def bearer(headers):
        scheme, _, value = headers.get("Authorization", "").partition(" ")
        value = value.strip()
        return value if scheme.lower() == "bearer" and value else None

    def check_device_identity(self, headers):
        """Device credentials need a tailnet login, listed when an allowlist is set."""
        if not headers.get(LOGIN_HEADER):
            return Denial(403, "forbidden_login", "This tailnet login is not allowed.")
        return self.check_identity(headers)

    def check_device(self, headers):
        """(device, None) for a paired bearer token over the tailnet, else (None, Denial).

        Only meaningful when on_tailnet(headers) holds; on loopback the caller never asks.
        """
        if not self.on_tailnet(headers):
            return None, Denial(401, "unauthorized", "Device tokens work only over the tailnet.")
        device = None
        if self.devices is not None:
            try:
                device = self.devices.match(self.bearer(headers))
            except OfficeError:
                device = None
        if device is None:
            return None, Denial(
                401, "unknown_device", "This device is not paired; pair it again from the Mac."
            )
        denial = self.check_device_identity(headers)
        return (None, denial) if denial else (device, None)

    def check_origin(self, method, headers):
        """Non-GET requests must come from the page's own origin."""
        if method == "GET":
            return None
        if headers.get("Origin") not in self.origins():
            return Denial(403, "forbidden_origin", "Requests must come from the companion app.")
        return None

    def identity(self, headers):
        if not self.remote:
            return None
        login = headers.get(LOGIN_HEADER)
        return {"login": login, "name": headers.get(NAME_HEADER)} if login else None

    def check_identity(self, headers):
        """With an allowlist, a missing or unlisted login fails closed; Funnel sends none.

        Only requests that name the tailnet host carry a header tailscale serve set. On
        loopback any local process can send one, so it proves nothing there and the launch
        cookie stays the sole gate; that is what lets the Mac app, a loopback client, keep
        working while --remote and an allowlist are on.
        """
        if not self.remote or not self.allowed_logins or not self.on_tailnet(headers):
            return None
        login = headers.get(LOGIN_HEADER)
        if login not in self.allowed_logins:
            return Denial(403, "forbidden_login", "This tailnet login is not allowed.")
        return None

    def check(self, method, headers):
        """Every gate after the landing route, in order: cookie, origin, identity."""
        return self.authenticate(method, headers)[1]

    def authenticate(self, method, headers):
        """(kind, Denial or None, device): kind is "cookie", "device", or None.

        Over the tailnet a bearer token is checked as a device token and needs no Origin,
        since a browser never attaches one by itself; a device's login session cookie is
        accepted there too. Everywhere else only the launch cookie counts.
        """
        if self.on_tailnet(headers) and self.bearer(headers):
            device, denial = self.check_device(headers)
            return ("device" if device else None), denial, device
        if self.on_tailnet(headers) and self.devices is not None:
            device = self.devices.session(self.session_cookie(headers))
            if device is not None:
                denial = self.check_origin(method, headers) or self.check_device_identity(headers)
                return ("device" if not denial else None), denial, device
        denial = (
            self.check_cookie(headers)
            or self.check_origin(method, headers)
            or self.check_identity(headers)
        )
        return ("cookie" if not denial else None), denial, None

    def device_cookie_header(self, value):
        return f"{COOKIE}={value}; HttpOnly; SameSite=Strict; Path=/; Secure"
